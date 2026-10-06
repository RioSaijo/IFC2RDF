from pathlib import Path
import sys

from rdflib import Graph, Namespace, URIRef
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
        ifc_path=inputs["ifc"],
        points_csv=inputs["points_csv"],
        mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
        output_dir=output,
        base_ns=base_ns,
    )

    assert result["equipment_count"] == 2
    assert result["bdns_classified_equipment_count"] == 2
    assert result["point_count"] == 2
    assert result["relation_count"] == 5
    assert result["validation"]["conforms"] is True
    assert result["capabilities"]["CLASSIFICATION"]["status"] == "PASS"
    assert result["capabilities"]["LOCATION"]["status"] == "PASS"
    assert result["capabilities"]["FLOW_TOPOLOGY"]["status"] == "PASS"

    graph = Graph().parse(output / "building_brick.ttl", format="turtle")
    ahu = equipment_iri(base_ns, inputs["ahu_guid"])
    fcu = equipment_iri(base_ns, inputs["fcu_guid"])
    space = spatial_iri(base_ns, inputs["space_guid"])
    project = Namespace(base_ns)
    assert (ahu, RDF.type, BRICK.Air_Handling_Unit) in graph
    assert (fcu, RDF.type, BRICK.Fan_Coil_Unit) in graph
    assert (ahu, BRICK.hasLocation, space) in graph
    assert (fcu, BRICK.hasLocation, space) in graph
    assert (ahu, BRICK.feeds, fcu) in graph
    assert len(list(graph.objects(ahu, BRICK.hasPoint))) == 1
    assert len(list(graph.objects(fcu, BRICK.hasPoint))) == 1
    assert (ahu, project.bdnsClassificationCode, None) in graph

    for name in (
        "building_brick.ttl",
        "provenance.csv",
        "requirement_report.json",
        "validation_report.json",
    ):
        assert (output / name).is_file()
