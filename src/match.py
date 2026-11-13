"""Stage 3: resolve BMS point references against the IFC-derived RDF and validate.

Inputs are the two RDF files produced by stage 1 (IFC) and stage 2 (points).
A point's equipment_ref is the BDNS asset instance ID (e.g. AHU-00001). It is
matched only to the equipment whose BDNS classification value is that ID; the
IFC Name is not used for equipment. A space_ref is matched to an ARC space
whose IFC Name equals it (e.g. 01-02). Each match becomes
`<equipment or space> brick:hasPoint <point>`.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from mapping import is_bdns_instance_id
from rdf import BOT, BRICK


def _index(graph: Graph, project: Namespace):
    """Equipment keyed by BDNS instance ID, spaces by IFC Name."""
    equipment = defaultdict(list)
    spaces = defaultdict(list)
    for subject, code in graph.subject_objects(project.bdnsClassificationCode):
        if is_bdns_instance_id(str(code)):
            equipment[str(code)].append((subject, "bdns_classification_instance_id"))
    for subject in graph.subjects(RDF.type, BOT.Space):
        name = graph.value(subject, project.ifcName)
        if name is not None:
            spaces[str(name)].append((subject, "ifc_space_name"))
    return equipment, spaces


def run_match_stage(
    ifc_ttl: str | Path,
    points_ttl: str | Path,
    output_dir: str | Path,
    base_ns: str,
) -> Dict[str, object]:
    project = Namespace(base_ns)
    ifc = Graph().parse(str(ifc_ttl), format="turtle")
    points = Graph().parse(str(points_ttl), format="turtle")
    equipment_by_name, spaces_by_name = _index(ifc, project)

    links = Graph()
    rows: List[Dict[str, object]] = []
    for point in sorted(points.subjects(project.pointId, None)):
        point_id = str(points.value(point, project.pointId))
        equipment_ref = points.value(point, project.equipmentRef)
        space_ref = points.value(point, project.spaceRef)
        ref_type, ref = ("equipment", str(equipment_ref)) if equipment_ref else ("space", str(space_ref or ""))
        candidates = (equipment_by_name if ref_type == "equipment" else spaces_by_name).get(ref, [])
        row = {
            "point_id": point_id,
            "point_class": ", ".join(sorted(str(t).split("#")[-1] for t in points.objects(point, RDF.type))),
            "classification": str(points.value(point, project.classificationStatus) or ""),
            "ref_type": ref_type,
            "ref": ref,
            "status": "",
            "target": "",
            "method": "",
            "review_required": False,
            "reason": "",
        }
        if not ref:
            row.update(status="unresolved", reason="point has neither equipment_ref nor space_ref")
        elif not candidates:
            key = "BDNS instance ID" if ref_type == "equipment" else "IFC Name"
            row.update(status="unresolved", reason=f"no {ref_type} with {key} {ref!r} in the IFC RDF")
        elif len(candidates) > 1:
            key = "BDNS instance ID" if ref_type == "equipment" else "IFC Name"
            row.update(status="ambiguous", reason=f"{len(candidates)} {ref_type} elements share {key} {ref!r}")
        else:
            target, method = candidates[0]
            row.update(status="linked", target=str(target), method=method)
            links.add((target, BRICK.hasPoint, point))
        if row["classification"] == "unclassified":
            row["review_required"] = True
            row["reason"] = "; ".join(filter(None, [row["reason"], "point class could not be assigned"]))
        rows.append(row)

    linked = Graph()
    for graph in (ifc, points, links):
        for prefix, namespace in graph.namespaces():
            linked.bind(prefix, namespace, override=False)
        linked += graph

    located_equipment = set(ifc.subjects(BRICK.hasLocation, None))
    equipment_points = [r for r in rows if r["ref_type"] == "equipment" and r["status"] == "linked"]
    statuses = Counter((r["ref_type"], r["status"]) for r in rows)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    linked_ttl = output / "linked_brick.ttl"
    linked.serialize(destination=str(linked_ttl), format="turtle")
    results_csv = output / "match_results.csv"
    with results_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["point_id"])
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "inputs": {"ifc_ttl": str(Path(ifc_ttl).resolve()), "points_ttl": str(Path(points_ttl).resolve())},
        "points": len(rows),
        "linked": sum(r["status"] == "linked" for r in rows),
        "by_reference": {f"{k[0]}:{k[1]}": v for k, v in sorted(statuses.items())},
        "review_required": sum(bool(r["review_required"]) for r in rows),
        "equipment_points_with_equipment_location": sum(
            1 for r in equipment_points if any(str(s) == r["target"] for s in located_equipment)
        ),
        "unresolved_refs": sorted({r["ref"] for r in rows if r["status"] != "linked"}),
        "linked_triple_count": len(linked),
        # conforms: every link that was made is unambiguous and needs no review.
        # complete: every point was linked. They are reported apart so that missing
        # references in the input do not hide whether the links themselves are sound.
        "conforms": not any(r["status"] == "ambiguous" or r["review_required"] for r in rows),
        "complete": all(r["status"] == "linked" for r in rows),
        "note": "Project-level reference and class checks; full Brick SHACL validation is not claimed.",
        "outputs": {"ttl": str(linked_ttl), "results": str(results_csv)},
    }
    (output / "match_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
