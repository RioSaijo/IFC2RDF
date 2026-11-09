"""Stage 4 CLI: load linked_brick.ttl into GraphDB and export graph_view.html."""
from __future__ import annotations

import argparse
import json

from graphdb import run_graphdb_stage, run_local_view


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--local-view", action="store_true",
                        help="Skip GraphDB and export graph_view.html from the RDF file with rdflib")
    parser.add_argument("--graphdb-url", default="http://localhost:7200")
    parser.add_argument("--graphdb-home", help="GraphDB distribution folder; used to start GraphDB if it is not running")
    parser.add_argument("--repository", default="IFC2RDF_case_study")
    parser.add_argument("--focus-iri", help="IRI to open in the Workbench visual graph")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ttl", required=True, help="Stage 3 output linked_brick.ttl")
    parser.add_argument("--out", required=True)
    add_arguments(parser)
    args = parser.parse_args()
    if args.local_view:
        report = run_local_view(args.ttl, args.out)
    else:
        report = run_graphdb_stage(args.ttl, args.out, args.repository, args.graphdb_url,
                                   args.graphdb_home, args.focus_iri)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
