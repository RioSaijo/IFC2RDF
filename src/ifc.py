from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import ifcopenshell

from models import (
    ConnectionInference,
    ExtractionResult,
    IfcAsset,
    IfcBundle,
    PortConnection,
    Relation,
    SpatialElement,
)


SPATIAL_CLASSES = ("IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace")


def _by_type(model, name: str):
    try:
        return model.by_type(name)
    except RuntimeError:
        return []


def _guid(obj) -> Optional[str]:
    value = getattr(obj, "GlobalId", None)
    return str(value) if value else None


def _name(obj) -> Optional[str]:
    value = getattr(obj, "Name", None)
    return str(value).strip() if value else None


def _entity_id(obj) -> Optional[int]:
    try:
        return int(obj.id())
    except Exception:
        return None


def load_ifc(path: str | Path) -> IfcBundle:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"IFC file not found: {source}")
    try:
        model = ifcopenshell.open(str(source))
    except Exception as exc:
        raise RuntimeError(f"Could not open IFC file: {source}") from exc
    schema = str(getattr(model, "schema", None) or "UNKNOWN").upper()
    return IfcBundle(schema=schema, source_path=str(source.resolve()), model=model)


def _classification_name(classification) -> str:
    return str(getattr(classification, "Name", None) or "").strip()


def _root_classification(reference):
    current = getattr(reference, "ReferencedSource", None)
    visited: Set[int] = set()
    while current is not None:
        identity = id(current)
        if identity in visited:
            return None
        visited.add(identity)
        if hasattr(current, "is_a") and current.is_a("IfcClassification"):
            return current
        current = getattr(current, "ReferencedSource", None)
    return None


