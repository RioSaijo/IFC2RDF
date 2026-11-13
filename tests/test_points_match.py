"""Stages 2-3 on synthetic inputs: point list -> RDF, then match against the IFC RDF."""
import csv
from pathlib import Path
import sys

import ifcopenshell.guid
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "examples"))

from app.pipeline import run_pipeline
from bms_points import POINT_LIST_COLUMNS, run_points_stage
from create_synthetic_inputs import _create_arc
from match import run_match_stage
from rdf import BRICK
from test_topology import _Builder

BASE_NS = "https://example.org/points#"
PROJECT = Namespace(BASE_NS)
RESOURCES = PROJECT_ROOT / "data" / "resources"

POINTS = [
    # point_id, object_name, object_type, units, equipment_ref, space_ref
    ("AHU-00001_SAT", "AHU-00001 Supply Air Temperature", "AI", "degC", "AHU-00001", ""),
    ("AHU-00001_FST", "AHU-00001 Fan Status", "BI", "", "AHU-00001", ""),
    ("AHU-00001_AI7", "AHU-00001 Analog Input 7", "AI", "", "AHU-00001", ""),
    ("VAV-00001_ZAT", "VAV-00001 Zone Air Temperature", "AI", "degC", "VAV-00001", ""),
    ("AHU-00009_SAT", "AHU-00009 Supply Air Temperature", "AI", "degC", "AHU-00009", ""),
    ("ROOM_T", "Room T Temperature", "AI", "degC", "", "Synthetic Room T"),
    ("ROOM_X", "Room X Temperature", "AI", "degC", "", "99-99"),
    ("BAD_UNIT", "VAV-00001 Zone Air Temperature", "AI", "ppm", "VAV-00001", ""),
    ("BAD_BINARY", "VAV-00001 Occupancy", "BI", "degC", "VAV-00001", ""),
]


def _run(tmp_path):
    b = _Builder()
    ahu = b.element("IfcEnergyConversionDevice", "AHU-00001", "AHU-00001")
    vav = b.element("IfcFlowController", "VAV-00001", "VAV-00001")
    b.element("IfcEnergyConversionDevice", "AHU-00009", "AHU")  # type-level tag only: left out of stage 1
    b.flow(ahu, vav)
    mep, arc = tmp_path / "mep.ifc", tmp_path / "arc.ifc"
    b.model.write(mep)
    _create_arc(arc, ifcopenshell.guid.new(), "T")
    run_pipeline(mep_ifc_paths=[mep], arc_ifc_paths=[arc], output_dir=tmp_path / "1_ifc",
                 mapping_csv_path=RESOURCES / "BDNS mapping partial.csv", base_ns=BASE_NS)

    points_csv = tmp_path / "points.csv"
    with points_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINT_LIST_COLUMNS)
        writer.writeheader()
        for index, (pid, name, otype, units, eref, sref) in enumerate(POINTS, start=1):
            writer.writerow({"point_id": pid, "object_name": name, "description": "", "object_type": otype,
                             "device_instance": 100, "object_instance": index, "units": units,
                             "equipment_ref": eref, "space_ref": sref})
    points = run_points_stage(points_csv, RESOURCES / "brick_classes.json", tmp_path / "2_points", BASE_NS)
    match = run_match_stage(tmp_path / "1_ifc" / "building_brick.ttl", tmp_path / "2_points" / "points_brick.ttl",
                            tmp_path / "3_match", BASE_NS)
    with (tmp_path / "3_match" / "match_results.csv").open(encoding="utf-8", newline="") as handle:
        rows = {r["point_id"]: r for r in csv.DictReader(handle)}
    return points, match, rows, tmp_path


def _issues(tmp_path):
    with (tmp_path / "2_points" / "point_list_issues.csv").open(encoding="utf-8", newline="") as handle:
        return [(r["point_id"], r["issue"]) for r in csv.DictReader(handle)]


