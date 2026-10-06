from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from rdflib import Graph

from models import BrickEquipment, PointLink, Relation


def build_validation_report(
    graph: Graph,
    equipment: Iterable[BrickEquipment],
    relations: Iterable[Relation],
    point_links: Iterable[PointLink],
    unresolved_points: Iterable[str],
) -> dict:
    equipment = list(equipment)
    relations = list(relations)
    point_links = list(point_links)
    unresolved_points = list(unresolved_points)
    review_mappings = [item.ifc_guid for item in equipment if item.mapping_status != "project-defined"]
    review_relations = [
        {"subject": item.subject_guid, "predicate": item.predicate, "object": item.object_guid}
        for item in relations
        if item.review_required
    ]
    review_point_links = [item.point_iri for item in point_links if item.review_required]
    return {
        "conforms": not review_mappings and not review_relations and not review_point_links and not unresolved_points,
        "triple_count": len(graph),
        "review_required_mappings": review_mappings,
        "review_required_relations": review_relations,
        "review_required_point_links": review_point_links,
        "unresolved_points": unresolved_points,
        "note": "conforms is a project-level completeness check; full Brick SHACL validation is not claimed.",
    }


def write_json(value: dict, path: str | Path) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)

