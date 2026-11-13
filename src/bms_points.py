"""Stage 2: BMS point list (BACnet-style CSV) -> Brick point RDF.

The point list is read on its own, without the IFC model. A BMS point list
carries no Brick class, so each point's class is assigned here from its name,
description, BACnet object type, unit, and equipment (src/point_classes.py).
Only Sensor and Setpoint points are in scope; other points are listed in
point_classification.csv and left out of the RDF. Equipment and space
references are kept as literals (project:equipmentRef, project:spaceRef) and
resolved against the IFC-derived RDF in stage 3 (match.py).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from mapping import load_crosswalk, lookup_code
from point_classes import PointClassification, classify_point, medium_words
from rdf import BRICK, QUDT

DEFAULT_CROSSWALK = Path(__file__).resolve().parent.parent / "data" / "resources" / "BDNS mapping partial.csv"

POINT_LIST_COLUMNS = [
    "point_id",
    "object_name",
    "description",
    "object_type",
    "device_instance",
    "object_instance",
    "units",
    "equipment_ref",
    "space_ref",
]
REQUIRED_COLUMNS = set(POINT_LIST_COLUMNS)

OBJECT_TYPES = {"AI", "AO", "AV", "BI", "BO", "BV", "MI", "MO", "MV"}
BINARY_OBJECT_TYPES = {"BI", "BO", "BV"}

UNITS = {
    "degC": QUDT.DEG_C,
    "Pa": QUDT.PA,
    "m3/s": QUDT["M3-PER-SEC"],
    "ppm": QUDT.PPM,
    "%RH": QUDT.PERCENT_RH,
    "rpm": QUDT["REV-PER-MIN"],
    "%": QUDT.PERCENT,
}


@dataclass(frozen=True)
class PointRecord:
    point_id: str
    object_name: str
    description: str
    object_type: str
    device_instance: Optional[int]
    object_instance: Optional[int]
    units: str
    equipment_ref: str
    space_ref: str
    classification: PointClassification
    issues: Tuple[str, ...] = ()


@dataclass
class PointListResult:
    points: List[PointRecord]
    issues: List[Dict[str, str]] = field(default_factory=list)


def load_point_classes(path: str | Path) -> Tuple[List[str], List[str]]:
    """Brick Sensor and Setpoint class local names the project can verify."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    def local(key: str) -> List[str]:
        return sorted(iri.split("#", 1)[1] for iri in data.get(key, []))

    return local("sensor_classes"), local("setpoint_classes")


def _int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def read_point_list(
    path: str | Path,
    sensor_classes: List[str],
    setpoint_classes: List[str],
    crosswalk: Dict[str, Dict[str, str]],
) -> PointListResult:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Point list is missing columns: {sorted(missing)}")
        rows = list(reader)

    result = PointListResult(points=[])
    seen: set[str] = set()
    for row in rows:
        get = lambda key: (row.get(key) or "").strip()  # noqa: E731
        point_id = get("point_id")
        issues: List[str] = []
        if not point_id:
            result.issues.append({"point_id": "", "issue": "empty point_id"})
            continue
        if point_id in seen:
            issues.append("duplicate point_id")
        seen.add(point_id)

        object_type = get("object_type").upper()
        if object_type not in OBJECT_TYPES:
            issues.append(f"unknown BACnet object_type {object_type!r}")
        device, instance = _int(get("device_instance")), _int(get("object_instance"))
        if device is None or instance is None:
            issues.append("device_instance and object_instance must be integers")

        units = get("units")
        if units and units not in UNITS:
            issues.append(f"unknown unit {units!r}")
        if object_type in BINARY_OBJECT_TYPES and units:
            issues.append("binary object has a unit")

        equipment_ref, space_ref = get("equipment_ref"), get("space_ref")
        if bool(equipment_ref) == bool(space_ref):
            issues.append("exactly one of equipment_ref and space_ref is required")

        # The equipment's Brick class comes from the project crosswalk via its
        # BDNS abbreviation (AHU-00001 -> AHU), not from the IFC model.
        equipment_class = (crosswalk.get(lookup_code(equipment_ref)) or {}).get("brick_class") if equipment_ref else None
        classification = classify_point(
            get("object_name"), get("description"), object_type, units,
            medium_words(equipment_class, is_space=bool(space_ref) and not equipment_ref),
            sensor_classes, setpoint_classes,
        )
        if classification.status == "unclassified":
            issues.append(f"unclassified: {classification.reason}")

        record = PointRecord(
            point_id=point_id,
            object_name=get("object_name"),
            description=get("description"),
            object_type=object_type,
            device_instance=device,
            object_instance=instance,
            units=units,
            equipment_ref=equipment_ref,
            space_ref=space_ref,
            classification=classification,
            issues=tuple(issues),
        )
        result.points.append(record)
        result.issues.extend({"point_id": point_id, "issue": issue} for issue in issues)

    bacnet_ids = {}
    for item in result.points:
        key = (item.device_instance, item.object_type, item.object_instance)
        if None not in key and key in bacnet_ids:
            result.issues.append({"point_id": item.point_id, "issue": f"BACnet object {key} also used by {bacnet_ids[key]}"})
        bacnet_ids.setdefault(key, item.point_id)
    return result


