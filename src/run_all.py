"""Run all stages: 1 IFC -> RDF, 2 points -> RDF, 3 match/validate, 4 GraphDB.

Each stage writes to its own sub-folder of --out so it can be reviewed alone:
1_ifc/, 2_points/, 3_match/, 4_graphdb/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_graphdb
import run_points
from app.pipeline import DEFAULT_BASE_NS, run_pipeline
from bms_points import run_points_stage
from graphdb import run_graphdb_stage, run_local_view
from match import run_match_stage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES = PROJECT_ROOT / "data" / "resources"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mep-ifc", required=True, nargs="+")
    parser.add_argument("--arc-ifc", required=True, nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-ns", default=DEFAULT_BASE_NS)
    parser.add_argument("--mapping-csv", default=str(RESOURCES / "BDNS mapping partial.csv"))
    parser.add_argument("--topology-roles-csv", default=str(RESOURCES / "topology_roles.csv"))
    parser.add_argument("--skip-graphdb", action="store_true")
    parser.add_argument("--skip-space-inference", action="store_true")
    run_points.add_arguments(parser)
    run_graphdb.add_arguments(parser)
    args = parser.parse_args()
    out = Path(args.out)

    summary = {}
    ifc = run_pipeline(
        mep_ifc_paths=args.mep_ifc,
        arc_ifc_paths=args.arc_ifc,
        output_dir=out / "1_ifc",
        mapping_csv_path=args.mapping_csv,
        base_ns=args.base_ns,
        topology_roles_path=args.topology_roles_csv,
        infer_spaces=not args.skip_space_inference,
    )
    summary["1_ifc"] = {"equipment": ifc["equipment_count"], "validation": ifc["validation"],
                        "flow_topology": ifc["capabilities"]["FLOW_TOPOLOGY"],
                        "location": ifc["capabilities"]["LOCATION"]}
    points = run_points_stage(args.points_csv, args.point_classes, out / "2_points", args.base_ns)
    summary["2_points"] = {k: points[k] for k in ("points", "classification", "issue_count", "triple_count")}
    match = run_match_stage(out / "1_ifc" / "building_brick.ttl", out / "2_points" / "points_brick.ttl",
                            out / "3_match", args.base_ns)
    summary["3_match"] = {k: match[k] for k in ("points", "linked", "by_reference", "review_required", "conforms", "complete")}
    if args.local_view:
        summary["4_graphdb"] = run_local_view(out / "3_match" / "linked_brick.ttl", out / "4_graphdb")
    elif not args.skip_graphdb:
        graph = run_graphdb_stage(out / "3_match" / "linked_brick.ttl", out / "4_graphdb", args.repository,
                                  args.graphdb_url, args.graphdb_home, args.focus_iri)
        summary["4_graphdb"] = {k: graph[k] for k in ("repository", "counts", "view", "workbench_visual_graph")}
    (out / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
