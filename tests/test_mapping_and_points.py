from pathlib import Path
import sys


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from mapping import map_assets
from models import IfcAsset
from points import load_and_link_points


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
    assert mapped[0].brick_class == "brick:Air_Handling_Unit"
    assert mapped[0].mapping_source.startswith("IfcClassificationReference")
    assert mapped[1].brick_class == "brick:Equipment"
    assert mapped[1].mapping_status == "missing_bdns_classification"


def test_bms_link_prefers_bdns_classification(tmp_path):
    crosswalk = tmp_path / "mapping.csv"
    crosswalk.write_text(
        "bdns_abbriviation,bdns_tag,raw_ifc_class,brick_class_candidate\n"
        "AHU,air handling unit,IfcUnitaryEquipment,brick:Air_Handling_Unit\n",
        encoding="utf-8",
    )
    equipment = map_assets(
        [IfcAsset("guid-1", "Not the identifier", "IfcUnitaryEquipment", "AHU-1", "BDNS", 42)],
        crosswalk,
    )
    points_csv = tmp_path / "points.csv"
    points_csv.write_text(
        "point_id,name,unit,bdns_abbreviation\n"
        "1,ahu_supply_temp,degC,AHU-1\n",
        encoding="utf-8",
    )
    points, links, unresolved = load_and_link_points(points_csv, equipment, "https://example.org/#")
    assert len(points) == 1
    assert links[0].equipment_guid == "guid-1"
    assert links[0].method == "explicit_bdns_identifier"
    assert not links[0].review_required
    assert unresolved == []
