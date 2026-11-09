"""Infer brick:feeds between mapped equipment from explicit IFC port flow paths.

Only connections whose ports are explicitly SOURCE -> SINK give a direction;
SOURCEANDSINK connections are never forced. Elements that are not mapped
equipment (ducts, fittings, tbd tags, unclassified elements) are traversed as
path evidence and never become RDF entities. Mapped equipment whose BDNS tag
has the `passthrough` topology role (dampers, silencers) is traversed the same
way: it keeps its own class and location in RDF but is not a feeds node, so
AHU -> damper -> VAV yields "AHU feeds VAV". A path stops at the first node
equipment it reaches.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from mapping import lookup_code
from models import BrickEquipment, PortConnection, Relation, TopologyPath


# Brick 1.4.4 defines Air_Diffuser as delivering air into a room, so a diffuser
# can only end an air path. A path that starts at one contradicts that role.
SINK_ONLY_CLASSES = frozenset(
    {
        "brick:Air_Diffuser",
        "brick:Displacement_Flow_Air_Diffuser",
        "brick:Jet_Nozzle_Air_Diffuser",
        "brick:Laminar_Flow_Air_Diffuser",
    }
)

METHOD = "explicit_source_sink_path"
CONFLICTED_PATH_CONFIDENCE = 0.8

# node -> [(next node, connection id, pair is also asserted in reverse)]
_Edges = Dict[str, List[Tuple[str, str, bool]]]


def load_passthrough_codes(path: str | Path | None) -> Set[str]:
    """BDNS abbreviations whose equipment is traversed instead of being a feeds node."""
    if path is None:
        return set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return {
            lookup_code(row["bdns_abbreviation"])
            for row in csv.DictReader(handle)
            if (row.get("topology_role") or "").strip() == "passthrough"
        }


def _directed_edges(connections: Iterable[PortConnection]) -> Tuple[_Edges, int, int]:
    asserted: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    seen: Set[str] = set()
    for item in connections:
        if item.connection_id in seen:
            continue
        seen.add(item.connection_id)
        directions = (item.relating_flow_direction, item.related_flow_direction)
        if directions == ("SOURCE", "SINK"):
            asserted[(item.relating_element_guid, item.related_element_guid)].append(item.connection_id)
        elif directions == ("SINK", "SOURCE"):
            asserted[(item.related_element_guid, item.relating_element_guid)].append(item.connection_id)

    # Parallel connections on the same element pair may assert opposite
    # directions. Both readings are kept as candidates; the role check and the
    # mutual-direction check below decide which one survives.
    conflicting = {frozenset(pair) for pair in asserted if (pair[1], pair[0]) in asserted}
    edges: _Edges = defaultdict(list)
    for (upstream, downstream), ids in sorted(asserted.items()):
        edges[upstream].append((downstream, ids[0], frozenset((upstream, downstream)) in conflicting))
    return edges, len(asserted), len(conflicting)


def _paths_from(start: str, edges: _Edges, anchors: Set[str]):
    """Shortest directed paths from start to each first-reached anchor."""
    previous: Dict[str, Tuple[str, str, bool] | None] = {start: None}
    queue = deque([start])
    reached: List[str] = []
    while queue:
        node = queue.popleft()
        for following, connection_id, conflicted in edges.get(node, ()):
            if following in previous:
                continue
            previous[following] = (node, connection_id, conflicted)
            if following in anchors:
                reached.append(following)
            else:
                queue.append(following)

    for target in reached:
        elements: List[str] = []
        connection_ids: List[str] = []
        conflicts = 0
        node = target
        while previous[node] is not None:
            node, connection_id, conflicted = previous[node]
            connection_ids.append(connection_id)
            conflicts += conflicted
            if node != start:
                elements.append(node)
        yield target, elements[::-1], connection_ids[::-1], conflicts


def infer_feed_paths(
    connections: Iterable[PortConnection],
    equipment: Iterable[BrickEquipment],
    passthrough_codes: Set[str] = frozenset(),
) -> Tuple[List[TopologyPath], List[Relation], Dict[str, int]]:
    mapped = {item.ifc_guid: item for item in equipment if item.brick_class is not None}
    passthrough = {
        guid for guid, item in mapped.items() if lookup_code(item.bdns_code) in passthrough_codes
    }
    anchors = {guid: item for guid, item in mapped.items() if guid not in passthrough}
    edges, directed_pairs, conflicting_pairs = _directed_edges(connections)

    candidates = [
        (source, target, elements, connection_ids, conflicts)
        for source in sorted(anchors)
        for target, elements, connection_ids, conflicts in _paths_from(source, edges, set(anchors))
    ]
    role_valid = {
        (source, target)
        for source, target, *_ in candidates
        if anchors[source].brick_class not in SINK_ONLY_CLASSES
    }

    paths: List[TopologyPath] = []
    for index, (source, target, elements, connection_ids, conflicts) in enumerate(
        sorted(candidates, key=lambda item: (item[0], item[1])), start=1
    ):
        source_class = anchors[source].brick_class
        if source_class in SINK_ONLY_CLASSES:
            status = "role_conflict"
            reason = f"{source_class} delivers air into a room and cannot feed other equipment"
        elif (target, source) in role_valid:
            status = "direction_conflict"
            reason = "explicit flow directions assert both this path and its reverse"
        else:
            status = "inferred"
            reason = (
                f"{conflicts} element pair(s) on this path also have a connection asserting "
                "the opposite direction; the opposite reading fails the role check"
                if conflicts
                else ""
            )
        inferred = status == "inferred"
        paths.append(
            TopologyPath(
                path_id=f"path-{index:05d}",
                source_equipment_guid=source,
                target_equipment_guid=target,
                source_class=source_class,
                target_class=anchors[target].brick_class,
                decision_status=status,
                inference_method=METHOD,
                traversed_element_guids=elements,
                traversed_connection_ids=connection_ids,
                conflicting_connection_pairs=conflicts,
                confidence=(CONFLICTED_PATH_CONFIDENCE if conflicts else 1.0) if inferred else 0.0,
                review_required=not inferred or conflicts > 0,
                reason=reason,
                traversed_equipment_guids=[guid for guid in elements if guid in passthrough],
            )
        )

    relations = [
        Relation(
            subject_guid=item.source_equipment_guid,
            predicate="brick:feeds",
            object_guid=item.target_equipment_guid,
            source="IfcRelConnectsPorts path + port FlowDirection",
            method=METHOD,
            confidence=item.confidence,
            review_required=item.review_required,
            evidence={
                "path_id": item.path_id,
                "hop_count": item.hop_count,
                "traversed_equipment_guids": item.traversed_equipment_guids,
                "traversed_connection_ids": item.traversed_connection_ids,
                "conflicting_connection_pairs": item.conflicting_connection_pairs,
            },
        )
        for item in paths
        if item.decision_status == "inferred"
    ]
    statuses = Counter(item.decision_status for item in paths)
    stats = {
        "node_equipment": len(anchors),
        "passthrough_equipment": len(passthrough),
        "directed_element_pairs": directed_pairs,
        "conflicting_element_pairs": conflicting_pairs,
        "inferred_feeds": statuses["inferred"],
        "role_conflicts": statuses["role_conflict"],
        "direction_conflicts": statuses["direction_conflict"],
        "review_required_feeds": sum(item.review_required for item in relations),
    }
    return paths, relations, stats


def write_topology_paths(paths: Iterable[TopologyPath], output_path: str | Path) -> str:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "path_id",
        "source_equipment_guid",
        "target_equipment_guid",
        "source_class",
        "target_class",
        "decision_status",
        "inference_method",
        "hop_count",
        "traversed_equipment_guids",
        "traversed_element_guids",
        "traversed_connection_ids",
        "conflicting_connection_pairs",
        "confidence",
        "review_required",
        "reason",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in paths:
            writer.writerow(
                {
                    "path_id": item.path_id,
                    "source_equipment_guid": item.source_equipment_guid,
                    "target_equipment_guid": item.target_equipment_guid,
                    "source_class": item.source_class or "",
                    "target_class": item.target_class or "",
                    "decision_status": item.decision_status,
                    "inference_method": item.inference_method,
                    "hop_count": item.hop_count,
                    "traversed_equipment_guids": ";".join(item.traversed_equipment_guids),
                    "traversed_element_guids": ";".join(item.traversed_element_guids),
                    "traversed_connection_ids": ";".join(item.traversed_connection_ids),
                    "conflicting_connection_pairs": item.conflicting_connection_pairs,
                    "confidence": item.confidence,
                    "review_required": str(item.review_required).lower(),
                    "reason": item.reason,
                }
            )
    return str(destination)
