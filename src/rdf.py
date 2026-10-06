from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from models import BrickEquipment, BrickPoint, PointLink, Relation, SpatialElement


BRICK = Namespace("https://brickschema.org/schema/Brick#")
BOT = Namespace("https://w3id.org/bot#")
QUDT = Namespace("http://qudt.org/vocab/unit/")


def _safe_local(value: str) -> str:
    local = re.sub(r"[^A-Za-z0-9_\-]", "_", value)
    return local if re.match(r"^[A-Za-z_]", local) else f"X_{local}"


def equipment_iri(base_ns: str, guid: str) -> URIRef:
    return URIRef(f"{base_ns}equipment_{_safe_local(guid)}")


def spatial_iri(base_ns: str, guid: str) -> URIRef:
    return URIRef(f"{base_ns}spatial_{_safe_local(guid)}")


def _term(value: str) -> URIRef:
    if value.startswith("brick:"):
        return BRICK[value.split(":", 1)[1]]
    if value.startswith("bot:"):
        return BOT[value.split(":", 1)[1]]
    return URIRef(value)


def build_graph(
    spatial: Iterable[SpatialElement],
    equipment: Iterable[BrickEquipment],
    points: Iterable[BrickPoint],
    relations: Iterable[Relation],
    point_links: Iterable[PointLink],
    base_ns: str,
) -> Graph:
    graph = Graph()
    project = Namespace(base_ns)
    for prefix, ns in (("brick", BRICK), ("bot", BOT), ("project", project), ("qudt-unit", QUDT)):
        graph.bind(prefix, ns)

    spatial_types = {
        "IfcSite": BOT.Site,
        "IfcBuilding": BOT.Building,
        "IfcBuildingStorey": BOT.Storey,
        "IfcSpace": BOT.Space,
    }
    spatial_by_guid = {item.ifc_guid: item for item in spatial}
    for item in spatial_by_guid.values():
        subject = spatial_iri(base_ns, item.ifc_guid)
        graph.add((subject, RDF.type, spatial_types[item.raw_ifc_class]))
        graph.add((subject, project.ifcGlobalId, Literal(item.ifc_guid)))
        if item.name:
            graph.add((subject, RDFS.label, Literal(item.name)))
        if item.parent_guid and item.parent_guid in spatial_by_guid:
            graph.add((spatial_iri(base_ns, item.parent_guid), BRICK.hasPart, subject))

    equipment_by_guid = {item.ifc_guid: item for item in equipment}
    for item in equipment_by_guid.values():
        subject = equipment_iri(base_ns, item.ifc_guid)
        graph.add((subject, RDF.type, _term(item.brick_class)))
        graph.add((subject, RDFS.label, Literal(item.label)))
        graph.add((subject, project.ifcGlobalId, Literal(item.ifc_guid)))
        graph.add((subject, project.ifcClass, Literal(item.raw_ifc_class)))
        graph.add((subject, project.mappingStatus, Literal(item.mapping_status)))
        if item.bdns_code:
            graph.add((subject, project.bdnsClassificationCode, Literal(item.bdns_code)))
        if item.classification_name:
            graph.add((subject, project.classificationSystem, Literal(item.classification_name)))

    for item in points:
        subject = URIRef(item.iri)
        graph.add((subject, RDF.type, _term(item.brick_class)))
        graph.add((subject, RDFS.label, Literal(item.name)))

    for item in relations:
        if item.subject_guid not in equipment_by_guid:
            continue
        subject = equipment_iri(base_ns, item.subject_guid)
        target = equipment_iri(base_ns, item.object_guid) if item.object_guid in equipment_by_guid else spatial_iri(base_ns, item.object_guid)
        graph.add((subject, _term(item.predicate), target))

    for item in point_links:
        if item.equipment_guid in equipment_by_guid:
            graph.add((equipment_iri(base_ns, item.equipment_guid), BRICK.hasPoint, URIRef(item.point_iri)))
    return graph


def write_outputs(
    graph: Graph,
    equipment: Iterable[BrickEquipment],
    relations: Iterable[Relation],
    point_links: Iterable[PointLink],
    output_dir: str | Path,
) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ttl_path = output / "building_brick.ttl"
    provenance_path = output / "provenance.csv"
    graph.serialize(destination=str(ttl_path), format="turtle")

    with provenance_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["record_type", "subject", "predicate_or_class", "object", "source", "method", "confidence", "review_required", "evidence"])
        for item in equipment:
            writer.writerow(["mapping", item.ifc_guid, item.brick_class, "", item.mapping_source or "", item.mapping_status, 1.0 if item.bdns_code else 0.0, item.mapping_status != "project-defined", ""])
        for item in relations:
            writer.writerow(["relation", item.subject_guid, item.predicate, item.object_guid, item.source, item.method, item.confidence, item.review_required, json.dumps(item.evidence, ensure_ascii=False)])
        for item in point_links:
            writer.writerow(["point_link", item.equipment_guid, "brick:hasPoint", item.point_iri, item.source, item.method, 1.0 if not item.review_required else 0.5, item.review_required, ""])
    return {"ttl": str(ttl_path), "provenance": str(provenance_path)}
