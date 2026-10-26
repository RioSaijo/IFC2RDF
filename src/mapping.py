from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

from models import BrickEquipment, IfcAsset


def _lookup_code(value: Optional[str]) -> str:
    text = (value or "").strip().upper()
    match = re.match(r"^([A-Z]{2,6})(?:\d+)?(?:-|$)", text)
    return match.group(1) if match else text


_BOT_CLASSES = {
    "bot:Zone",
    "bot:Site",
    "bot:Building",
    "bot:Storey",
    "bot:Space",
    "bot:Element",
    "bot:Interface",
}


def _valid_target_class(value: str) -> bool:
    return bool(re.fullmatch(r"brick:[A-Za-z_][A-Za-z0-9_]*", value)) or value in _BOT_CLASSES


def load_crosswalk(path: str | Path) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        code_column = (
            "bdns_abbreviation"
            if "bdns_abbreviation" in fields
            else "bdns_abbriviation"
            if "bdns_abbriviation" in fields
            else None
        )
        if code_column is None or "brick_class_candidate" not in fields:
            raise ValueError(
                "Mapping CSV requires bdns_abbreviation (or legacy "
                "bdns_abbriviation) and brick_class_candidate columns"
            )

        for row in reader:
            code = _lookup_code(row.get(code_column))
            brick = (row.get("brick_class_candidate") or "").strip()
            if not code:
                continue

            candidates = [item.strip() for item in brick.split("|") if item.strip()]
            is_unique_target_class = (
                len(candidates) == 1 and _valid_target_class(candidates[0])
            )
            record = {
                "brick_class": candidates[0] if is_unique_target_class else None,
                "status": "project-defined" if is_unique_target_class else "tbd",
            }
            previous = result.get(code)
            if previous is not None and previous != record:
                result[code] = {
                    "brick_class": None,
                    "status": "tbd",
                }
            elif previous is None:
                result[code] = record
    return result


def map_assets(assets: Iterable[IfcAsset], crosswalk_path: str | Path) -> list[BrickEquipment]:
    crosswalk = load_crosswalk(crosswalk_path)
    result: list[BrickEquipment] = []
    for asset in assets:
        # The crosswalk maps explicit BDNS tags to ontology classes. It is not
        # an IFC-class or name-based equipment classifier.
        if not asset.bdns_code:
            continue

        record = crosswalk.get(_lookup_code(asset.bdns_code))
        if record is None:
            brick_class = None
            status = "tbd"
            source = "IfcClassificationReference"
        else:
            brick_class = record["brick_class"]
            status = record["status"]
            source = "IfcClassificationReference + project BDNS-to-ontology crosswalk"

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
                source_path=asset.source_path,
            )
        )
    return result


def write_mapping_results(
    equipment: Iterable[BrickEquipment],
    output_path: str | Path,
) -> str:
    """Write one auditable mapping row for every extracted IFC asset."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ifc_global_id",
                "label",
                "raw_ifc_class",
                "bdns_code",
                "classification_name",
                "target_ontology_class",
                "mapping_status",
                "mapping_source",
                "source_ifc",
            ]
        )
        for item in equipment:
            writer.writerow(
                [
                    item.ifc_guid,
                    item.label,
                    item.raw_ifc_class,
                    item.bdns_code or "",
                    item.classification_name or "",
                    item.brick_class or "",
                    item.mapping_status,
                    item.mapping_source or "",
                    item.source_path or "",
                ]
            )
    return str(destination)

