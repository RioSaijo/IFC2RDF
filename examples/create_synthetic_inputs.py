from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict

import ifcopenshell
import ifcopenshell.guid


def _guid() -> str:
    return ifcopenshell.guid.new()


def create_synthetic_inputs(output_dir: str | Path) -> Dict[str, str]:
    """Create a small, fully synthetic IFC/BMS example for public testing."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    model = ifcopenshell.file(schema="IFC4")
    space = model.create_entity("IfcSpace", GlobalId=_guid(), Name="Synthetic Room")
    ahu = model.create_entity("IfcUnitaryEquipment", GlobalId=_guid(), Name="Synthetic AHU")
    fcu = model.create_entity("IfcUnitaryEquipment", GlobalId=_guid(), Name="Synthetic FCU")

    bdns = model.create_entity(
        "IfcClassification",
        Source="Synthetic public example",
        Edition="example",
        Name="BDNS",
    )
    ahu_ref = model.create_entity(
        "IfcClassificationReference",
        Identification="AHU-1",
        Name="Air handling unit",
        ReferencedSource=bdns,
    )
    fcu_ref = model.create_entity(
        "IfcClassificationReference",
        Identification="FCU-1",
        Name="Fan coil unit",
        ReferencedSource=bdns,
    )
    for equipment, reference in ((ahu, ahu_ref), (fcu, fcu_ref)):
        model.create_entity(
            "IfcRelAssociatesClassification",
            GlobalId=_guid(),
            RelatedObjects=[equipment],
            RelatingClassification=reference,
        )

    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatedElements=[ahu, fcu],
        RelatingStructure=space,
    )

    source_port = model.create_entity(
        "IfcDistributionPort",
        GlobalId=_guid(),
        Name="AHU supply",
        FlowDirection="SOURCE",
    )
    sink_port = model.create_entity(
        "IfcDistributionPort",
        GlobalId=_guid(),
        Name="FCU inlet",
        FlowDirection="SINK",
    )
    model.create_entity(
        "IfcRelNests",
        GlobalId=_guid(),
        RelatingObject=ahu,
        RelatedObjects=[source_port],
    )
    model.create_entity(
        "IfcRelNests",
        GlobalId=_guid(),
        RelatingObject=fcu,
        RelatedObjects=[sink_port],
    )
    model.create_entity(
        "IfcRelConnectsPorts",
        GlobalId=_guid(),
        RelatingPort=source_port,
        RelatedPort=sink_port,
    )

    ifc_path = output / "synthetic_bdns.ifc"
    model.write(ifc_path)

    points_path = output / "synthetic_points.csv"
    with points_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["point_id", "name", "unit", "bdns_abbreviation"],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "point_id": "P-1",
                    "name": "supply_air_temperature",
                    "unit": "degC",
                    "bdns_abbreviation": "AHU-1",
                },
                {
                    "point_id": "P-2",
                    "name": "fan_status",
                    "unit": "",
                    "bdns_abbreviation": "FCU-1",
                },
            ]
        )

    return {
        "ifc": str(ifc_path),
        "points_csv": str(points_path),
        "ahu_guid": str(ahu.GlobalId),
        "fcu_guid": str(fcu.GlobalId),
        "space_guid": str(space.GlobalId),
    }


if __name__ == "__main__":
    paths = create_synthetic_inputs(Path(__file__).resolve().parent / "generated")
    for name, value in paths.items():
        print(f"{name}: {value}")
