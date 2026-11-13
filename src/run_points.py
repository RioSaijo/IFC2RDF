"""Stage 2 CLI: BMS point list CSV -> points_brick.ttl."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline import DEFAULT_BASE_NS
from bms_points import run_points_stage

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--points-csv", required=True, help="BACnet-style point list CSV")
    parser.add_argument(
        "--point-classes",
        default=str(PROJECT_ROOT / "data" / "resources" / "brick_classes.json"),
        help="Verified Brick point classes (sensor_classes / setpoint_classes)",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-ns", default=DEFAULT_BASE_NS)
    args = parser.parse_args()
    print(json.dumps(run_points_stage(args.points_csv, args.point_classes, args.out, args.base_ns),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
