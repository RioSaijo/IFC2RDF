from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from ifc import (
    extract_ifc,
    extract_spatial_elements,
    load_ifc,
    write_connection_inferences,
)
import csv
from collections import Counter

from mapping import is_bdns_instance_id, map_assets, write_mapping_results
from models import IfcAsset, Relation, SpatialElement
from rdf import build_graph, write_outputs
from spaces import infer_space_locations, write_space_locations
from topology import infer_feed_paths, load_passthrough_codes, write_topology_paths
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
            elif relation.predicate == "brick:feeds":
                # Feeds come from path inference over the whole port graph,
                # which needs the mapping result; see infer_feed_paths.
                continue
            seen.add(key)
            relations.append(relation)
    return relations


def _status(complete: bool, available: bool = True) -> str:
    if complete:
        return "PASS"
    return "WARN" if available else "FAIL"


def _write_bdns_tag_issues(non_instance_tags, duplicate_instance_ids, assets, path: Path) -> str:
    """Elements left out or in conflict because of their BDNS tag."""
    path.parent.mkdir(parents=True, exist_ok=True)
    duplicates = set(duplicate_instance_ids)
    rows = [
        (item, "BDNS tag is not an asset instance ID (abbreviation-number); element left out")
        for item in non_instance_tags
    ] + [(item, "BDNS instance ID is used by more than one element") for item in assets if item.bdns_code in duplicates]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ifc_guid", "ifc_name", "raw_ifc_class", "bdns_tag", "issue", "source_path"])
        for item, issue in rows:
            writer.writerow([item.ifc_guid, item.name or "", item.raw_ifc_class, item.bdns_code, issue, item.source_path or ""])
    return str(path)


