from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple

from models import BrickEquipment, BrickPoint, PointLink


def _clean(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return None if not text or text.lower() in {"none", "nan", "null"} else text


def _safe_local(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_\-]", "_", value)
    return value if re.match(r"^[A-Za-z_]", value) else f"X_{value}"


def _point_class(name: str) -> str:
    text = name.lower()
    if "co2" in text:
        return "brick:CO2_Sensor"
    if "temp" in text:
        return "brick:Temperature_Sensor"
    if "humidity" in text or "_rh" in text:
        return "brick:Humidity_Sensor"
    if "flow" in text:
        return "brick:Flow_Sensor"
    if "pressure" in text or "static" in text:
        return "brick:Pressure_Sensor"
    if "status" in text:
        return "brick:Status_Sensor"
    return "brick:Sensor"


def load_and_link_points(
    csv_path: str | Path,
    equipment: Iterable[BrickEquipment],
    base_ns: str,
) -> Tuple[list[BrickPoint], list[PointLink], list[str]]:
    by_bdns: dict[str, list[BrickEquipment]] = {}
    by_name: dict[str, list[BrickEquipment]] = {}
    for item in equipment:
        if item.bdns_code:
            by_bdns.setdefault(item.bdns_code.upper(), []).append(item)
        if item.label:
            by_name.setdefault(item.label.upper(), []).append(item)
    points: list[BrickPoint] = []
    links: list[PointLink] = []
    unresolved: list[str] = []

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"point_id", "name", "unit", "bdns_abbreviation"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing point CSV columns: {sorted(missing)}")
        for row in reader:
            point_id = _clean(row.get("point_id"))
            if not point_id:
                continue
            name = _clean(row.get("name")) or f"point_{point_id}"
            equipment_ref = _clean(row.get("bdns_abbreviation"))
            point = BrickPoint(
                iri=f"{base_ns}{_safe_local('Point_' + point_id)}",
                name=name,
                brick_class=_point_class(name),
                equipment_ref=equipment_ref,
                unit=_clean(row.get("unit")),
            )
            points.append(point)
            if not equipment_ref:
                unresolved.append(point_id)
                continue

            # Classification values are authoritative. Name matching supports
            # legacy BMS exports only and is explicitly marked for review.
            candidates = by_bdns.get(equipment_ref.upper(), [])
            target = candidates[0] if len(candidates) == 1 else None
            method = "explicit_bdns_identifier"
            review = False
            if not candidates:
                name_candidates = by_name.get(equipment_ref.upper(), [])
                target = name_candidates[0] if len(name_candidates) == 1 else None
                method = "legacy_name_match"
                review = True
            if target is None:
                unresolved.append(point_id)
            else:
                links.append(
                    PointLink(
                        equipment_guid=target.ifc_guid,
                        point_iri=point.iri,
                        source="BMS point CSV",
                        method=method,
                        review_required=review,
                    )
                )
    return points, links, unresolved

