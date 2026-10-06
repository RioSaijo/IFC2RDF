from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict

import ifcopenshell
import ifcopenshell.guid


def _guid() -> str:
    return ifcopenshell.guid.new()


def _classification(model, equipment, code: str, label: str) -> None:
    bdns = next(iter(model.by_type("IfcClassification")), None)
    if bdns is None:
        bdns = model.create_entity(
            "IfcClassification",
            Source="Synthetic public example",
            Edition="example",
            Name="BDNS",
        )
    reference = model.create_entity(
        "IfcClassificationReference",
        Identification=code,
        Name=label,
        ReferencedSource=bdns,
    )
    model.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=_guid(),
        RelatedObjects=[equipment],
        RelatingClassification=reference,
    )


def _space_stub(model, guid: str, name: str):
    return model.create_entity("IfcSpace", GlobalId=guid, Name=name)


def _contain(model, equipment, space) -> None:
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatedElements=list(equipment),
        RelatingStructure=space,
    )


def _create_arc(path: Path, space_guid: str, suffix: str) -> None:
    model = ifcopenshell.file(schema="IFC4")
    project = model.create_entity("IfcProject", GlobalId=_guid(), Name=f"Synthetic Project {suffix}")
    site = model.create_entity("IfcSite", GlobalId=_guid(), Name=f"Synthetic Site {suffix}")
    building = model.create_entity("IfcBuilding", GlobalId=_guid(), Name=f"Synthetic Building {suffix}")
    storey = model.create_entity(
        "IfcBuildingStorey",
        GlobalId=_guid(),
        Name=f"Synthetic Storey {suffix}",
        Elevation=3.0,
    )
    space = model.create_entity(
        "IfcSpace",
        GlobalId=space_guid,
        Name=f"Synthetic Room {suffix}",
        LongName=f"Synthetic ARC Room {suffix}",
        Description="Public synthetic architectural space",
    )
    for parent, child in (
        (project, site),
        (site, building),
        (building, storey),
        (storey, space),
    ):
        model.create_entity(
            "IfcRelAggregates",
            GlobalId=_guid(),
            RelatingObject=parent,
            RelatedObjects=[child],
        )
    model.write(path)


def create_synthetic_inputs(output_dir: str | Path) -> Dict[str, Any]:
    """Create fully synthetic multi-MEP IFC, multi-ARC IFC, and BMS inputs."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    room_a_guid = _guid()
    room_b_guid = _guid()

    arc_a_path = output / "synthetic_arc_a.ifc"
    arc_b_path = output / "synthetic_arc_b.ifc"
    _create_arc(arc_a_path, room_a_guid, "A")
    _create_arc(arc_b_path, room_b_guid, "B")

    mep_a = ifcopenshell.file(schema="IFC4")
    room_a_stub = _space_stub(mep_a, room_a_guid, "MEP reference to Room A")
    ahu = mep_a.create_entity("IfcUnitaryEquipment", GlobalId=_guid(), Name="Synthetic AHU")
    fcu = mep_a.create_entity("IfcUnitaryEquipment", GlobalId=_guid(), Name="Synthetic FCU")
    _classification(mep_a, ahu, "AHU-1", "Air handling unit")
    _classification(mep_a, fcu, "FCU-1", "Fan coil unit")
    _contain(mep_a, [ahu, fcu], room_a_stub)

    source_port = mep_a.create_entity(
        "IfcDistributionPort",
        GlobalId=_guid(),
        Name="AHU supply",
        FlowDirection="SOURCE",
    )
    sink_port = mep_a.create_entity(
        "IfcDistributionPort",
        GlobalId=_guid(),
        Name="FCU inlet",
        FlowDirection="SINK",
    )
    for equipment, port in ((ahu, source_port), (fcu, sink_port)):
        mep_a.create_entity(
            "IfcRelNests",
            GlobalId=_guid(),
            RelatingObject=equipment,
            RelatedObjects=[port],
        )
    mep_a.create_entity(
        "IfcRelConnectsPorts",
        GlobalId=_guid(),
        RelatingPort=source_port,
        RelatedPort=sink_port,
    )
    mep_a_path = output / "synthetic_mep_a.ifc"
    mep_a.write(mep_a_path)

    mep_b = ifcopenshell.file(schema="IFC4")
    room_b_stub = _space_stub(mep_b, room_b_guid, "MEP reference to Room B")
    pump = mep_b.create_entity("IfcPump", GlobalId=_guid(), Name="Synthetic Pump")
    _classification(mep_b, pump, "CP-1", "Circulator pump")
    _contain(mep_b, [pump], room_b_stub)
    mep_b_path = output / "synthetic_mep_b.ifc"
    mep_b.write(mep_b_path)

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
                {
                    "point_id": "P-3",
                    "name": "pump_status",
                    "unit": "",
                    "bdns_abbreviation": "CP-1",
                },
            ]
        )

    return {
        "mep_ifc": [str(mep_a_path), str(mep_b_path)],
        "arc_ifc": [str(arc_a_path), str(arc_b_path)],
        "points_csv": str(points_path),
        "ahu_guid": str(ahu.GlobalId),
        "fcu_guid": str(fcu.GlobalId),
        "pump_guid": str(pump.GlobalId),
        "room_a_guid": room_a_guid,
        "room_b_guid": room_b_guid,
    }


if __name__ == "__main__":
    paths = create_synthetic_inputs(Path(__file__).resolve().parent / "generated")
    for name, value in paths.items():
        print(f"{name}: {value}")
