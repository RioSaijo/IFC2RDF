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


def test_partial_classification_is_warning(tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    classification = model.create_entity(
        "IfcClassification",
        Source="Synthetic",
        Edition="example",
        Name="BDNS",
    )
    reference = model.create_entity(
        "IfcClassificationReference",
        Identification="AHU-1",
        Name="Air handling unit",
        ReferencedSource=classification,
    )
    classified = model.create_entity(
        "IfcUnitaryEquipment",
        GlobalId=ifcopenshell.guid.new(),
        Name="Classified",
    )
    model.create_entity(
        "IfcUnitaryEquipment",
        GlobalId=ifcopenshell.guid.new(),
        Name="Unclassified",
    )
    model.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[classified],
        RelatingClassification=reference,
    )
    path = tmp_path / "partial.ifc"
    model.write(path)

    result = extract_ifc(load_ifc(path))

    assert result.audit["counts"]["bdns_classified_assets"] == 1
    assert result.audit["counts"]["unresolved_assets"] == 1
    assert result.audit["capabilities"]["CLASSIFICATION"]["status"] == "WARN"


def test_connection_direction_is_conservative_with_sourceandsink(tmp_path):
    model = ifcopenshell.file(schema="IFC4")
    classification = model.create_entity("IfcClassification", Name="BDNS")
    reference = model.create_entity(
        "IfcClassificationReference",
        Identification="AHU-1",
        ReferencedSource=classification,
    )
    equipment = [
        model.create_entity(
            "IfcUnitaryEquipment",
            GlobalId=ifcopenshell.guid.new(),
            Name=f"Equipment {index}",
        )
        for index in range(4)
    ]
    model.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=equipment,
        RelatingClassification=reference,
    )
    directions = ["SOURCE", "SOURCEANDSINK", "SOURCEANDSINK", "SOURCEANDSINK"]
    ports = []
    for item, direction in zip(equipment, directions):
        port = model.create_entity(
            "IfcDistributionPort",
            GlobalId=ifcopenshell.guid.new(),
            FlowDirection=direction,
        )
        ports.append(port)
        model.create_entity(
            "IfcRelNests",
            GlobalId=ifcopenshell.guid.new(),
            RelatingObject=item,
            RelatedObjects=[port],
        )
    model.create_entity(
        "IfcRelConnectsPorts",
        GlobalId=ifcopenshell.guid.new(),
        RelatingPort=ports[0],
        RelatedPort=ports[1],
    )
    model.create_entity(
        "IfcRelConnectsPorts",
        GlobalId=ifcopenshell.guid.new(),
        RelatingPort=ports[2],
        RelatedPort=ports[3],
    )
    path = tmp_path / "sourceandsink.ifc"
    model.write(path)

    result = extract_ifc(load_ifc(path))

    assert len([item for item in result.relations if item.predicate == "brick:feeds"]) == 1
    assert [item.decision_status for item in result.connection_inferences].count("directed") == 1
    assert [item.decision_status for item in result.connection_inferences].count("ambiguous") == 1
    ambiguous = next(
        item for item in result.connection_inferences if item.decision_status == "ambiguous"
    )
    assert ambiguous.source_equipment_guid is None
    assert ambiguous.target_equipment_guid is None
    assert ambiguous.review_required is True
