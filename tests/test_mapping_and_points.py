from pathlib import Path
import csv
import json
import sys

from rdflib.namespace import RDF


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

from mapping import load_crosswalk, map_assets
from models import IfcAsset, Relation
from rdf import BOT, BRICK, build_graph, equipment_iri


def test_ifc_guid_dollar_and_underscore_produce_distinct_iris():
    assert equipment_iri("https://example.org/#", "A$B") != equipment_iri(
        "https://example.org/#", "A_B"
    )


def test_project_crosswalk_maps_supply_grille_to_air_diffuser():
    crosswalk = PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv"
    equipment = map_assets(
        [
            IfcAsset(
                "sg-guid",
                "SG-00001",
                "IfcFlowTerminal",
                "SG",
                "BDNS",
                1,
            )
        ],
        crosswalk,
    )

    assert equipment[0].brick_class == "brick:Air_Diffuser"
    assert equipment[0].mapping_status == "project-defined"
    graph = build_graph([], equipment, [], "https://example.org/#")
    assert (
        equipment_iri("https://example.org/#", "sg-guid"),
        RDF.type,
        BRICK.Air_Diffuser,
    ) in graph


def test_project_crosswalk_uses_only_brick_144_equipment_classes():
    resources = PROJECT_ROOT / "data" / "resources"
    allowed = set(
        json.loads((resources / "brick_1.4.4_equipment_classes.json").read_text(encoding="utf-8"))[
            "equipment_classes"
        ]
    )
    with (resources / "BDNS mapping partial.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    invalid = [
        (row["bdns_abbreviation"], row["brick_class_candidate"])
        for row in rows
        if row["mapping_status"] == "mapped"
        and row["brick_class_candidate"].startswith("brick:")
        and row["brick_class_candidate"].split(":", 1)[1] not in allowed
    ]
    assert invalid == []


def test_project_crosswalk_reviewed_rows_are_consistent():
    crosswalk = PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv"
    with crosswalk.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    reviewed = [row for row in rows if row["mapping_method"].startswith("brick144_")]

    unreviewed = [
        row["bdns_abbreviation"]
        for row in rows
        if not row["mapping_method"].startswith(("brick144_", "bdns_tag_bot_"))
    ]
    assert unreviewed == []
    assert reviewed
    for row in reviewed:
        no_match = row["mapping_method"] == "brick144_no_match"
        assert (row["brick_class_candidate"] == "tbd") == no_match, row["bdns_abbreviation"]
        assert row["mapping_status"] == ("tbd" if no_match else "mapped"), row["bdns_abbreviation"]
        assert row["mapping_rationale"].strip(), row["bdns_abbreviation"]


def test_project_crosswalk_maps_motion_sensor_as_equipment_not_point():
    crosswalk = PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv"
    equipment = map_assets(
        [IfcAsset("mos-guid", "MOS-00001", "IfcDistributionControlElement", "MOS", "BDNS", 1)],
        crosswalk,
    )

    assert equipment[0].brick_class == "brick:Occupancy_Sensor_Equipment"


def test_explicit_classification_drives_mapping(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text(
        "bdns_abbriviation,bdns_tag,raw_ifc_class,brick_class_candidate\n"
        "AHU,air handling unit,IfcUnitaryEquipment,brick:Air_Handling_Unit\n",
        encoding="utf-8",
    )
    assets = [
        IfcAsset("guid-1", "A descriptive name", "IfcUnitaryEquipment", "AHU-1", "BDNS", 42),
        IfcAsset("guid-2", "AHU-2", "IfcUnitaryEquipment"),
    ]
    mapped = map_assets(assets, crosswalk)
    assert len(mapped) == 1
    assert mapped[0].brick_class == "brick:Air_Handling_Unit"
    assert mapped[0].mapping_source.startswith("IfcClassificationReference")


def test_crosswalk_rejects_non_brick_candidate(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text(
        "bdns_abbreviation,brick_class_candidate\n"
        "DR,rec:Door\n",
        encoding="utf-8",
    )
    mapped = map_assets(
        [IfcAsset("guid-1", "Door", "IfcDoor", "DR-1", "BDNS", 1)],
        crosswalk,
    )
    assert mapped[0].brick_class is None
    assert mapped[0].mapping_status == "tbd"


def test_crosswalk_accepts_official_bot_spatial_class(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text(
        "bdns_abbreviation,bdns_tag,brick_class_candidate\n"
        "SPACE,space,bot:Space\n"
        "ZONE,zone,bot:Zone\n",
        encoding="utf-8",
    )
    mapped = map_assets(
        [
            IfcAsset("space-guid", "Room 101", "IfcSpace", "SPACE-1", "BDNS", 1),
            IfcAsset("zone-guid", "Thermal zone", "IfcZone", "ZONE-1", "BDNS", 2),
        ],
        crosswalk,
    )
    assert [item.brick_class for item in mapped] == ["bot:Space", "bot:Zone"]
    assert all(item.mapping_status == "project-defined" for item in mapped)
    graph = build_graph([], mapped, [], "https://example.org/#")
    assert (
        equipment_iri("https://example.org/#", "space-guid"),
        RDF.type,
        BOT.Space,
    ) in graph
    assert (
        equipment_iri("https://example.org/#", "zone-guid"),
        RDF.type,
        BOT.Zone,
    ) in graph


def test_conflicting_normalized_crosswalk_rows_do_not_overwrite(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text(
        "bdns_abbreviation,brick_class_candidate\n"
        "AHU,brick:Air_Handling_Unit\n"
        "AHU-1,brick:Fan_Coil_Unit\n",
        encoding="utf-8",
    )
    record = load_crosswalk(crosswalk)["AHU"]
    assert record == {
        "brick_class": None,
        "status": "tbd",
    }


def test_crosswalk_requires_mapping_columns(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text("code,class\nAHU,brick:Air_Handling_Unit\n", encoding="utf-8")
    try:
        load_crosswalk(crosswalk)
    except ValueError as exc:
        assert "brick_class_candidate" in str(exc)
    else:
        raise AssertionError("Expected invalid crosswalk columns to be rejected")


def test_tbd_equipment_and_dependent_links_are_omitted_from_rdf(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text(
        "bdns_abbreviation,brick_class_candidate\n"
        "DR,tbd\n"
        "AHU,brick:Air_Handling_Unit\n",
        encoding="utf-8",
    )
    equipment = map_assets(
        [
            IfcAsset("guid-1", "Door", "IfcDoor", "DR-1", "BDNS", 1),
            IfcAsset("guid-2", "AHU", "IfcUnitaryEquipment", "AHU-1", "BDNS", 2),
        ],
        crosswalk,
    )
    graph = build_graph(
        spatial=[],
        equipment=equipment,
        relations=[
            Relation(
                subject_guid="guid-2",
                predicate="brick:feeds",
                object_guid="guid-1",
                source="test",
                method="explicit",
            )
        ],
        base_ns="https://example.org/#",
    )
    assert equipment[0].mapping_status == "tbd"
    assert equipment[0].brick_class is None
    assert not list(graph.triples((equipment_iri("https://example.org/#", "guid-1"), None, None)))
    assert not list(
        graph.triples(
            (
                equipment_iri("https://example.org/#", "guid-2"),
                BRICK.feeds,
                None,
            )
        )
    )
