from pathlib import Path
import sys

import ifcopenshell
import ifcopenshell.guid


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ifc import extract_ifc, load_ifc


def test_bdns_ifc_relationship_is_primary_source(tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    classification = model.create_entity(
        "IfcClassification",
        Source="BDNS Registry",
        Edition="2.1.3",
        Name="BDNS",
    )
    reference = model.create_entity(
        "IfcClassificationReference",
        Identification="AHU-1",
        Name="Air handling unit",
        ReferencedSource=classification,
    )
    equipment = model.create_entity(
        "IfcUnitaryEquipment",
        GlobalId=ifcopenshell.guid.new(),
        Name="Name is not used as the BDNS assignment",
    )
    model.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[equipment],
        RelatingClassification=reference,
    )
    path = tmp_path / "classified.ifc"
    model.write(path)

    result = extract_ifc(load_ifc(path))

    assert len(result.assets) == 1
    assert result.assets[0].bdns_code == "AHU-1"
    assert result.assets[0].classification_name == "BDNS"
    assert result.audit["capabilities"]["CLASSIFICATION"]["status"] == "PASS"
