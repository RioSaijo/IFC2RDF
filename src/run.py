from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline import DEFAULT_BASE_NS, run_pipeline


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Convert MEP IFC equipment and ARC IFC spaces to Brick RDF."
    )
    parser.add_argument(
        "--mep-ifc",
        required=True,
        nargs="+",
        help="One or more MEP IFC files containing equipment and BDNS classifications",
    )
    parser.add_argument(
        "--arc-ifc",
        required=True,
        nargs="+",
        help="One or more architectural IFC files containing the spatial hierarchy",
    )
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--base-ns", default=DEFAULT_BASE_NS)
    parser.add_argument(
        "--mapping-csv",
        default=str(project_root / "data" / "resources" / "BDNS mapping partial.csv"),
        help="Project BDNS-to-Brick crosswalk",
    )
    parser.add_argument(
        "--topology-roles-csv",
        default=str(project_root / "data" / "resources" / "topology_roles.csv"),
        help="BDNS tags traversed as path evidence instead of being brick:feeds nodes",
    )
    parser.add_argument(
        "--skip-space-inference",
        action="store_true",
        help="Do not place equipment in ARC spaces from geometry (see src/spaces.py)",
    )
    args = parser.parse_args()
    result = run_pipeline(
        mep_ifc_paths=args.mep_ifc,
        arc_ifc_paths=args.arc_ifc,
        output_dir=args.out,
        mapping_csv_path=args.mapping_csv,
        base_ns=args.base_ns,
        infer_spaces=not args.skip_space_inference,
        topology_roles_path=args.topology_roles_csv,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
