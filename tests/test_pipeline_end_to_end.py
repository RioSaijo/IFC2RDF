import csv
from pathlib import Path
import sys

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
EXAMPLES = PROJECT_ROOT / "examples"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(EXAMPLES))

from app.pipeline import run_pipeline
from bms_points import run_points_stage
from create_synthetic_inputs import create_synthetic_inputs
from match import run_match_stage
from rdf import BRICK, equipment_iri, spatial_iri


def test_complete_synthetic_ifc_and_bms_pipeline(tmp_path):
    inputs = create_synthetic_inputs(tmp_path / "input")
    output = tmp_path / "output"
    base_ns = "https://example.org/synthetic-building#"

    result = run_pipeline(
        mep_ifc_paths=inputs["mep_ifc"],
        arc_ifc_paths=inputs["arc_ifc"],
        mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
        output_dir=output,
        base_ns=base_ns,
    )
    resources = PROJECT_ROOT / "data" / "resources"
    run_points_stage(inputs["points_csv"], resources / "brick_classes.json", tmp_path / "points", base_ns)
    match = run_match_stage(output / "building_brick.ttl", tmp_path / "points" / "points_brick.ttl",
                            tmp_path / "match", base_ns)

    assert result["mep_ifc_count"] == 2
    assert result["arc_ifc_count"] == 2
    assert result["equipment_count"] == 3
    assert result["bdns_classified_equipment_count"] == 3
    assert result["relation_count"] == 4
    assert match["linked"] == 3 and match["conforms"] is True and match["complete"] is True
    assert result["validation"]["conforms"] is True
    assert result["capabilities"]["CLASSIFICATION"]["status"] == "PASS"
    assert result["capabilities"]["LOCATION"]["status"] == "PASS"
    assert result["capabilities"]["FLOW_TOPOLOGY"]["status"] == "PASS"

    graph = Graph().parse(tmp_path / "match" / "linked_brick.ttl", format="turtle")
    ahu = equipment_iri(base_ns, inputs["ahu_guid"])
    fcu = equipment_iri(base_ns, inputs["fcu_guid"])
    pump = equipment_iri(base_ns, inputs["pump_guid"])
    room_a = spatial_iri(base_ns, inputs["room_a_guid"])
    room_b = spatial_iri(base_ns, inputs["room_b_guid"])
    project = Namespace(base_ns)
    assert (ahu, RDF.type, BRICK.Air_Handling_Unit) in graph
    assert (fcu, RDF.type, BRICK.Fan_Coil_Unit) in graph
    assert (pump, RDF.type, BRICK.Circulator_Pump) in graph
    assert (ahu, BRICK.hasLocation, room_a) in graph
    assert (fcu, BRICK.hasLocation, room_a) in graph
    assert (pump, BRICK.hasLocation, room_b) in graph
    assert (ahu, BRICK.feeds, fcu) in graph
    assert len(list(graph.objects(ahu, BRICK.hasPoint))) == 1
    assert len(list(graph.objects(fcu, BRICK.hasPoint))) == 1
    assert len(list(graph.objects(pump, BRICK.hasPoint))) == 1
    assert (ahu, project.bdnsClassificationCode, None) in graph
    assert (room_a, project.ifcLongName, Literal("Synthetic ARC Room A")) in graph
    assert (
        room_a,
        project.ifcDescription,
        Literal("Public synthetic architectural space"),
    ) in graph
    assert len(list(graph.triples((None, project.ifcElevation, Literal(3.0))))) == 2
    assert len(list(graph.triples((None, BRICK.hasUnit, None)))) == 3
    for point in graph.objects(ahu, BRICK.hasPoint):
        assert list(graph.objects(ahu, BRICK.hasLocation))
    for point in graph.objects(fcu, BRICK.hasPoint):
        assert list(graph.objects(fcu, BRICK.hasLocation))
    for point in graph.objects(pump, BRICK.hasPoint):
        assert list(graph.objects(pump, BRICK.hasLocation))

    for name in (
        "building_brick.ttl",
        "connection_inference.csv",
        "equipment_mapping.csv",
        "provenance.csv",
        "requirement_report.json",
        "topology_paths.csv",
        "validation_report.json",
    ):
        assert (output / name).is_file()

    with (output / "equipment_mapping.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        mapping_rows = list(csv.DictReader(handle))
    assert len(mapping_rows) == 3
    assert {row["bdns_code"] for row in mapping_rows} == {"AHU-1", "FCU-1", "CP-1"}
    assert all(row["target_ontology_class"] for row in mapping_rows)
    assert all(row["mapping_status"] == "project-defined" for row in mapping_rows)

    with (output / "connection_inference.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        connection_rows = list(csv.DictReader(handle))
    assert len(connection_rows) == 1
    assert connection_rows[0]["decision_status"] == "directed"
    assert connection_rows[0]["inference_method"] == "explicit_source_sink_flow_direction"
    assert connection_rows[0]["review_required"] == "false"
