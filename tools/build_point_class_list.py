"""Build data/resources/brick_classes.json from an official Brick release file.

The list holds every non-deprecated Brick class that is brick:Sensor or
brick:Setpoint or one of their subclasses. Deprecated classes are left out so
the point classifier never assigns them; a point whose name only matches a
deprecated class falls back to the broader non-deprecated class.

Usage:
    python tools/build_point_class_list.py Brick.ttl data/resources/brick_classes.json

Brick.ttl is the release file, for example
https://github.com/BrickSchema/Brick/releases/download/v1.4.4/Brick.ttl
"""
import argparse
import json
from pathlib import Path

from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS, URIRef

BRICK = Namespace("https://brickschema.org/schema/Brick#")


def _is_deprecated(graph: Graph, term: URIRef) -> bool:
    return (term, OWL.deprecated, Literal(True)) in graph or any(graph.objects(term, BRICK.deprecatedInVersion))


def _live_subclasses(graph: Graph, root: URIRef) -> list[str]:
    found = {root}
    stack = [root]
    while stack:
        for child in graph.subjects(RDFS.subClassOf, stack.pop()):
            if isinstance(child, URIRef) and child not in found:
                found.add(child)
                stack.append(child)
    return sorted(str(c) for c in found if str(c).startswith(str(BRICK)) and not _is_deprecated(graph, c))


def build(brick_ttl: Path) -> dict:
    graph = Graph()
    graph.parse(brick_ttl)
    ontology = next(graph.subjects(RDF.type, OWL.Ontology))
    version = str(next(graph.objects(ontology, OWL.versionInfo)))
    return {
        "source": str(ontology),
        "brick_version": version,
        "description": f"Non-deprecated Brick {version} classes that are brick:Sensor or brick:Setpoint or their subclasses.",
        "sensor_classes": _live_subclasses(graph, BRICK.Sensor),
        "setpoint_classes": _live_subclasses(graph, BRICK.Setpoint),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("brick_ttl", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    data = build(args.brick_ttl)
    args.output_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Brick {data['brick_version']}: {len(data['sensor_classes'])} sensor classes, "
          f"{len(data['setpoint_classes'])} setpoint classes -> {args.output_json}")


if __name__ == "__main__":
    main()
