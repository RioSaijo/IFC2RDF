from pathlib import Path
from types import SimpleNamespace
import sys

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.guid
from rdflib import Graph


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

from app.pipeline import run_pipeline
from rdf import BRICK


def _guid() -> str:
    return ifcopenshell.guid.new()


def test_cross_model_geometry_is_review_required(monkeypatch, tmp_path):
    mep = ifcopenshell.file(schema="IFC4")
    equipment = mep.create_entity(
        "IfcUnitaryEquipment",
        GlobalId=_guid(),
        Name="Synthetic uncontained AHU",
    )
    classification = mep.create_entity(
        "IfcClassification",
        Source="Synthetic",
        Edition="example",
        Name="BDNS",
    )
    reference = mep.create_entity(
        "IfcClassificationReference",
        Identification="AHU-1",
        Name="Air handling unit",
        ReferencedSource=classification,
    )
    mep.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=_guid(),
        RelatedObjects=[equipment],
        RelatingClassification=reference,
    )
    mep_path = tmp_path / "mep.ifc"
    mep.write(mep_path)

    arc = ifcopenshell.file(schema="IFC4")
    arc.create_entity("IfcSpace", GlobalId=_guid(), Name="Synthetic geometry space")
    arc_path = tmp_path / "arc.ifc"
    arc.write(arc_path)

    def fake_shape(_settings, obj):
        if obj.is_a("IfcSpace"):
            vertices = [0.0, 0.0, 0.0, 10.0, 10.0, 10.0]
        else:
            vertices = [1.0, 1.0, 1.0, 2.0, 2.0, 2.0]
        return SimpleNamespace(geometry=SimpleNamespace(verts=vertices))

    monkeypatch.setattr(ifcopenshell.geom, "create_shape", fake_shape)
    output = tmp_path / "output"
    result = run_pipeline(
        mep_ifc_paths=[mep_path],
        arc_ifc_paths=[arc_path],
        mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
        output_dir=output,
        geometry_fallback=True,
    )

    assert result["capabilities"]["LOCATION"]["status"] == "PASS"
    assert result["validation"]["review_required_relation_count"] == 1
    assert result["validation"]["conforms"] is False
    graph = Graph().parse(output / "building_brick.ttl", format="turtle")
    assert len(list(graph.triples((None, BRICK.hasLocation, None)))) == 1
