from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ifc import extract_ifc, infer_geometry_locations, load_ifc
from mapping import map_assets
from points import load_and_link_points
from rdf import build_graph, write_outputs
from validation import build_validation_report, write_json


DEFAULT_BASE_NS = "https://example.org/building#"


def run_pipeline(
    ifc_path: str | Path,
    output_dir: str | Path,
    mapping_csv_path: str | Path,
    points_csv: Optional[str | Path] = None,
    base_ns: str = DEFAULT_BASE_NS,
    geometry_fallback: bool = False,
) -> Dict[str, Any]:
    if not base_ns.startswith(("http://", "https://")) or not base_ns.endswith(("#", "/")):
        raise ValueError("base_ns must be an HTTP(S) namespace ending in '#' or '/'")

    output_dir = Path(output_dir)
    bundle = load_ifc(ifc_path)
    extraction = extract_ifc(bundle)
    if geometry_fallback:
        inferred = infer_geometry_locations(bundle, extraction)
        extraction.relations.extend(inferred)
        extraction.audit["counts"]["geometry_inferred_locations"] = len(inferred)
        extraction.audit["capabilities"]["GEOMETRY_FALLBACK"] = {
            "status": "WARN" if inferred else "NOT_USED",
            "evidence": f"{len(inferred)} review-required AABB centroid inferences",
        }

    equipment = map_assets(extraction.assets, mapping_csv_path)
    points = []
    point_links = []
    unresolved_points = []
    if points_csv is not None:
        points, point_links, unresolved_points = load_and_link_points(points_csv, equipment, base_ns)

    graph = build_graph(
        spatial=extraction.spatial,
        equipment=equipment,
        points=points,
        relations=extraction.relations,
        point_links=point_links,
        base_ns=base_ns,
    )
    paths = write_outputs(graph, equipment, extraction.relations, point_links, output_dir)
    validation = build_validation_report(graph, equipment, extraction.relations, point_links, unresolved_points)
    paths["requirement_report"] = write_json(extraction.audit, output_dir / "requirement_report.json")
    paths["validation_report"] = write_json(validation, output_dir / "validation_report.json")
    validation_summary = {
        "conforms": validation["conforms"],
        "triple_count": validation["triple_count"],
        "review_required_mapping_count": len(validation["review_required_mappings"]),
        "review_required_relation_count": len(validation["review_required_relations"]),
        "review_required_point_link_count": len(validation["review_required_point_links"]),
        "unresolved_point_count": len(validation["unresolved_points"]),
    }
    return {
        "ifc_schema": bundle.schema,
        "equipment_count": len(equipment),
        "bdns_classified_equipment_count": sum(item.bdns_code is not None for item in equipment),
        "point_count": len(points),
        "relation_count": len(extraction.relations) + len(point_links),
        "outputs": paths,
        "capabilities": extraction.audit["capabilities"],
        "validation": validation_summary,
    }
