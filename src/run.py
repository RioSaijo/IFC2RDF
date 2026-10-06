from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline import DEFAULT_BASE_NS, run_pipeline


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Convert BDNS-classified IFC equipment and relationships to Brick RDF.")
    parser.add_argument("--ifc", required=True, help="IFC STEP input file")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--points-csv", help="Optional BMS point CSV")
    parser.add_argument("--base-ns", default=DEFAULT_BASE_NS)
    parser.add_argument(
        "--mapping-csv",
        default=str(project_root / "data" / "resources" / "BDNS mapping partial.csv"),
        help="Project BDNS-to-Brick crosswalk",
    )
    parser.add_argument(
        "--geometry-fallback",
        action="store_true",
        help="Infer missing locations from geometry AABBs; results require review",
    )
    args = parser.parse_args()
    result = run_pipeline(
        ifc_path=args.ifc,
        output_dir=args.out,
        mapping_csv_path=args.mapping_csv,
        points_csv=args.points_csv,
        base_ns=args.base_ns,
        geometry_fallback=args.geometry_fallback,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
