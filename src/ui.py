"""Local web UI for the staged workflow (standard library only).

    python src/ui.py            # then open http://127.0.0.1:8765

The server listens on 127.0.0.1 only. Inputs are local file paths; nothing is
uploaded anywhere. Each button runs one stage in the background and shows its
summary, output files, and (stage 4) the graph view. Output files are served
only from the chosen output folder.
"""
from __future__ import annotations

import argparse
import json
import threading
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent

import explorer  # noqa: E402
from app.pipeline import DEFAULT_BASE_NS, run_pipeline  # noqa: E402
from bms_points import run_points_stage  # noqa: E402
from graphdb import GraphDB, run_graphdb_stage, run_local_view  # noqa: E402
from match import run_match_stage  # noqa: E402

RESOURCES = PROJECT_ROOT / "data" / "resources"
STAGE_DIRS = {"1": "1_ifc", "2": "2_points", "3": "3_match", "4": "4_graphdb"}

STATE = {"running": None, "log": [], "results": {}}
LOCK = threading.Lock()


def _lines(value: str) -> list[str]:
    return [line.strip().strip('"') for line in (value or "").splitlines() if line.strip()]


def _log(message: str) -> None:
    with LOCK:
        STATE["log"].append(f"{datetime.now():%H:%M:%S} {message}")


def run_stage(stage: str, p: dict) -> dict:
    out = Path(p["out"].strip().strip('"'))
    base_ns = p.get("base_ns") or DEFAULT_BASE_NS
    stage_dir = out / STAGE_DIRS[stage]
    if stage == "1":
        result = run_pipeline(
            mep_ifc_paths=_lines(p["mep"]), arc_ifc_paths=_lines(p["arc"]), output_dir=stage_dir,
            mapping_csv_path=RESOURCES / "BDNS mapping partial.csv", base_ns=base_ns,
            topology_roles_path=RESOURCES / "topology_roles.csv",
            infer_spaces=bool(p.get("infer_spaces")),
        )
        return {k: result[k] for k in ("equipment_count", "capabilities", "validation", "outputs")}
    if stage == "2":
        return run_points_stage(p["points"].strip().strip('"'), RESOURCES / "brick_classes.json", stage_dir, base_ns)
    if stage == "3":
        return run_match_stage(out / "1_ifc" / "building_brick.ttl", out / "2_points" / "points_brick.ttl",
                               stage_dir, base_ns)
    if stage == "4":
        linked = out / "3_match" / "linked_brick.ttl"
        if p.get("local_view"):
            return run_local_view(linked, stage_dir)
        return run_graphdb_stage(linked, stage_dir, p.get("repository") or "IFC2RDF_case_study",
                                 p.get("graphdb_url") or "http://localhost:7200", p.get("graphdb_home") or None)
    raise ValueError(f"unknown stage {stage}")


def _worker(stages: list[str], params: dict) -> None:
    try:
        for stage in stages:
            with LOCK:
                STATE["running"] = stage
            _log(f"stage {stage} started")
            result = run_stage(stage, params)
            with LOCK:
                STATE["results"][stage] = {"ok": True, "result": result}
            _log(f"stage {stage} finished")
    except Exception as exc:  # report any failure to the page
        with LOCK:
            STATE["results"][stage] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                       "trace": traceback.format_exc()[-3000:]}
        _log(f"stage {stage} failed: {exc}")
    finally:
        with LOCK:
            STATE["running"] = None


def _start_graphdb(url: str, home: str) -> None:
    try:
        _log("GraphDB starting")
        GraphDB(url).start(home, Path(home) / "logs" / "ifc2rdf_ui_start.log")
        _log("GraphDB is running")
    except Exception as exc:
        _log(f"GraphDB start failed: {exc}")
    finally:
        with LOCK:
            STATE["graphdb_starting"] = False


def graphdb_api(action: str, q: dict) -> dict:
    """GraphDB panel: status, and explorer queries against the selected repository."""
    db = GraphDB(q.get("url") or "http://localhost:7200")
    repository = q.get("repo") or ""
    base_ns = q.get("ns") or DEFAULT_BASE_NS
    if action == "status":
        running = db.is_running()
        return {"running": running, "starting": bool(STATE.get("graphdb_starting")),
                "repositories": db.repositories() if running else []}
    if action == "search":
        return explorer.search(db, repository, base_ns, q.get("q", ""))
    if action == "neighbors":
        return explorer.neighbors(db, repository, q.get("iri", ""))
    if action == "feeds":
        return explorer.feeds_paths(db, repository, q.get("iri", ""))
    if action == "table" and q.get("name") in explorer.PRESET_TABLES:
        return explorer.PRESET_TABLES[q["name"]](db, repository, base_ns)
    raise ValueError(f"unknown action {action!r}")


