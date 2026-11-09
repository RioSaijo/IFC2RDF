from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from rdflib import Graph

from models import BrickEquipment, Relation


def build_validation_report(
    graph: Graph,
    equipment: Iterable[BrickEquipment],
    relations: Iterable[Relation],
) -> dict:
    equipment = list(equipment)
    relations = list(relations)
    review_mappings = [item.ifc_guid for item in equipment if item.mapping_status != "project-defined"]
    review_relations = [
        {"subject": item.subject_guid, "predicate": item.predicate, "object": item.object_guid}
        for item in relations
        if item.review_required
    ]
    return {
        "conforms": not review_mappings and not review_relations,
        "triple_count": len(graph),
        "review_required_mappings": review_mappings,
        "review_required_relations": review_relations,
        "note": "conforms is a project-level completeness check; full Brick SHACL validation is not claimed.",
    }


def write_json(value: dict, path: str | Path) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)
