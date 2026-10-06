from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

from models import BrickEquipment, IfcAsset


FALLBACK_CLASS = "brick:Equipment"


def _lookup_code(value: Optional[str]) -> str:
    text = (value or "").strip().upper()
    match = re.match(r"^([A-Z]{2,6})(?:\d+)?(?:-|$)", text)
    return match.group(1) if match else text


def load_crosswalk(path: str | Path) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = _lookup_code(row.get("bdns_abbriviation") or row.get("bdns_abbreviation"))
            brick = (row.get("brick_class_candidate") or "").strip()
            if code and brick:
                candidates = [item.strip() for item in brick.split("|") if item.strip()]
                result[code] = {
                    "brick_class": candidates[0] if len(candidates) == 1 else FALLBACK_CLASS,
                    "status": "project-defined" if len(candidates) == 1 else "review_required",
                }
    return result


def map_assets(assets: Iterable[IfcAsset], crosswalk_path: str | Path) -> list[BrickEquipment]:
    crosswalk = load_crosswalk(crosswalk_path)
    result: list[BrickEquipment] = []
    for asset in assets:
        record = crosswalk.get(_lookup_code(asset.bdns_code)) if asset.bdns_code else None
        if asset.bdns_code is None:
            brick_class = FALLBACK_CLASS
            status = "missing_bdns_classification"
            source = None
        elif record is None:
            brick_class = FALLBACK_CLASS
            status = "review_required"
            source = "IfcClassificationReference"
        else:
            brick_class = record["brick_class"]
            status = record["status"]
            source = "IfcClassificationReference + project BDNS-to-Brick crosswalk"

        label = asset.name or asset.bdns_code or f"equipment_{asset.ifc_guid}"
        result.append(
            BrickEquipment(
                ifc_guid=asset.ifc_guid,
                brick_class=brick_class,
                label=label,
                bdns_code=asset.bdns_code,
                raw_ifc_class=asset.raw_ifc_class,
                mapping_status=status,
                mapping_source=source,
                classification_name=asset.classification_name,
            )
        )
    return result

