"""Convert the legacy research point list to the BACnet-style point list format.

Legacy columns: point_id, name, unit, bdns_abbreviation[, space_id]
New columns:    see bms_points.POINT_LIST_COLUMNS

Usage:
    python tools/convert_legacy_point_list.py <legacy.csv> <out.csv>

A BMS point list carries no Brick class; stage 2 assigns it (see
src/point_classes.py). The legacy file has no BACnet data either, so each
name pattern below states its BACnet object type and a readable name, and
device and object instances are synthetic numbering, not values read from a
BMS.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from bms_points import POINT_LIST_COLUMNS  # noqa: E402

# name pattern (without numeric suffix) -> (point ID suffix, BACnet object type, readable name)
RULES = {
    "ahu_supply_temp": ("SAT", "AI", "Supply Air Temperature"),
    "ahu_supply_sp": ("SASP", "AI", "Supply Air Static Pressure"),
    "ahu_supply_flow": ("SAF", "AI", "Supply Air Flow"),
    "ahu_return_temp": ("RAT", "AI", "Return Air Temperature"),
    "ahu_mixed_temp": ("MAT", "AI", "Mixed Air Temperature"),
    "ahu_fan_speed": ("FSPD", "AI", "Fan Speed"),
    "vav_zone_flow": ("SAF", "AI", "Zone Air Flow"),
    "vav_zone_temp": ("ZAT", "AI", "Zone Air Temperature"),
    "vav_zone_co2": ("ZCO2", "AI", "Zone CO2"),
    "vavs_zone_flow": ("SAF", "AI", "Zone Air Flow"),
    "vavs_zone_temp": ("ZAT", "AI", "Zone Air Temperature"),
    "vavs_zone_co2": ("ZCO2", "AI", "Zone CO2"),
    "fcu_zone_temp": ("ZAT", "AI", "Zone Air Temperature"),
    "fcu_fan_status": ("FST", "BI", "Fan Status"),
    "airterm_flow": ("AF", "AI", "Air Flow"),
    "room_temp": ("ZAT", "AI", "Room Temperature"),
    "room_rh": ("ZRH", "AI", "Room Humidity"),
    "room_co2": ("ZCO2", "AI", "Room CO2"),
    "room_occupancy": ("OCC", "BI", "Room Occupancy"),
}

# "binary" is a state, not a unit.
UNITS = {"degC": "degC", "Pa": "Pa", "m3/s": "m3/s", "ppm": "ppm", "%RH": "%RH", "rpm": "rpm", "binary": ""}


def _pattern(name: str) -> str:
    # room_temp_m51_01_02 -> room_temp ; ahu_supply_temp_1 -> ahu_supply_temp
    name = re.sub(r"_m\d+_\d+_\d+$", "", name)
    return re.sub(r"_\d+$", "", name)


def convert(legacy_path: Path, out_path: Path) -> int:
    with legacy_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    devices: dict[str, int] = {}
    next_object: dict[int, int] = {}
    out_rows = []
    for row in rows:
        pattern = _pattern(row["name"])
        if pattern not in RULES:
            raise ValueError(f"No rule for point name {row['name']!r}")
        suffix, object_type, readable = RULES[pattern]
        equipment_ref = (row.get("bdns_abbreviation") or "").strip()
        space_ref = (row.get("space_id") or "").strip()
        owner = equipment_ref or f"SPACE-{space_ref}"
        device = devices.setdefault(owner, 1000 + len(devices) + 1)
        next_object[device] = next_object.get(device, 0) + 1
        label_owner = equipment_ref or f"Room {space_ref}"
        out_rows.append(
            {
                "point_id": f"{owner}_{suffix}",
                "object_name": f"{label_owner} {readable}",
                "description": f"{readable} of {label_owner}",
                "object_type": object_type,
                "device_instance": device,
                "object_instance": next_object[device],
                "units": UNITS[row["unit"]],
                "equipment_ref": equipment_ref,
                "space_ref": space_ref,
                "legacy_point_id": row["point_id"],
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINT_LIST_COLUMNS + ["legacy_point_id"])
        writer.writeheader()
        writer.writerows(out_rows)
    return len(out_rows)


if __name__ == "__main__":
    count = convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"wrote {count} points to {sys.argv[2]}")
