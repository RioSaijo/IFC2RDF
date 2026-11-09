"""Graph exploration queries for the UI's GraphDB panel.

Every function takes a source with `select(repository, query)` — a GraphDB
connection or a LocalGraph over an RDF file — so the same SPARQL runs in both.
Graph results are {"nodes": [...], "edges": [...]}; table results are
{"columns": [...], "rows": [...]}.
"""
from __future__ import annotations

import re
from typing import Dict, List

from graphdb import PREFIXES, VIEW_NODES_QUERY, _group

EXCLUDED_PREDICATES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    "https://brickschema.org/schema/Brick#hasUnit",
)
IRI = re.compile(r"^https?://[^\s<>\"{}|\\^`]+$")


def _iri(value: str) -> str:
    if not IRI.match(value or ""):
        raise ValueError(f"not an IRI: {value!r}")
    return f"<{value}>"


def _literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _local(iri: str) -> str:
    return re.split(r"[#/]", iri)[-1]


def _project(base_ns: str) -> str:
    return f"PREFIX project: {_iri(base_ns)}\n"


def _graph(source, repository: str, edges: List[Dict[str, str]]) -> Dict[str, list]:
    iris = sorted({e["s"] for e in edges} | {e["o"] for e in edges})
    info = []
    for start in range(0, len(iris), 200):
        values = " ".join(f"<{iri}>" for iri in iris[start:start + 200])
        info.extend(source.select(repository, VIEW_NODES_QUERY % values))
    nodes = [
        {"id": n["n"], "label": n.get("label") or _local(n["n"]), "types": n.get("types", ""),
         "group": _group(n.get("types", ""))}
        for n in info
    ]
    return {"nodes": nodes, "edges": [{"s": e["s"], "p": _local(e["p"]), "o": e["o"]} for e in edges]}


def search(source, repository: str, base_ns: str, text: str, limit: int = 30) -> Dict[str, list]:
    """Equipment, spaces and points whose IFC Name, point ID or label contains the text."""
    query = PREFIXES + _project(base_ns) + f"""
SELECT DISTINCT ?n ?name ?kind WHERE {{
  {{ ?n project:ifcName ?name . BIND("ifcName" AS ?kind) }}
  UNION {{ ?n project:pointId ?name . BIND("pointId" AS ?kind) }}
  FILTER(CONTAINS(LCASE(STR(?name)), LCASE({_literal(text)})))
}} ORDER BY ?name LIMIT {int(limit)}
"""
    rows = source.select(repository, query)
    return {"columns": ["name", "kind", "n"], "rows": rows}


def neighbors(source, repository: str, iri: str, limit: int = 200) -> Dict[str, list]:
    """Every IRI linked to or from the node, except rdf:type and units."""
    node = _iri(iri)
    excluded = ", ".join(f"<{p}>" for p in EXCLUDED_PREDICATES)
    query = PREFIXES + f"""
SELECT ?s ?p ?o WHERE {{
  {{ {node} ?p ?o . BIND({node} AS ?s) FILTER(isIRI(?o)) }}
  UNION {{ ?s ?p {node} . BIND({node} AS ?o) }}
  FILTER(?p NOT IN ({excluded}))
}} LIMIT {int(limit)}
"""
    graph = _graph(source, repository, source.select(repository, query))
    if not graph["nodes"]:
        graph["nodes"] = _graph(source, repository, [{"s": iri, "p": "self", "o": iri}])["nodes"]
    return graph


def feeds_paths(source, repository: str, iri: str) -> Dict[str, list]:
    """All brick:feeds edges upstream and downstream of the equipment."""
    node = _iri(iri)
    query = PREFIXES + f"""
SELECT DISTINCT ?s ?p ?o WHERE {{
  {{ {node} brick:feeds* ?s . ?s brick:feeds ?o }}
  UNION {{ ?o brick:feeds* {node} . ?s brick:feeds ?o }}
  BIND(brick:feeds AS ?p)
}}
"""
    return _graph(source, repository, source.select(repository, query))


def unlinked_points(source, repository: str, base_ns: str) -> Dict[str, list]:
    """Points that no equipment or space links to with brick:hasPoint."""
    query = PREFIXES + _project(base_ns) + """
SELECT ?pointId ?equipmentRef ?spaceRef WHERE {
  ?p project:pointId ?pointId .
  FILTER NOT EXISTS { ?x brick:hasPoint ?p }
  OPTIONAL { ?p project:equipmentRef ?equipmentRef }
  OPTIONAL { ?p project:spaceRef ?spaceRef }
} ORDER BY ?pointId
"""
    return {"columns": ["pointId", "equipmentRef", "spaceRef"], "rows": source.select(repository, query)}


def unclassified_points(source, repository: str, base_ns: str) -> Dict[str, list]:
    """Sensor/Setpoint points whose Brick class could not be assigned."""
    query = PREFIXES + _project(base_ns) + """
SELECT ?pointId ?reason WHERE {
  ?p project:pointId ?pointId ; project:classificationStatus "unclassified" .
  OPTIONAL { ?p project:classificationReason ?reason }
} ORDER BY ?pointId
"""
    return {"columns": ["pointId", "reason"], "rows": source.select(repository, query)}


def feeds_table(source, repository: str, base_ns: str) -> Dict[str, list]:
    """Every brick:feeds relation with equipment names."""
    query = PREFIXES + _project(base_ns) + """
SELECT ?from ?to WHERE {
  ?s brick:feeds ?o .
  OPTIONAL { ?s project:ifcName ?from } OPTIONAL { ?o project:ifcName ?to }
} ORDER BY ?from ?to
"""
    return {"columns": ["from", "to"], "rows": source.select(repository, query)}


PRESET_TABLES = {
    "unlinked_points": unlinked_points,
    "unclassified_points": unclassified_points,
    "feeds_table": feeds_table,
}