PAGE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>IFC2RDF local runner</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
#gdb{margin-top:18px;border-top:2px solid #2f4b7c;padding-top:8px}
#explore{height:560px;border:1px solid #ccc;background:#fff}
#hits div,#tbl td{cursor:pointer}#hits div:hover{background:#eef}
#hits{max-height:220px;overflow:auto;border:1px solid #ddd;background:#fff;font-size:12px}
table{border-collapse:collapse;font-size:12px;background:#fff}td,th{border:1px solid #ddd;padding:3px 6px}
.grid{display:grid;grid-template-columns:320px 1fr;gap:12px}
#detail{font-size:12px;word-break:break-all}
body{font-family:system-ui,sans-serif;margin:0;color:#222;background:#fafafa}
header{padding:12px 20px;background:#2f4b7c;color:#fff}main{padding:16px 20px;max-width:1200px}
label{display:block;font-size:13px;margin-top:10px;font-weight:600}
textarea,input[type=text]{width:100%;box-sizing:border-box;font-family:monospace;font-size:12px;padding:6px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
button{margin:12px 8px 0 0;padding:8px 14px;border:1px solid #2f4b7c;background:#fff;border-radius:4px;cursor:pointer}
button.primary{background:#2f4b7c;color:#fff}button:disabled{opacity:.5}
pre{background:#fff;border:1px solid #ddd;padding:8px;font-size:12px;max-height:320px;overflow:auto;white-space:pre-wrap}
.stage{margin-top:14px;border-top:1px solid #ddd;padding-top:8px}.ok{color:#2a7d2a}.err{color:#b00020}
iframe{width:100%;height:640px;border:1px solid #ccc;background:#fff}
small{color:#666}
</style></head><body>
<header><b>IFC2RDF</b> — local runner (BDNS-tagged MEP IFC + spatial IFC + BMS point list → Brick RDF)</header>
<main>
<div class="row">
 <div><label>MEP IFC (one path per line; BDNS-classified equipment)</label><textarea id="mep" rows="2"></textarea>
 <label>Spatial / ARC IFC (one path per line)</label><textarea id="arc" rows="2"></textarea>
 <label>BMS point list CSV</label><input type="text" id="points"></div>
 <div><label>Output folder</label><input type="text" id="out">
 <label>Base namespace</label><input type="text" id="base_ns" value="__BASE_NS__">
 <label>GraphDB home (to start it if needed)</label><input type="text" id="graphdb_home">
 <label>GraphDB URL / repository</label><input type="text" id="graphdb_url" value="http://localhost:7200">
 <input type="text" id="repository" value="IFC2RDF_case_study">
 <label><input type="checkbox" id="infer_spaces" checked> Stage 1: place equipment in ARC spaces from geometry</label>
 <label><input type="checkbox" id="local_view"> Stage 4 without GraphDB (local graph view)</label></div>
</div>
<div>
 <button onclick="run(['1'])">1 IFC → RDF</button>
 <button onclick="run(['2'])">2 Points → RDF</button>
 <button onclick="run(['3'])">3 Match & validate</button>
 <button onclick="run(['4'])">4 GraphDB / view</button>
 <button class="primary" onclick="run(['1','2','3','4'])">Run 1–4</button>
 <small id="busy"></small>
</div>
<div id="stages"></div>
<section id="gdb">
<h3>GraphDB</h3>
<div><span id="gdbstatus">not checked</span>
 <button onclick="gdbStatus()">Check</button><button onclick="gdbStart()">Start GraphDB</button>
 Repository <select id="repo"></select></div>
<div class="grid">
 <div>
  <label>Search equipment / space / point (IFC Name or point ID)</label>
  <input type="text" id="q" placeholder="e.g. AHU-0" onkeydown="if(event.key==='Enter')gdbSearch()">
  <button onclick="gdbSearch()">Search</button>
  <div id="hits"></div>
  <label>Selected</label><div id="detail">—</div>
  <button onclick="explore('neighbors')">Neighbors</button>
  <button onclick="explore('feeds')">Feeds path (up/downstream)</button>
  <button onclick="clearGraph()">Clear</button>
  <label>Checks</label>
  <button onclick="table('feeds_table')">All feeds</button>
  <button onclick="table('unlinked_points')">Unlinked points</button>
  <button onclick="table('unclassified_points')">Unclassified points</button>
 </div>
 <div><div id="explore"></div><small>Click a node to select it; double-click to expand its neighbors.</small></div>
</div>
<div id="tbl"></div>
</section>
<h3>Log</h3><pre id="log"></pre>
<h3>Graph view</h3><iframe id="view"></iframe>
</main>
<script>
const ids=["mep","arc","points","out","base_ns","graphdb_home","graphdb_url","repository"];
for(const id of ids){try{const v=localStorage.getItem("ifc2rdf_"+id);if(v)document.getElementById(id).value=v}catch(e){}}
function params(){const p={};for(const id of ids){p[id]=document.getElementById(id).value;try{localStorage.setItem("ifc2rdf_"+id,p[id])}catch(e){}}
 p.local_view=document.getElementById("local_view").checked;
 p.infer_spaces=document.getElementById("infer_spaces").checked;return p}
async function run(stages){const r=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({stages,params:params()})});
 if(!r.ok)alert(await r.text());poll()}
const names={"1":"1 IFC → RDF","2":"2 Points → RDF","3":"3 Match & validate","4":"4 GraphDB / view"};
async function poll(){const s=await (await fetch("/api/status")).json();
 document.getElementById("busy").textContent=s.running?("running stage "+s.running+" …"):"";
 document.querySelectorAll("button").forEach(b=>b.disabled=!!s.running);
 document.getElementById("log").textContent=s.log.join("\\n");
 let html="";for(const k of Object.keys(s.results).sort()){const r=s.results[k];
  html+=`<div class="stage"><b>${names[k]}</b> <span class="${r.ok?"ok":"err"}">${r.ok?"OK":"FAILED"}</span>`;
  if(r.files&&r.files.length)html+="<br>"+r.files.map(f=>`<a href="/files?path=${encodeURIComponent(f)}" target="_blank">${f}</a>`).join(" · ");
  html+=`<pre>${(r.ok?JSON.stringify(r.result,null,2):(r.error+"\\n\\n"+r.trace)).replace(/</g,"&lt;")}</pre></div>`;}
 document.getElementById("stages").innerHTML=html;
 if(s.results["4"]&&s.results["4"].ok){const f=document.getElementById("view");const src="/files?path=4_graphdb%2Fgraph_view.html&t="+s.stamp;if(!f.dataset.src||f.dataset.src!==src){f.src=src;f.dataset.src=src}}
 if(s.running)setTimeout(poll,1500)}
poll();

// ---- GraphDB panel ----
const colors={equipment:"#4C78A8",point:"#F58518",space:"#54A24B",storey:"#B279A2",other:"#9D9D9D"};
const gNodes=new vis.DataSet(), gEdges=new vis.DataSet();
let selected=null;
const net=new vis.Network(document.getElementById("explore"),{nodes:gNodes,edges:gEdges},
 {physics:{solver:"forceAtlas2Based",stabilization:{iterations:150}},edges:{smooth:false,font:{size:9}}});
net.on("click",p=>{if(p.nodes.length)select(p.nodes[0])});
net.on("doubleClick",p=>{if(p.nodes.length){select(p.nodes[0]);explore("neighbors")}});
function gq(){const p=params();const repo=document.getElementById("repo").value||p.repository;
 return `url=${encodeURIComponent(p.graphdb_url)}&repo=${encodeURIComponent(repo)}&ns=${encodeURIComponent(p.base_ns)}`}
async function gdb(action,extra){const r=await fetch(`/api/gdb/${action}?${gq()}${extra||""}`);const d=await r.json();
 if(!r.ok){alert(d.error||"GraphDB request failed");throw new Error(d.error)}return d}
async function gdbStatus(){const s=await gdb("status");
 document.getElementById("gdbstatus").textContent=s.running?"running":(s.starting?"starting …":"not running");
 const sel=document.getElementById("repo"),cur=sel.value||document.getElementById("repository").value;
 sel.innerHTML=s.repositories.map(r=>`<option${r===cur?" selected":""}>${r}</option>`).join("");
 if(s.starting)setTimeout(gdbStatus,3000)}
async function gdbStart(){const p=params();const r=await fetch("/api/gdb/start",{method:"POST",headers:{"Content-Type":"application/json"},
 body:JSON.stringify({url:p.graphdb_url,home:p.graphdb_home})});if(!r.ok)alert(await r.text());setTimeout(gdbStatus,1000)}
function esc(t){return String(t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
async function gdbSearch(){const d=await gdb("search",`&q=${encodeURIComponent(document.getElementById("q").value)}`);
 document.getElementById("hits").innerHTML=d.rows.map(r=>`<div data-iri="${esc(r.n)}">${esc(r.name)} <small>${esc(r.kind)}</small></div>`).join("")||"<div>no match</div>";
 document.querySelectorAll("#hits div[data-iri]").forEach(el=>el.onclick=()=>{select(el.dataset.iri);explore("neighbors")})}
function select(iri){selected=iri;const n=gNodes.get(iri);
 document.getElementById("detail").innerHTML=n?`<b>${esc(n.label)}</b><br>${esc(n.types||"")}<br><small>${esc(iri)}</small>`:esc(iri)}
function addGraph(d){gNodes.update(d.nodes.map(n=>({id:n.id,label:n.label,types:n.types,title:(n.types||"")+"\\n"+n.id,
 color:colors[n.group]||colors.other,shape:n.group==="point"?"dot":"box",size:8})));
 gEdges.update(d.edges.map(e=>({id:e.s+"|"+e.p+"|"+e.o,from:e.s,to:e.o,label:e.p,arrows:"to",
 color:e.p==="feeds"?"#D62728":"#888",width:e.p==="feeds"?3:1})))}
async function explore(kind){if(!selected){alert("Select a node first");return}
 addGraph(await gdb(kind,`&iri=${encodeURIComponent(selected)}`));if(selected)net.selectNodes([selected]);select(selected)}
function clearGraph(){gNodes.clear();gEdges.clear()}
async function table(name){const d=await gdb("table",`&name=${name}`);
 document.getElementById("tbl").innerHTML=`<h4>${name} (${d.rows.length})</h4><table><tr>${d.columns.map(c=>`<th>${c}</th>`).join("")}</tr>`+
 d.rows.map(r=>`<tr>${d.columns.map(c=>`<td>${esc(r[c]||"")}</td>`).join("")}</tr>`).join("")+"</table>"}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    out_dir: Path | None = None

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:  # keep the console quiet
        pass

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, PAGE.replace("__BASE_NS__", DEFAULT_BASE_NS).encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/api/status":
            with LOCK:
                results = {}
                for stage, value in STATE["results"].items():
                    folder = Handler.out_dir / STAGE_DIRS[stage] if Handler.out_dir else None
                    files = sorted(f"{STAGE_DIRS[stage]}/{p.name}" for p in folder.iterdir() if p.is_file()) \
                        if folder and folder.is_dir() else []
                    results[stage] = {**value, "files": files}
                body = {"running": STATE["running"], "log": STATE["log"][-200:], "results": results,
                        "stamp": len(STATE["log"])}
            self._send(200, json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"), "application/json")
        elif url.path.startswith("/api/gdb/"):
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                body, code = graphdb_api(url.path.rsplit("/", 1)[1], query), 200
            except ValueError as exc:
                body, code = {"error": str(exc)}, 400
            except Exception as exc:  # shown to the user by the page
                body, code = {"error": f"{type(exc).__name__}: {exc}"}, 500
            self._send(code, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")
        elif url.path == "/files" and Handler.out_dir:
            relative = parse_qs(url.query).get("path", [""])[0]
            target = (Handler.out_dir / relative).resolve()
            if Handler.out_dir.resolve() not in target.parents or not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            kinds = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
                     ".csv": "text/plain; charset=utf-8", ".ttl": "text/plain; charset=utf-8",
                     ".log": "text/plain; charset=utf-8"}
            self._send(200, target.read_bytes(), kinds.get(target.suffix, "application/octet-stream"))
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if path == "/api/gdb/start":
            home = (payload.get("home") or "").strip().strip('"')
            if not home or not Path(home).is_dir():
                self._send(400, "GraphDB home folder is required".encode("utf-8"), "text/plain; charset=utf-8")
                return
            with LOCK:
                if STATE.get("graphdb_starting"):
                    self._send(409, b"GraphDB is already starting", "text/plain")
                    return
                STATE["graphdb_starting"] = True
            threading.Thread(target=_start_graphdb, args=(payload.get("url") or "http://localhost:7200", home),
                             daemon=True).start()
            self._send(202, b"starting", "text/plain")
            return
        if path != "/api/run":
            self._send(404, b"not found", "text/plain")
            return
        params, stages = payload.get("params", {}), payload.get("stages", [])
        if not (params.get("out") or "").strip():
            self._send(400, "Output folder is required".encode("utf-8"), "text/plain; charset=utf-8")
            return
        with LOCK:
            if STATE["running"]:
                self._send(409, b"a stage is already running", "text/plain")
                return
            STATE["running"] = stages[0] if stages else None
            for stage in stages:
                STATE["results"].pop(stage, None)
        Handler.out_dir = Path(params["out"].strip().strip('"'))
        threading.Thread(target=_worker, args=(stages, params), daemon=True).start()
        self._send(202, b"started", "text/plain")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"IFC2RDF UI at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