def run_pipeline(
    mep_ifc_paths: str | Path | Sequence[str | Path],
    arc_ifc_paths: str | Path | Sequence[str | Path],
    output_dir: str | Path,
    mapping_csv_path: str | Path,
    base_ns: str = DEFAULT_BASE_NS,
    infer_spaces: bool = False,
    topology_roles_path: str | Path | None = None,
) -> Dict[str, Any]:
    if not base_ns.startswith(("http://", "https://")) or not base_ns.endswith(("#", "/")):
        raise ValueError("base_ns must be an HTTP(S) namespace ending in '#' or '/'")

    mep_paths = _paths(mep_ifc_paths, "MEP")
    arc_paths = _paths(arc_ifc_paths, "ARC")
    mep_bundles = [load_ifc(path) for path in mep_paths]
    arc_bundles = [load_ifc(path) for path in arc_paths]
    mep_extractions = [extract_ifc(bundle) for bundle in mep_bundles]
    arc_spatial_groups = [extract_spatial_elements(bundle) for bundle in arc_bundles]

    all_distribution_assets, duplicate_asset_guids = _merge_assets(mep_extractions)
    # Only elements whose BDNS tag is an asset instance ID (e.g. AHU-00001) are converted.
    # Elements tagged with an abbreviation only (e.g. AHU) are reported and left out.
    bdns_tagged = [item for item in all_distribution_assets if item.bdns_code]
    assets = [item for item in bdns_tagged if is_bdns_instance_id(item.bdns_code)]
    non_instance_tags = [item for item in bdns_tagged if not is_bdns_instance_id(item.bdns_code)]
    instance_id_counts = Counter(item.bdns_code for item in assets)
    duplicate_instance_ids = sorted(code for code, count in instance_id_counts.items() if count > 1)
    spatial, duplicate_arc_guids, arc_guids = _merge_spatial(mep_extractions, arc_spatial_groups)
    asset_guids = {item.ifc_guid for item in assets}
    connection_inferences = [
        item
        for extraction in mep_extractions
        for item in extraction.connection_inferences
        if item.relating_equipment_guid in asset_guids
        and item.related_equipment_guid in asset_guids
    ]
    spatial_guids = {item.ifc_guid for item in spatial}
    relations = _merge_relations(
        mep_extractions,
        asset_guids=asset_guids,
        spatial_guids=spatial_guids,
        arc_guids=arc_guids,
    )

    space_decisions = []
    space_diagnostics: Dict[str, Any] = {"enabled": infer_spaces}
    if infer_spaces:
        space_relations, space_decisions, diagnostics = infer_space_locations(
            mep_bundles, arc_bundles, assets, relations
        )
        space_diagnostics.update(diagnostics)
        relations.extend(space_relations)

    equipment = map_assets(assets, mapping_csv_path)
    topology_paths, feed_relations, topology_stats = infer_feed_paths(
        [item for extraction in mep_extractions for item in extraction.port_connections],
        equipment,
        load_passthrough_codes(topology_roles_path),
    )
    relations.extend(feed_relations)

    graph = build_graph(
        spatial=spatial,
        equipment=equipment,
        relations=relations,
        base_ns=base_ns,
    )

    classified_count = len(assets)
    located_assets = {
        item.subject_guid for item in relations if item.predicate == "brick:hasLocation"
    }
    space_guids = {item.ifc_guid for item in spatial if item.raw_ifc_class == "IfcSpace"}
    located_in_space = {
        item.subject_guid
        for item in relations
        if item.predicate == "brick:hasLocation" and item.object_guid in space_guids
    }
    explicit_locations = sum(
        item.predicate == "brick:hasLocation" and item.method == "explicit"
        for item in relations
    )
    inferred_locations = sum(
        item.predicate == "brick:hasLocation" and item.method != "explicit"
        for item in relations
    )
    feeds = [item for item in relations if item.predicate == "brick:feeds"]
    mapped_equipment_guids = {
        item.ifc_guid for item in equipment if item.brick_class is not None
    }
    rdf_feeds = [
        item
        for item in feeds
        if item.subject_guid in mapped_equipment_guids
        and item.object_guid in mapped_equipment_guids
    ]
    ambiguous_connections = sum(
        item.decision_status == "ambiguous" for item in connection_inferences
    )
    hierarchy_links = sum(
        item.parent_guid in arc_guids
        for item in spatial
        if item.ifc_guid in arc_guids
    )
    ambiguous_bdns_count = sum(
        extraction.audit["bdns"].get("ambiguous_asset_count", 0)
        for extraction in mep_extractions
    )
    capabilities = {
        "IDENTITY": {
            "status": _status(
                bool(assets) and not duplicate_asset_guids and not duplicate_instance_ids and not non_instance_tags,
                bool(assets),
            ),
            "evidence": (
                f"{len(assets)} equipment with a BDNS instance ID selected from "
                f"{len(all_distribution_assets)} distribution elements; "
                f"{len(non_instance_tags)} BDNS tags without an instance ID left out; "
                f"{len(duplicate_instance_ids)} duplicate BDNS instance IDs; "
                f"{len(duplicate_asset_guids)} duplicate GlobalIds"
            ),
        },
        "CLASSIFICATION": {
            "status": _status(bool(assets) and ambiguous_bdns_count == 0, bool(assets)),
            "evidence": (
                f"{classified_count} equipment selected by explicit BDNS association; "
                f"{ambiguous_bdns_count} ambiguous assignments"
            ),
        },
        "SPATIAL_HIERARCHY": {
            "status": _status(bool(arc_guids) and hierarchy_links > 0, bool(arc_guids)),
            "evidence": f"{len(arc_guids)} ARC spatial elements; {hierarchy_links} hierarchy links",
        },
        "LOCATION": {
            "status": _status(bool(assets) and len(located_assets) == len(assets), bool(assets)),
            "evidence": (
                f"{len(located_assets)}/{len(assets)} equipment located; "
                f"{explicit_locations} explicit and {inferred_locations} inferred; "
                f"{len(located_in_space)} in a space"
            ),
        },
        "FLOW_TOPOLOGY": {
            "status": _status(
                bool(rdf_feeds)
                and ambiguous_connections == 0
                and not topology_stats["review_required_feeds"]
                and not topology_stats["role_conflicts"]
                and not topology_stats["direction_conflicts"],
                True,
            ),
            "evidence": (
                f"{topology_stats['inferred_feeds']} inferred feeds "
                f"({topology_stats['review_required_feeds']} review-required); "
                f"{topology_stats['role_conflicts']} role conflicts; "
                f"{topology_stats['direction_conflicts']} direction conflicts; "
                f"{ambiguous_connections} undirected connections between BDNS equipment"
            ),
        },
    }
    audit = {
        "inputs": {
            "mep_ifc": [str(path.resolve()) for path in mep_paths],
            "arc_ifc": [str(path.resolve()) for path in arc_paths],
        },
        "schemas": {
            "mep": [bundle.schema for bundle in mep_bundles],
            "arc": [bundle.schema for bundle in arc_bundles],
        },
        "counts": {
            "mep_models": len(mep_bundles),
            "arc_models": len(arc_bundles),
            "ifc_distribution_elements": len(all_distribution_assets),
            "equipment": len(assets),
            "bdns_classified_equipment": classified_count,
            "bdns_tags_without_instance_id": len(non_instance_tags),
            "arc_spatial_elements": len(arc_guids),
            "explicit_locations": explicit_locations,
            "inferred_locations": inferred_locations,
            "located_in_space": len(located_in_space),
            "directed_feeds": len(feeds),
            "rdf_eligible_directed_feeds": len(rdf_feeds),
            "topology": topology_stats,
        },
        "conflicts": {
            "duplicate_equipment_global_ids": duplicate_asset_guids,
            "duplicate_bdns_instance_ids": duplicate_instance_ids,
            "duplicate_arc_spatial_global_ids": duplicate_arc_guids,
            "ambiguous_bdns_assignment_count": sum(
                extraction.audit["bdns"].get("ambiguous_asset_count", 0)
                for extraction in mep_extractions
            ),
        },
        "space_inference": space_diagnostics,
        "per_mep_model": [extraction.audit for extraction in mep_extractions],
        "capabilities": capabilities,
    }

    output_dir = Path(output_dir)
    paths = write_outputs(graph, equipment, relations, output_dir)
    if infer_spaces:
        paths["space_locations"] = write_space_locations(space_decisions, output_dir / "space_locations.csv")
    paths["equipment_mapping"] = write_mapping_results(
        equipment,
        output_dir / "equipment_mapping.csv",
    )
    paths["connection_inference"] = write_connection_inferences(
        connection_inferences,
        output_dir / "connection_inference.csv",
    )
    paths["bdns_tag_issues"] = _write_bdns_tag_issues(
        non_instance_tags, duplicate_instance_ids, assets, output_dir / "bdns_tag_issues.csv"
    )
    paths["topology_paths"] = write_topology_paths(
        topology_paths,
        output_dir / "topology_paths.csv",
    )
    validation = build_validation_report(graph, equipment, relations)
    input_conflicts = {
        "duplicate_equipment_global_ids": duplicate_asset_guids,
        "duplicate_bdns_instance_ids": duplicate_instance_ids,
        "duplicate_arc_spatial_global_ids": duplicate_arc_guids,
        "ambiguous_bdns_assignment_count": ambiguous_bdns_count,
    }
    validation["input_conflicts"] = input_conflicts
    if (duplicate_asset_guids or duplicate_instance_ids or duplicate_arc_guids
            or input_conflicts["ambiguous_bdns_assignment_count"]):
        validation["conforms"] = False
    paths["requirement_report"] = write_json(audit, output_dir / "requirement_report.json")
    paths["validation_report"] = write_json(validation, output_dir / "validation_report.json")
    validation_summary = {
        "conforms": validation["conforms"],
        "triple_count": validation["triple_count"],
        "review_required_mapping_count": len(validation["review_required_mappings"]),
        "review_required_relation_count": len(validation["review_required_relations"]),
        "input_conflict_count": (
            len(duplicate_asset_guids)
            + len(duplicate_instance_ids)
            + len(duplicate_arc_guids)
            + input_conflicts["ambiguous_bdns_assignment_count"]
        ),
    }
    return {
        "mep_ifc_count": len(mep_bundles),
        "arc_ifc_count": len(arc_bundles),
        "equipment_count": len(equipment),
        "bdns_classified_equipment_count": classified_count,
        "relation_count": len(relations),
        "outputs": paths,
        "capabilities": capabilities,
        "validation": validation_summary,
    }