def _reference_code(reference) -> Optional[str]:
    for attr in ("Identification", "ItemReference", "Name"):
        value = getattr(reference, attr, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _is_bdns(classification) -> bool:
    return _classification_name(classification).upper() == "BDNS"


def _spatial_elements(model, source_path: Optional[str] = None) -> List[SpatialElement]:
    parent_by_guid: Dict[str, str] = {}
    for rel in _by_type(model, "IfcRelAggregates"):
        parent_guid = _guid(getattr(rel, "RelatingObject", None))
        if not parent_guid:
            continue
        for child in getattr(rel, "RelatedObjects", None) or []:
            child_guid = _guid(child)
            if child_guid:
                parent_by_guid[child_guid] = parent_guid

    result: List[SpatialElement] = []
    for ifc_class in SPATIAL_CLASSES:
        for obj in _by_type(model, ifc_class):
            guid = _guid(obj)
            if guid:
                properties: Dict[str, Any] = {}
                for attr in ("LongName", "Description", "ObjectType", "CompositionType"):
                    value = getattr(obj, attr, None)
                    if value is not None and str(value).strip():
                        properties[attr] = str(value).strip()
                elevation = getattr(obj, "Elevation", None)
                if elevation is not None:
                    try:
                        properties["Elevation"] = float(elevation)
                    except (TypeError, ValueError):
                        properties["Elevation"] = str(elevation)
                result.append(
                    SpatialElement(
                        ifc_guid=guid,
                        name=_name(obj),
                        raw_ifc_class=ifc_class,
                        parent_guid=parent_by_guid.get(guid),
                        source_path=source_path,
                        properties=properties,
                    )
                )
    return result


def _bdns_assignments(model) -> Tuple[Dict[str, Tuple[str, str, Optional[int]]], Dict[str, int]]:
    references: Dict[object, Tuple[str, str, Optional[int]]] = {}
    bdns_classifications = [item for item in _by_type(model, "IfcClassification") if _is_bdns(item)]
    for ref in _by_type(model, "IfcClassificationReference"):
        root = _root_classification(ref)
        code = _reference_code(ref)
        if root is not None and _is_bdns(root) and code:
            references[ref] = (code, _classification_name(root), _entity_id(ref))

    assignments: Dict[str, Tuple[str, str, Optional[int]]] = {}
    ambiguous_guids: Set[str] = set()
    association_count = 0
    for rel in _by_type(model, "IfcRelAssociatesClassification"):
        value = references.get(getattr(rel, "RelatingClassification", None))
        if value is None:
            continue
        association_count += 1
        for obj in getattr(rel, "RelatedObjects", None) or []:
            guid = _guid(obj)
            if guid:
                previous = assignments.get(guid)
                if previous is not None and previous[0] != value[0]:
                    ambiguous_guids.add(guid)
                    assignments.pop(guid, None)
                elif guid not in ambiguous_guids:
                    assignments[guid] = value

    return assignments, {
        "classification_count": len(bdns_classifications),
        "reference_count": len(references),
        "association_count": association_count,
        "ambiguous_asset_count": len(ambiguous_guids),
    }


def _distribution_assets(model, assignments, source_path: Optional[str] = None) -> List[IfcAsset]:
    assets: List[IfcAsset] = []
    seen: Set[str] = set()
    for obj in _by_type(model, "IfcDistributionElement"):
        if obj.is_a("IfcDistributionPort"):
            continue
        guid = _guid(obj)
        if not guid or guid in seen:
            continue
        seen.add(guid)
        assignment = assignments.get(guid)
        assets.append(
            IfcAsset(
                ifc_guid=guid,
                name=_name(obj),
                raw_ifc_class=str(obj.is_a()),
                bdns_code=assignment[0] if assignment else None,
                classification_name=assignment[1] if assignment else None,
                classification_reference_id=assignment[2] if assignment else None,
                source_path=source_path,
            )
        )
    return assets


def _containment_relations(
    model,
    asset_guids: Set[str],
    spatial_guids: Set[str],
    source_path: Optional[str] = None,
) -> List[Relation]:
    result: List[Relation] = []
    for rel in _by_type(model, "IfcRelContainedInSpatialStructure"):
        container = _guid(getattr(rel, "RelatingStructure", None))
        if not container or container not in spatial_guids:
            continue
        for obj in getattr(rel, "RelatedElements", None) or []:
            guid = _guid(obj)
            if guid and guid in asset_guids:
                result.append(
                    Relation(
                        subject_guid=guid,
                        predicate="brick:hasLocation",
                        object_guid=container,
                        source="IfcRelContainedInSpatialStructure",
                        method="explicit",
                        evidence={
                            "ifc_relation_id": _entity_id(rel),
                            "source_path": source_path,
                        },
                    )
                )
    return result


def _port_owners(model) -> Dict[int, object]:
    owners: Dict[int, object] = {}
    for rel in _by_type(model, "IfcRelConnectsPortToElement"):
        port = getattr(rel, "RelatingPort", None)
        element = getattr(rel, "RelatedElement", None)
        if port is not None and element is not None:
            port_id = _entity_id(port)
            if port_id is not None:
                owners[port_id] = element

    # IFC4 commonly nests ports under their element.
    for rel in _by_type(model, "IfcRelNests"):
        owner = getattr(rel, "RelatingObject", None)
        for child in getattr(rel, "RelatedObjects", None) or []:
            if hasattr(child, "is_a") and child.is_a("IfcDistributionPort"):
                port_id = _entity_id(child)
                if port_id is not None:
                    owners[port_id] = owner
    return owners


def _flow_direction(port) -> str:
    return str(getattr(port, "FlowDirection", None) or "").upper()


def _port_connections(model, source_path: Optional[str] = None) -> List[PortConnection]:
    """Every port connection between two owners with a GlobalId.

    Owners of any class are kept (ducts, fittings, proxies), because path
    inference needs the elements between equipment as evidence.
    """
    owners = _port_owners(model)
    result: List[PortConnection] = []
    for rel in _by_type(model, "IfcRelConnectsPorts"):
        first = getattr(rel, "RelatingPort", None)
        second = getattr(rel, "RelatedPort", None)
        first_guid = _guid(owners.get(_entity_id(first)))
        second_guid = _guid(owners.get(_entity_id(second)))
        if not first_guid or not second_guid or first_guid == second_guid:
            continue
        result.append(
            PortConnection(
                connection_id=_guid(rel) or f"ifc-entity-{_entity_id(rel)}",
                source_path=source_path,
                relating_element_guid=first_guid,
                related_element_guid=second_guid,
                relating_flow_direction=_flow_direction(first) or "UNSPECIFIED",
                related_flow_direction=_flow_direction(second) or "UNSPECIFIED",
            )
        )
    return result


def _feed_relations(
    model,
    asset_guids: Set[str],
    source_path: Optional[str] = None,
) -> Tuple[List[Relation], List[ConnectionInference]]:
    owners = _port_owners(model)
    result: List[Relation] = []
    decisions: List[ConnectionInference] = []
    seen: Set[Tuple[str, str]] = set()
    for rel in _by_type(model, "IfcRelConnectsPorts"):
        first = getattr(rel, "RelatingPort", None)
        second = getattr(rel, "RelatedPort", None)
        first_owner = owners.get(_entity_id(first))
        second_owner = owners.get(_entity_id(second))
        first_guid = _guid(first_owner)
        second_guid = _guid(second_owner)
        if not first_guid or not second_guid or first_guid == second_guid:
            continue
        if first_guid not in asset_guids or second_guid not in asset_guids:
            continue

        first_direction = _flow_direction(first)
        second_direction = _flow_direction(second)
        source = target = None
        method = "unresolved_flow_direction"
        confidence = 0.0
        review_required = True
        if first_direction == "SOURCE" and second_direction == "SINK":
            source, target = first_guid, second_guid
            method = "explicit_source_sink_flow_direction"
            confidence = 1.0
            review_required = False
        elif first_direction == "SINK" and second_direction == "SOURCE":
            source, target = second_guid, first_guid
            method = "explicit_source_sink_flow_direction"
            confidence = 1.0
            review_required = False
        elif first_direction == "SOURCE" and second_direction == "SOURCEANDSINK":
            source, target = first_guid, second_guid
            method = "source_with_bidirectional_peer"
            confidence = 0.9
            review_required = False
        elif first_direction == "SOURCEANDSINK" and second_direction == "SOURCE":
            source, target = second_guid, first_guid
            method = "source_with_bidirectional_peer"
            confidence = 0.9
            review_required = False
        elif first_direction == "SINK" and second_direction == "SOURCEANDSINK":
            source, target = second_guid, first_guid
            method = "sink_with_bidirectional_peer"
            confidence = 0.9
            review_required = False
        elif first_direction == "SOURCEANDSINK" and second_direction == "SINK":
            source, target = first_guid, second_guid
            method = "sink_with_bidirectional_peer"
            confidence = 0.9
            review_required = False

        decisions.append(
            ConnectionInference(
                connection_id=_guid(rel) or f"ifc-entity-{_entity_id(rel)}",
                source_path=source_path,
                relating_port_guid=_guid(first),
                related_port_guid=_guid(second),
                relating_equipment_guid=first_guid,
                related_equipment_guid=second_guid,
                relating_flow_direction=first_direction or "UNSPECIFIED",
                related_flow_direction=second_direction or "UNSPECIFIED",
                source_equipment_guid=source,
                target_equipment_guid=target,
                decision_status="directed" if source is not None else "ambiguous",
                inference_method=method,
                confidence=confidence,
                review_required=review_required,
            )
        )
        if source is None:
            continue
        if (source, target) in seen:
            continue
        seen.add((source, target))
        result.append(
            Relation(
                subject_guid=source,
                predicate="brick:feeds",
                object_guid=target,
                source="IfcRelConnectsPorts + port ownership + FlowDirection",
                method="derived",
                evidence={
                    "ifc_relation_id": _entity_id(rel),
                    "relating_flow_direction": first_direction,
                    "related_flow_direction": second_direction,
                    "source_path": source_path,
                    "connection_id": _guid(rel) or f"ifc-entity-{_entity_id(rel)}",
                },
            )
        )
    return result, decisions


def write_connection_inferences(
    records: Iterable[ConnectionInference],
    output_path: str | Path,
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "connection_id",
        "source_ifc",
        "relating_port_guid",
        "related_port_guid",
        "relating_equipment_guid",
        "related_equipment_guid",
        "relating_flow_direction",
        "related_flow_direction",
        "source_equipment_guid",
        "target_equipment_guid",
        "decision_status",
        "inference_method",
        "confidence",
        "review_required",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in records:
            writer.writerow(
                {
                    "connection_id": item.connection_id,
                    "source_ifc": item.source_path or "",
                    "relating_port_guid": item.relating_port_guid or "",
                    "related_port_guid": item.related_port_guid or "",
                    "relating_equipment_guid": item.relating_equipment_guid,
                    "related_equipment_guid": item.related_equipment_guid,
                    "relating_flow_direction": item.relating_flow_direction,
                    "related_flow_direction": item.related_flow_direction,
                    "source_equipment_guid": item.source_equipment_guid or "",
                    "target_equipment_guid": item.target_equipment_guid or "",
                    "decision_status": item.decision_status,
                    "inference_method": item.inference_method,
                    "confidence": item.confidence,
                    "review_required": str(item.review_required).lower(),
                }
            )
    return str(path)


def _capability(status: str, evidence: str) -> Dict[str, str]:
    return {"status": status, "evidence": evidence}


def extract_ifc(bundle: IfcBundle) -> ExtractionResult:
    model = bundle.model
    spatial = _spatial_elements(model, bundle.source_path)
    assignments, bdns_counts = _bdns_assignments(model)
    assets = _distribution_assets(model, assignments, bundle.source_path)
    asset_guids = {item.ifc_guid for item in assets}
    spatial_guids = {item.ifc_guid for item in spatial}
    containment = _containment_relations(
        model,
        asset_guids,
        spatial_guids,
        bundle.source_path,
    )
    feeds, connection_inferences = _feed_relations(
        model,
        asset_guids,
        bundle.source_path,
    )
    unresolved_port_connections = sum(
        item.decision_status == "ambiguous" for item in connection_inferences
    )

    classification_names = Counter(
        _classification_name(item) or "(unnamed)" for item in _by_type(model, "IfcClassification")
    )
    classified_count = sum(item.bdns_code is not None for item in assets)
    contained_assets = {item.subject_guid for item in containment}
    relations = containment + feeds
    audit = {
        "schema": bundle.schema,
        "source_path": bundle.source_path,
        "ifc_classifications": dict(classification_names),
        "bdns": bdns_counts,
        "counts": {
            "spatial_elements": len(spatial),
            "distribution_assets": len(assets),
            "bdns_classified_assets": classified_count,
            "unresolved_assets": len(assets) - classified_count,
            "explicit_equipment_locations": len(contained_assets),
            "derived_feeds": len(feeds),
            "undirected_port_connections": unresolved_port_connections,
        },
        "capabilities": {
            "IDENTITY": _capability("PASS" if assets else "FAIL", f"{len(assets)} distribution assets with GlobalId"),
            "CLASSIFICATION": _capability(
                "PASS" if assets and classified_count == len(assets) else "WARN",
                f"{classified_count}/{len(assets)} assets associated with the BDNS classification",
            ),
            "SPATIAL_HIERARCHY": _capability(
                "PASS" if any(item.parent_guid for item in spatial) else "WARN",
                f"{len(spatial)} spatial elements; {sum(item.parent_guid is not None for item in spatial)} hierarchy links",
            ),
            "LOCATION": _capability(
                "PASS" if assets and len(contained_assets) == len(assets) else "WARN",
                f"{len(contained_assets)}/{len(assets)} assets explicitly contained",
            ),
            "FLOW_TOPOLOGY": _capability(
                "PASS" if feeds and unresolved_port_connections == 0 else "WARN",
                f"{len(feeds)} directed feeds; {unresolved_port_connections} ambiguous connections",
            ),
        },
    }
    return ExtractionResult(
        spatial=spatial,
        assets=assets,
        relations=relations,
        connection_inferences=connection_inferences,
        audit=audit,
        port_connections=_port_connections(model, bundle.source_path),
    )


def extract_spatial_elements(bundle: IfcBundle) -> List[SpatialElement]:
    """Extract only spatial elements from an architectural IFC model."""
    return _spatial_elements(bundle.model, bundle.source_path)