def point_iri(base_ns: str, point_id: str) -> URIRef:
    return URIRef(f"{base_ns}point_{re.sub(r'[^A-Za-z0-9_$-]', '_', point_id)}")


def build_point_graph(points: Iterable[PointRecord], base_ns: str) -> Graph:
    graph = Graph()
    project = Namespace(base_ns)
    for prefix, ns in (("brick", BRICK), ("project", project), ("qudt-unit", QUDT)):
        graph.bind(prefix, ns)
    for item in points:
        status = item.classification.status
        if status == "out_of_scope":
            continue
        subject = point_iri(base_ns, item.point_id)
        # An unclassified point stays a plain brick:Point; it is never guessed.
        graph.add((subject, RDF.type, BRICK[item.classification.brick_class] if status == "classified" else BRICK.Point))
        graph.add((subject, project.classificationStatus, Literal(status)))
        if status != "classified":
            graph.add((subject, project.classificationReason, Literal(item.classification.reason)))
        graph.add((subject, RDFS.label, Literal(item.object_name or item.point_id)))
        graph.add((subject, project.pointId, Literal(item.point_id)))
        if item.description:
            graph.add((subject, project.description, Literal(item.description)))
        graph.add((subject, project.bacnetObjectType, Literal(item.object_type)))
        if item.device_instance is not None:
            graph.add((subject, project.bacnetDeviceInstance, Literal(item.device_instance, datatype=XSD.integer)))
        if item.object_instance is not None:
            graph.add((subject, project.bacnetObjectInstance, Literal(item.object_instance, datatype=XSD.integer)))
        if item.units in UNITS:
            graph.add((subject, BRICK.hasUnit, UNITS[item.units]))
        if item.equipment_ref:
            graph.add((subject, project.equipmentRef, Literal(item.equipment_ref)))
        if item.space_ref:
            graph.add((subject, project.spaceRef, Literal(item.space_ref)))
    return graph


def write_classification(points: Iterable[PointRecord], path: Path) -> None:
    columns = ["point_id", "object_name", "object_type", "units", "equipment_ref", "space_ref",
               "status", "kind", "brick_class", "words", "candidates", "reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in points:
            c = item.classification
            writer.writerow({
                "point_id": item.point_id, "object_name": item.object_name, "object_type": item.object_type,
                "units": item.units, "equipment_ref": item.equipment_ref, "space_ref": item.space_ref,
                "status": c.status, "kind": c.kind, "brick_class": c.brick_class, "words": " ".join(c.words),
                "candidates": " ".join(c.candidates), "reason": c.reason,
            })


def run_points_stage(
    point_list_csv: str | Path,
    point_classes_json: str | Path,
    output_dir: str | Path,
    base_ns: str,
    mapping_csv: str | Path = DEFAULT_CROSSWALK,
) -> Dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sensors, setpoints = load_point_classes(point_classes_json)
    result = read_point_list(point_list_csv, sensors, setpoints, load_crosswalk(mapping_csv))
    graph = build_point_graph(result.points, base_ns)
    ttl = output / "points_brick.ttl"
    graph.serialize(destination=str(ttl), format="turtle")
    issues_csv = output / "point_list_issues.csv"
    with issues_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["point_id", "issue"])
        writer.writeheader()
        writer.writerows(result.issues)
    classification_csv = output / "point_classification.csv"
    write_classification(result.points, classification_csv)
    statuses: Dict[str, int] = {}
    for item in result.points:
        statuses[item.classification.status] = statuses.get(item.classification.status, 0) + 1
    classes = sorted({p.classification.brick_class for p in result.points if p.classification.brick_class})
    summary = {
        "point_list": str(Path(point_list_csv).resolve()),
        "points": len(result.points),
        "classification": statuses,
        "classes": {name: sum(p.classification.brick_class == name for p in result.points) for name in classes},
        "equipment_points": sum(bool(p.equipment_ref) for p in result.points),
        "space_points": sum(bool(p.space_ref) for p in result.points),
        "issue_count": len(result.issues),
        "triple_count": len(graph),
        "outputs": {"ttl": str(ttl), "classification": str(classification_csv), "issues": str(issues_csv)},
    }
    (output / "points_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
