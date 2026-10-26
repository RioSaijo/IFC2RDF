from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class IfcBundle:
    schema: str
    source_path: str
    model: Any


@dataclass(frozen=True)
class SpatialElement:
    ifc_guid: str
    name: Optional[str]
    raw_ifc_class: str
    parent_guid: Optional[str] = None
    source_path: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IfcAsset:
    ifc_guid: str
    name: Optional[str]
    raw_ifc_class: str
    bdns_code: Optional[str] = None
    classification_name: Optional[str] = None
    classification_reference_id: Optional[int] = None
    source_path: Optional[str] = None


@dataclass(frozen=True)
class BrickEquipment:
    ifc_guid: str
    brick_class: Optional[str]
    label: str
    bdns_code: Optional[str]
    raw_ifc_class: str
    mapping_status: str
    mapping_source: Optional[str]
    classification_name: Optional[str]
    source_path: Optional[str] = None


@dataclass(frozen=True)
class BrickPoint:
    iri: str
    name: str
    brick_class: str
    equipment_ref: Optional[str]
    unit: Optional[str]


@dataclass(frozen=True)
class Relation:
    subject_guid: str
    predicate: str
    object_guid: str
    source: str
    method: str
    confidence: float = 1.0
    review_required: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionInference:
    connection_id: str
    source_path: Optional[str]
    relating_port_guid: Optional[str]
    related_port_guid: Optional[str]
    relating_equipment_guid: str
    related_equipment_guid: str
    relating_flow_direction: str
    related_flow_direction: str
    source_equipment_guid: Optional[str]
    target_equipment_guid: Optional[str]
    decision_status: str
    inference_method: str
    confidence: float
    review_required: bool


@dataclass(frozen=True)
class PointLink:
    equipment_guid: str
    point_iri: str
    source: str
    method: str
    review_required: bool = False


@dataclass
class ExtractionResult:
    spatial: List[SpatialElement]
    assets: List[IfcAsset]
    relations: List[Relation]
    connection_inferences: List[ConnectionInference]
    audit: Dict[str, Any]

