"""Stage 4: load the linked RDF into a local GraphDB and export a graph view.

Uses only the GraphDB REST / RDF4J HTTP API through the standard library.
The repository given by --repository is created if missing and its statements
are replaced on every load; other repositories are never touched.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Optional

REPOSITORY_CONFIG = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rep: <http://www.openrdf.org/config/repository#>.
@prefix sr: <http://www.openrdf.org/config/repository/sail#>.
@prefix sail: <http://www.openrdf.org/config/sail#>.
@prefix graphdb: <http://www.ontotext.com/config/graphdb#>.

[] a rep:Repository ;
    rep:repositoryID "{repository}" ;
    rdfs:label "{label}" ;
    rep:repositoryImpl [
        rep:repositoryType "graphdb:SailRepository" ;
        sr:sailImpl [
            sail:sailType "graphdb:Sail" ;
            graphdb:ruleset "rdfsplus-optimized" ;
            graphdb:disable-sameAs "true" ;
        ]
    ].
"""


class GraphDB:
    def __init__(self, url: str = "http://localhost:7200"):
        self.url = url.rstrip("/")

    def _request(self, method: str, path: str, data: bytes | None = None,
                 headers: Optional[Dict[str, str]] = None, timeout: float = 600) -> bytes:
        request = urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()[:500]
            raise RuntimeError(f"GraphDB {method} {path[:120]} failed with HTTP {exc.code}: {detail}") from exc

    def is_running(self) -> bool:
        try:
            self._request("GET", "/rest/repositories", timeout=3)
            return True
        except (urllib.error.URLError, OSError):
            return False

    def start(self, home: str | Path, log_path: str | Path, wait_seconds: int = 180) -> None:
        """Start GraphDB from its distribution folder and wait until it answers."""
        home = Path(home)
        log = open(log_path, "ab")
        if os.name == "nt":
            # graphdb.cmd needs a console; DETACHED_PROCESS makes it exit silently.
            command = ["cmd", "/c", str(home / "bin" / "graphdb.cmd")]
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            command = [str(home / "bin" / "graphdb")]
            flags = 0
        subprocess.Popen(command, cwd=str(home), stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=flags)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.is_running():
                return
            time.sleep(2)
        raise TimeoutError(f"GraphDB did not answer at {self.url} within {wait_seconds}s; see {log_path}")

    def repositories(self) -> List[str]:
        data = json.loads(self._request("GET", "/rest/repositories", headers={"Accept": "application/json"}))
        return [item["id"] for item in data]

    def ensure_repository(self, repository: str, label: str) -> bool:
        """Create the repository if missing. Returns True when it was created."""
        if repository in self.repositories():
            return False
        boundary = uuid.uuid4().hex
        config = REPOSITORY_CONFIG.format(repository=repository, label=label).encode("utf-8")
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="config"; filename="config.ttl"\r\n'
            "Content-Type: text/turtle\r\n\r\n"
        ).encode("utf-8") + config + f"\r\n--{boundary}--\r\n".encode("utf-8")
        self._request("POST", "/rest/repositories", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return True

    def replace_statements(self, repository: str, ttl_path: str | Path) -> None:
        path = f"/repositories/{urllib.parse.quote(repository)}/statements"
        self._request("DELETE", path)
        self._request("POST", path, Path(ttl_path).read_bytes(), {"Content-Type": "text/turtle"})

    def select(self, repository: str, query: str) -> List[Dict[str, str]]:
        # POST keeps long queries (e.g. VALUES lists of IRIs) out of the request line.
        data = json.loads(self._request(
            "POST",
            f"/repositories/{urllib.parse.quote(repository)}",
            urllib.parse.urlencode({"query": query}).encode("utf-8"),
            {"Accept": "application/sparql-results+json", "Content-Type": "application/x-www-form-urlencoded"},
        ))
        return [{k: v["value"] for k, v in row.items()} for row in data["results"]["bindings"]]


class LocalGraph:
    """Answers the same SELECT queries from a local RDF file with rdflib.

    Used to export the graph view when GraphDB cannot load the data.
    """

    def __init__(self, ttl_path: str | Path):
        from rdflib import Graph

        self.graph = Graph().parse(str(ttl_path), format="turtle")

    def select(self, _repository: str, query: str) -> List[Dict[str, str]]:
        return [
            {str(k): str(v) for k, v in row.asdict().items() if v is not None}
            for row in self.graph.query(query)
        ]


PREFIXES = """PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bot: <https://w3id.org/bot#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

COUNT_QUERY = PREFIXES + """
SELECT ?metric (COUNT(*) AS ?n) WHERE {
  { ?s brick:feeds ?o . BIND("feeds" AS ?metric) }
  UNION { ?s brick:hasPoint ?o . BIND("hasPoint" AS ?metric) }
  UNION { ?s brick:hasLocation ?o . BIND("hasLocation" AS ?metric) }
  UNION { ?s brick:hasPart ?o . BIND("hasPart" AS ?metric) }
} GROUP BY ?metric ORDER BY ?metric
"""

# Equipment on feeds paths with their points and locations, plus spaces with points.
VIEW_EDGES_QUERY = PREFIXES + """
SELECT DISTINCT ?s ?p ?o WHERE {
  { ?s brick:feeds ?o . BIND("feeds" AS ?p) }
  UNION { ?s brick:feeds|^brick:feeds [] . ?s brick:hasPoint ?o . BIND("hasPoint" AS ?p) }
  UNION { ?s brick:feeds|^brick:feeds [] . ?s brick:hasLocation ?o . BIND("hasLocation" AS ?p) }
  UNION { ?s a bot:Space ; brick:hasPoint ?o . BIND("hasPoint" AS ?p) }
}
"""

VIEW_NODES_QUERY = PREFIXES + """
SELECT ?n (SAMPLE(?l) AS ?label) (GROUP_CONCAT(DISTINCT STRAFTER(STR(?t), "#"); separator=", ") AS ?types) WHERE {
  VALUES ?n { %s }
  OPTIONAL { ?n rdfs:label ?l }
  OPTIONAL { ?n a ?t FILTER(STRSTARTS(STR(?t), "https://brickschema.org/") || STRSTARTS(STR(?t), "https://w3id.org/bot#")) }
} GROUP BY ?n
"""

VIEW_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Brick graph view</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>body{margin:0;font-family:sans-serif}#info{padding:8px 12px;font-size:13px;border-bottom:1px solid #ccc}
#graph{height:calc(100vh - 40px)}</style></head>
<body><div id="info">__INFO__</div><div id="graph"></div>
<script>
const data = __DATA__;
const colors = {equipment:"#4C78A8", point:"#F58518", space:"#54A24B", storey:"#B279A2", other:"#9D9D9D"};
const nodes = new vis.DataSet(data.nodes.map(n => ({id:n.id, label:n.label, title:n.types + "\\n" + n.id,
  color:colors[n.group] || colors.other, shape: n.group === "point" ? "dot" : "box", size: 8})));
const edges = new vis.DataSet(data.edges.map(e => ({from:e.s, to:e.o, label:e.p, arrows:"to",
  color: e.p === "feeds" ? "#D62728" : "#888", width: e.p === "feeds" ? 3 : 1, font:{size:9}})));
new vis.Network(document.getElementById("graph"), {nodes, edges},
  {physics:{solver:"forceAtlas2Based", stabilization:{iterations:300}}, edges:{smooth:false}});
</script></body></html>
"""


def _group(types: str) -> str:
    if "Space" in types.split(", "):
        return "space"
    if "Storey" in types.split(", "):
        return "storey"
    if any(t.endswith(("_Sensor", "_Status", "_Setpoint")) or t == "Point" for t in types.split(", ")):
        return "point"
    return "equipment" if types else "other"


def export_view(db: GraphDB | LocalGraph, repository: str, html_path: str | Path) -> Dict[str, int]:
    edges = db.select(repository, VIEW_EDGES_QUERY)
    iris = sorted({e["s"] for e in edges} | {e["o"] for e in edges})
    nodes: List[Dict[str, str]] = []
    for start in range(0, len(iris), 200):
        values = " ".join(f"<{iri}>" for iri in iris[start:start + 200])
        nodes.extend(db.select(repository, VIEW_NODES_QUERY % values))
    data = {
        "nodes": [
            {"id": n["n"], "label": n.get("label") or n["n"].rsplit("#", 1)[-1],
             "types": n.get("types", ""), "group": _group(n.get("types", ""))}
            for n in nodes
        ],
        "edges": edges,
    }
    source = f"GraphDB repository <b>{repository}</b>" if isinstance(db, GraphDB) else f"local file <b>{repository}</b>"
    info = (f"{source}: {len(data['nodes'])} nodes, {len(edges)} edges "
            "(equipment on feeds paths with points and locations; spaces with points)")
    html = VIEW_HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__INFO__", info)
    Path(html_path).write_text(html, encoding="utf-8")
    return {"nodes": len(data["nodes"]), "edges": len(edges)}


def run_local_view(ttl_path: str | Path, output_dir: str | Path) -> Dict[str, object]:
    """Export graph_view.html from the RDF file without GraphDB."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    view = export_view(LocalGraph(ttl_path), Path(ttl_path).name, output / "graph_view.html")
    return {"source": str(Path(ttl_path).resolve()), "view": view, "outputs": {"html": str(output / "graph_view.html")}}


def run_graphdb_stage(
    ttl_path: str | Path,
    output_dir: str | Path,
    repository: str,
    url: str = "http://localhost:7200",
    graphdb_home: str | Path | None = None,
    focus_iri: str | None = None,
) -> Dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    db = GraphDB(url)
    started = False
    if not db.is_running():
        if graphdb_home is None:
            raise RuntimeError(f"GraphDB is not running at {url}; pass --graphdb-home to start it")
        db.start(graphdb_home, output / "graphdb_server.log")
        started = True
    created = db.ensure_repository(repository, "IFC2RDF case study (Brick)")
    db.replace_statements(repository, ttl_path)
    counts = {row["metric"]: int(row["n"]) for row in db.select(repository, COUNT_QUERY)}
    view = export_view(db, repository, output / "graph_view.html")
    workbench = f"{db.url}/graphs-visualizations?repositoryId={urllib.parse.quote(repository)}"
    if focus_iri:
        workbench += f"&uri={urllib.parse.quote(focus_iri, safe='')}"
    report = {
        "graphdb_url": db.url,
        "started_graphdb": started,
        "repository": repository,
        "repository_created": created,
        "loaded_ttl": str(Path(ttl_path).resolve()),
        "counts": counts,
        "view": view,
        "outputs": {"html": str(output / "graph_view.html")},
        "workbench_visual_graph": workbench,
    }
    (output / "graphdb_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
