from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from ifc import (
    extract_ifc,
    extract_spatial_elements,
    infer_cross_model_geometry_locations,
    load_ifc,
)
from mapping import map_assets
from models import IfcAsset, Relation, SpatialElement
from points import load_and_link_points
from rdf import build_graph, write_outputs
from validation import build_validation_report, write_json


DEFAULT_BASE_NS = "https://example.org/building#"


def _paths(values: str | Path | Sequence[str | Path], label: str) -> list[Path]:
    if isinstance(values, (str, Path)):
        result = [Path(values)]
    else:
        result = [Path(value) for value in values]
    if not result:
        raise ValueError(f"At least one {label} IFC path is required")
    return result


def _merge_assets(extractions) -> tuple[list[IfcAsset], list[str]]:
    assets: Dict[str, IfcAsset] = {}
    duplicates: list[str] = []
    for extraction in extractions:
        for asset in extraction.assets:
            if asset.ifc_guid in assets:
                duplicates.append(asset.ifc_guid)
                continue
            assets[asset.ifc_guid] = asset
    return list(assets.values()), sorted(set(duplicates))


def _merge_spatial(
    mep_extractions,
    arc_spatial_groups: Iterable[Iterable[SpatialElement]],
) -> tuple[list[SpatialElement], list[str], set[str]]:
    # MEP spatial stubs support explicit containment. ARC values overwrite the
    # same GlobalId and are the authoritative source of spatial attributes.
    spatial: Dict[str, SpatialElement] = {}
    for extraction in mep_extractions:
        for item in extraction.spatial:
            spatial.setdefault(item.ifc_guid, item)

    duplicate_arc_guids: list[str] = []
    arc_guids: set[str] = set()
    for group in arc_spatial_groups:
        for item in group:
            if item.ifc_guid in arc_guids:
                duplicate_arc_guids.append(item.ifc_guid)
                continue
            arc_guids.add(item.ifc_guid)
            spatial[item.ifc_guid] = item
    return list(spatial.values()), sorted(set(duplicate_arc_guids)), arc_guids


def _merge_relations(
    mep_extractions,
    asset_guids: set[str],
    spatial_guids: set[str],
    arc_guids: set[str],
) -> list[Relation]:
    relations: list[Relation] = []
    seen: set[tuple[str, str, str]] = set()
    for extraction in mep_extractions:
        for relation in extraction.relations:
            key = (relation.subject_guid, relation.predicate, relation.object_guid)
            if key in seen or relation.subject_guid not in asset_guids:
                continue
            if relation.predicate == "brick:hasLocation":
                if relation.object_guid not in spatial_guids:
                    continue
                if relation.object_guid not in arc_guids:
                    relation = replace(
                        relation,
                        review_required=True,
                        confidence=min(relation.confidence, 0.75),
                        evidence={**relation.evidence, "arc_space_match": False},
                    )
            elif relation.predicate == "brick:feeds" and relation.object_guid not in asset_guids:
                continue
            seen.add(key)
            relations.append(relation)
    return relations


def _status(complete: bool, available: bool = True) -> str:
    if complete:
        return "PASS"
    return "WARN" if available else "FAIL"