def test_point_list_checks_units_and_classes(tmp_path):
    points, _, _, out = _run(tmp_path)
    issues = _issues(out)

    assert points["points"] == len(POINTS)
    assert points["classification"] == {"classified": 5, "out_of_scope": 1, "unclassified": 3}
    assert any(p == "BAD_UNIT" and "contradicts" in i for p, i in issues)
    assert any(p == "BAD_BINARY" and "binary object has a unit" in i for p, i in issues)
    assert not any(p == "AHU-00001_SAT" for p, _ in issues)


def test_classes_are_assigned_and_unclear_points_stay_plain_points(tmp_path):
    _, _, _, out = _run(tmp_path)
    graph = Graph().parse(out / "2_points" / "points_brick.ttl", format="turtle")
    sat = next(graph.subjects(PROJECT.pointId, Literal("AHU-00001_SAT")))
    unclear = next(graph.subjects(PROJECT.pointId, Literal("AHU-00001_AI7")))

    assert (sat, RDF.type, BRICK.Supply_Air_Temperature_Sensor) in graph
    assert set(graph.objects(unclear, RDF.type)) == {BRICK.Point}
    assert graph.value(unclear, PROJECT.classificationStatus) == Literal("unclassified")
    assert not list(graph.subjects(PROJECT.pointId, Literal("AHU-00001_FST")))  # status point is out of scope


def test_points_link_to_equipment_and_spaces_by_ifc_name(tmp_path):
    _, match, rows, out = _run(tmp_path)
    linked = Graph().parse(out / "3_match" / "linked_brick.ttl", format="turtle")
    ahu = next(linked.subjects(PROJECT.ifcName, Literal("AHU-00001")))
    room = next(linked.subjects(PROJECT.ifcName, Literal("Synthetic Room T")))
    sat = next(linked.subjects(PROJECT.pointId, Literal("AHU-00001_SAT")))
    room_point = next(linked.subjects(PROJECT.pointId, Literal("ROOM_T")))

    assert (ahu, BRICK.hasPoint, sat) in linked
    assert (room, BRICK.hasPoint, room_point) in linked
    assert rows["AHU-00001_SAT"]["status"] == "linked"
    assert rows["AHU-00001_SAT"]["review_required"] == "False"


def test_unknown_space_is_unresolved(tmp_path):
    _, match, rows, _ = _run(tmp_path)

    assert rows["ROOM_X"]["status"] == "unresolved"
    assert "99-99" in match["unresolved_refs"]
    assert match["complete"] is False


def test_points_link_on_bdns_instance_id(tmp_path):
    _, _, rows, _ = _run(tmp_path)

    assert rows["AHU-00001_SAT"]["method"] == "bdns_classification_instance_id"


def test_type_level_bdns_tag_is_left_out_and_not_matched_by_name(tmp_path):
    _, _, rows, out = _run(tmp_path)
    with (out / "1_ifc" / "bdns_tag_issues.csv").open(encoding="utf-8", newline="") as handle:
        issues = list(csv.DictReader(handle))
    linked = Graph().parse(out / "3_match" / "linked_brick.ttl", format="turtle")

    assert [(r["ifc_name"], r["bdns_tag"]) for r in issues] == [("AHU-00009", "AHU")]
    assert not list(linked.subjects(PROJECT.ifcName, Literal("AHU-00009")))
    assert rows["AHU-00009_SAT"]["status"] == "unresolved"
    assert "BDNS instance ID" in rows["AHU-00009_SAT"]["reason"]


def test_duplicate_bdns_instance_id_is_a_conflict(tmp_path):
    b = _Builder()
    b.element("IfcEnergyConversionDevice", "AHU-00001", "AHU-00001")
    b.element("IfcEnergyConversionDevice", "AHU-00001 copy", "AHU-00001")
    mep, arc = tmp_path / "mep.ifc", tmp_path / "arc.ifc"
    b.model.write(mep)
    _create_arc(arc, ifcopenshell.guid.new(), "T")
    result = run_pipeline(mep_ifc_paths=[mep], arc_ifc_paths=[arc], output_dir=tmp_path / "1_ifc",
                          mapping_csv_path=RESOURCES / "BDNS mapping partial.csv", base_ns=BASE_NS)

    assert result["capabilities"]["IDENTITY"]["status"] != "PASS"
    assert result["validation"]["conforms"] is False

