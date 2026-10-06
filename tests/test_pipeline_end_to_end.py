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
from create_synthetic_inputs import create_synthetic_inputs
from rdf import BRICK, equipment_iri, spatial_iri


def test_complete_synthetic_ifc_and_bms_pipeline(tmp_path):
    inputs = create_synthetic_inputs(tmp_path / "input")
    output = tmp_path / "output"
    base_ns = "https://example.org/synthetic-building#"

    result = run_pipeline(
        mep_ifc_paths=inputs["mep_ifc"],
        arc_ifc_paths=inputs["arc_ifc"],
        points_csv=inputs["points_csv"],
        mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
        output_dir=output,
        base_ns=base_ns,
    )

    assert result["mep_ifc_count"] == 2
    assert result["arc_ifc_count"] == 2
    assert result["equipment_count"] == 3
    assert result["bdns_classified_equipment_count"] == 3
    assert result["point_count"] == 3
    assert result["relation_count"] == 7
    assert result["validation"]["conforms"] is True
    assert result["capabilities"]["CLASSIFICATION"]["status"] == "PASS"
    assert result["capabilities"]["LOCATION"]["status"] == "PASS"
    assert result["capabilities"]["FLOW_TOPOLOGY"]["status"] == "PASS"
    assert "3/3 have spatial context via equipment" in result["capabilities"]["POINT_LINKAGE"]["evidence"]

    graph = Graph().parse(output / "building_brick.ttl", format="turtle")
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
    assert len(list(graph.triples((None, BRICK.hasUnit, None)))) == 1
    for point in graph.objects(ahu, BRICK.hasPoint):
        assert list(graph.objects(ahu, BRICK.hasLocation))
    for point in graph.objects(fcu, BRICK.hasPoint):
        assert list(graph.objects(fcu, BRICK.hasLocation))
    for point in graph.objects(pump, BRICK.hasPoint):
        assert list(graph.objects(pump, BRICK.hasLocation))

    for name in (
        "building_brick.ttl",
        "provenance.csv",
        "requirement_report.json",
        "validation_report.json",
    ):
        assert (output / name).is_file()
