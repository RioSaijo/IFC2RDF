"""Stage 3 CLI: match points_brick.ttl against the IFC building_brick.ttl."""
from __future__ import annotations

import argparse
import json

from app.pipeline import DEFAULT_BASE_NS
from match import run_match_stage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ifc-ttl", required=True, help="Stage 1 output building_brick.ttl")
    parser.add_argument("--points-ttl", required=True, help="Stage 2 output points_brick.ttl")
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-ns", default=DEFAULT_BASE_NS)
    args = parser.parse_args()
    print(json.dumps(run_match_stage(args.ifc_ttl, args.points_ttl, args.out, args.base_ns),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