def run_pipeline(
    mep_ifc_paths: str | Path | Sequence[str | Path],
    arc_ifc_paths: str | Path | Sequence[str | Path],
    output_dir: str | Path,
    mapping_csv_path: str | Path,
    points_csv: str | Path | None = None,
    base_ns: str = DEFAULT_BASE_NS,
    geometry_fallback: bool = False,
) -> Dict[str, Any]:
    if not base_ns.startswith(("http://", "https://")) or not base_ns.endswith(("#", "/")):
        raise ValueError("base_ns must be an HTTP(S) namespace ending in '#' or '/'")

    mep_paths = _paths(mep_ifc_paths, "MEP")
    arc_paths = _paths(arc_ifc_paths, "ARC")
    mep_bundles = [load_ifc(path) for path in mep_paths]
    arc_bundles = [load_ifc(path) for path in arc_paths]
    mep_extractions = [extract_ifc(bundle) for bundle in mep_bundles]
    arc_spatial_groups = [extract_spatial_elements(bundle) for bundle in arc_bundles]

    assets, duplicate_asset_guids = _merge_assets(mep_extractions)
    spatial, duplicate_arc_guids, arc_guids = _merge_spatial(mep_extractions, arc_spatial_groups)
    asset_guids = {item.ifc_guid for item in assets}
    spatial_guids = {item.ifc_guid for item in spatial}
    relations = _merge_relations(
        mep_extractions,
        asset_guids=asset_guids,
        spatial_guids=spatial_guids,
        arc_guids=arc_guids,
    )

    geometry_diagnostics: Dict[str, Any] = {}
    if geometry_fallback:
        inferred, geometry_diagnostics = infer_cross_model_geometry_locations(
            list(zip(mep_bundles, mep_extractions)),
            arc_bundles,
            relations,
        )
        existing = {(item.subject_guid, item.predicate, item.object_guid) for item in relations}
        relations.extend(
            item
            for item in inferred
            if (item.subject_guid, item.predicate, item.object_guid) not in existing
        )

    equipment = map_assets(assets, mapping_csv_path)
    points = []
    point_links = []
    unresolved_points = []
    if points_csv is not None:
        points, point_links, unresolved_points = load_and_link_points(points_csv, equipment, base_ns)

    graph = build_graph(
        spatial=spatial,
        equipment=equipment,
        points=points,
        relations=relations,
        point_links=point_links,
        base_ns=base_ns,
    )

    classified_count = sum(item.bdns_code is not None for item in assets)
    located_assets = {
        item.subject_guid for item in relations if item.predicate == "brick:hasLocation"
    }
    point_spatial_contexts = sum(
        item.equipment_guid in located_assets for item in point_links
    )
    explicit_locations = sum(
        item.predicate == "brick:hasLocation" and item.method == "explicit"
        for item in relations
    )
    inferred_locations = sum(
        item.predicate == "brick:hasLocation" and item.method != "explicit"
        for item in relations
    )
    feeds = [item for item in relations if item.predicate == "brick:feeds"]
    ambiguous_connections = sum(
        extraction.audit["counts"]["undirected_port_connections"]
        for extraction in mep_extractions
    )
    hierarchy_links = sum(
        item.parent_guid in arc_guids
        for item in spatial
        if item.ifc_guid in arc_guids
    )
    capabilities = {
        "IDENTITY": {
            "status": _status(bool(assets) and not duplicate_asset_guids, bool(assets)),
            "evidence": f"{len(assets)} unique equipment; {len(duplicate_asset_guids)} duplicate GlobalIds",
        },
        "CLASSIFICATION": {
            "status": _status(bool(assets) and classified_count == len(assets), bool(assets)),
            "evidence": f"{classified_count}/{len(assets)} equipment associated with BDNS",
        },
        "SPATIAL_HIERARCHY": {
            "status": _status(bool(arc_guids) and hierarchy_links > 0, bool(arc_guids)),
            "evidence": f"{len(arc_guids)} ARC spatial elements; {hierarchy_links} hierarchy links",
        },
        "LOCATION": {
            "status": _status(bool(assets) and len(located_assets) == len(assets), bool(assets)),
            "evidence": (
                f"{len(located_assets)}/{len(assets)} equipment located; "
                f"{explicit_locations} explicit and {inferred_locations} inferred"
            ),
        },
        "FLOW_TOPOLOGY": {
            "status": _status(bool(feeds) and ambiguous_connections == 0, True),
            "evidence": f"{len(feeds)} directed feeds; {ambiguous_connections} ambiguous connections",
        },
        "POINT_LINKAGE": {
            "status": (
                "NOT_PROVIDED"
                if points_csv is None
                else _status(
                    bool(points)
                    and len(point_links) == len(points)
                    and point_spatial_contexts == len(points),
                    bool(points),
                )
            ),
            "evidence": (
                f"{len(point_links)}/{len(points)} BMS points linked; "
                f"{point_spatial_contexts}/{len(points)} have spatial context via equipment"
            ),
        },
    }
    audit = {
        "inputs": {
            "mep_ifc": [str(path.resolve()) for path in mep_paths],
            "arc_ifc": [str(path.resolve()) for path in arc_paths],
            "points_csv": str(Path(points_csv).resolve()) if points_csv is not None else None,
        },
        "schemas": {
            "mep": [bundle.schema for bundle in mep_bundles],
            "arc": [bundle.schema for bundle in arc_bundles],
        },
        "counts": {
            "mep_models": len(mep_bundles),
            "arc_models": len(arc_bundles),
            "equipment": len(assets),
            "bdns_classified_equipment": classified_count,
            "arc_spatial_elements": len(arc_guids),
            "explicit_locations": explicit_locations,
            "inferred_locations": inferred_locations,
            "directed_feeds": len(feeds),
            "bms_points": len(points),
            "point_links": len(point_links),
            "point_spatial_contexts": point_spatial_contexts,
        },
        "conflicts": {
            "duplicate_equipment_global_ids": duplicate_asset_guids,
            "duplicate_arc_spatial_global_ids": duplicate_arc_guids,
            "ambiguous_bdns_assignment_count": sum(
                extraction.audit["bdns"].get("ambiguous_asset_count", 0)
                for extraction in mep_extractions
            ),
        },
        "geometry_fallback": {
            "enabled": geometry_fallback,
            **geometry_diagnostics,
        },
        "per_mep_model": [extraction.audit for extraction in mep_extractions],
        "capabilities": capabilities,
    }

    output_dir = Path(output_dir)
    paths = write_outputs(graph, equipment, relations, point_links, output_dir)
    validation = build_validation_report(graph, equipment, relations, point_links, unresolved_points)
    input_conflicts = {
        "duplicate_equipment_global_ids": duplicate_asset_guids,
        "duplicate_arc_spatial_global_ids": duplicate_arc_guids,
        "ambiguous_bdns_assignment_count": sum(
            extraction.audit["bdns"].get("ambiguous_asset_count", 0)
            for extraction in mep_extractions
        ),
    }
    validation["input_conflicts"] = input_conflicts
    if duplicate_asset_guids or duplicate_arc_guids or input_conflicts["ambiguous_bdns_assignment_count"]:
        validation["conforms"] = False
    paths["requirement_report"] = write_json(audit, output_dir / "requirement_report.json")
    paths["validation_report"] = write_json(validation, output_dir / "validation_report.json")
    validation_summary = {
        "conforms": validation["conforms"],
        "triple_count": validation["triple_count"],
        "review_required_mapping_count": len(validation["review_required_mappings"]),
        "review_required_relation_count": len(validation["review_required_relations"]),
        "review_required_point_link_count": len(validation["review_required_point_links"]),
        "unresolved_point_count": len(validation["unresolved_points"]),
        "input_conflict_count": (
            len(duplicate_asset_guids)
            + len(duplicate_arc_guids)
            + input_conflicts["ambiguous_bdns_assignment_count"]
        ),
    }
    return {
        "mep_ifc_count": len(mep_bundles),
        "arc_ifc_count": len(arc_bundles),
        "equipment_count": len(equipment),
        "bdns_classified_equipment_count": classified_count,
        "point_count": len(points),
        "relation_count": len(relations) + len(point_links),
        "outputs": paths,
        "capabilities": capabilities,
        "validation": validation_summary,
    }
