"""Equipment -> space locations from MEP and spatial (ARC) IFC geometry.

MEP models often contain equipment only in storeys. This module places each
equipment in an ARC IfcSpace with one deterministic rule and no tolerances on
the decision itself:

1. Coordinate frames must agree: every storey present in both models (same
   GlobalId) must have the same placement origin. If not, nothing is inferred.
2. Reference point: the centre of the equipment's own geometry (world
   coordinates, metres).
3. The reference height must lie between the floor level of the storey the
   equipment is explicitly contained in and the next storey's floor level;
   otherwise the explicit storey contradicts the geometry and nothing is
   inferred. Candidates: only spaces aggregated under that same storey (same
   GlobalId).
4. Test: the reference point lies inside the space's plan footprint, i.e. the
   union of the space geometry's triangles projected onto the XY plane.
5. Exactly one candidate passes -> `equipment brick:hasLocation space`.
   None, several, missing geometry or a missing storey -> no relation, with
   the reason written to space_locations.csv.

Height is not part of the test, because ceiling-mounted and ceiling-void
equipment sits above the space's volume; the height relation is recorded as
evidence only. Equipment explicitly contained in a space keeps that relation.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.unit

from models import IfcAsset, IfcBundle, Relation

METHOD = "geometric_plan_containment_same_storey"
FRAME_TOLERANCE_XY = 0.01  # metres; storey origins must coincide in plan
FRAME_TOLERANCE_Z = 0.05  # metres; storey elevations are often rounded per model

Point = Tuple[float, float, float]
Triangle = Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]


@dataclass(frozen=True)
class SpaceShape:
    guid: str
    name: Optional[str]
    storey_guid: Optional[str]
    min_xyz: Point
    max_xyz: Point
    triangles: Tuple[Triangle, ...]


@dataclass(frozen=True)
class SpaceDecision:
    equipment_guid: str
    equipment_name: Optional[str]
    storey_guid: Optional[str]
    status: str  # located | outside | ambiguous | storey_mismatch | no_geometry | no_storey | explicit_space
    space_guid: Optional[str] = None
    space_name: Optional[str] = None
    candidates: Tuple[str, ...] = ()
    reference_point: Optional[Point] = None
    height_relation: str = ""
    reason: str = ""


def _settings():
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    return settings


def _scale(model) -> float:
    try:
        return float(ifcopenshell.util.unit.calculate_unit_scale(model))
    except Exception:
        return 1.0


def _mesh(settings, element):
    # ifcopenshell.geom already returns coordinates in metres, whatever the
    # model's length unit; scaling them again would shrink a millimetre model
    # a thousandfold.
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except Exception:
        return None
    verts = shape.geometry.verts
    points = [(verts[i], verts[i + 1], verts[i + 2]) for i in range(0, len(verts), 3)]
    if not points:
        return None
    faces = getattr(shape.geometry, "faces", ()) or ()
    triangles = tuple(
        ((points[faces[i]][0], points[faces[i]][1]),
         (points[faces[i + 1]][0], points[faces[i + 1]][1]),
         (points[faces[i + 2]][0], points[faces[i + 2]][1]))
        for i in range(0, len(faces) - 2, 3)
    )
    xs, ys, zs = zip(*points)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)), triangles


def _inside_triangle(p: Tuple[float, float], tri: Triangle) -> bool:
    (ax, ay), (bx, by), (cx, cy) = tri

    def side(x1, y1, x2, y2):
        return (p[0] - x2) * (y1 - y2) - (x1 - x2) * (p[1] - y2)

    d1, d2, d3 = side(ax, ay, bx, by), side(bx, by, cx, cy), side(cx, cy, ax, ay)
    has_negative = d1 < 0 or d2 < 0 or d3 < 0
    has_positive = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_negative and has_positive)


def in_footprint(p: Tuple[float, float], space: SpaceShape) -> bool:
    if not (space.min_xyz[0] <= p[0] <= space.max_xyz[0] and space.min_xyz[1] <= p[1] <= space.max_xyz[1]):
        return False
    return any(_inside_triangle(p, tri) for tri in space.triangles)


def _storey_of(model) -> Dict[str, str]:
    """IfcSpace GlobalId -> GlobalId of the storey it is (transitively) aggregated under."""
    parent: Dict[str, object] = {}
    for rel in model.by_type("IfcRelAggregates"):
        for child in rel.RelatedObjects or []:
            parent[child.GlobalId] = rel.RelatingObject
    result = {}
    for space in model.by_type("IfcSpace"):
        node = parent.get(space.GlobalId)
        seen = set()
        while node is not None and node.GlobalId not in seen and not node.is_a("IfcBuildingStorey"):
            seen.add(node.GlobalId)
            node = parent.get(node.GlobalId)
        if node is not None and node.is_a("IfcBuildingStorey"):
            result[space.GlobalId] = node.GlobalId
    return result


def _storey_origins(model) -> Dict[str, Point]:
    scale = _scale(model)
    origins = {}
    for storey in model.by_type("IfcBuildingStorey"):
        if storey.ObjectPlacement is None:
            continue
        matrix = ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)
        origins[storey.GlobalId] = tuple(float(matrix[i][3]) * scale for i in range(3))
    return origins


def check_frames(mep_bundles: Sequence[IfcBundle], arc_bundles: Sequence[IfcBundle]) -> Dict[str, object]:
    """Compare origins of storeys that exist in both an MEP and an ARC model."""
    arc_origins: Dict[str, Point] = {}
    for bundle in arc_bundles:
        arc_origins.update(_storey_origins(bundle.model))
    compared, mismatches = 0, []
    for bundle in mep_bundles:
        for guid, origin in _storey_origins(bundle.model).items():
            if guid not in arc_origins:
                continue
            compared += 1
            other = arc_origins[guid]
            dxy = max(abs(origin[0] - other[0]), abs(origin[1] - other[1]))
            dz = abs(origin[2] - other[2])
            if dxy > FRAME_TOLERANCE_XY or dz > FRAME_TOLERANCE_Z:
                mismatches.append({"storey": guid, "dxy_m": round(dxy, 4), "dz_m": round(dz, 4)})
    status = "mismatch" if mismatches else ("verified" if compared else "unverified")
    return {"status": status, "shared_storeys_compared": compared, "mismatches": mismatches}


def storey_bands(arc_bundles: Sequence[IfcBundle]) -> Dict[str, Tuple[float, float]]:
    """Storey GlobalId -> (its floor level, the next storey's floor level) in metres."""
    origins: Dict[str, float] = {}
    for bundle in arc_bundles:
        origins.update({guid: origin[2] for guid, origin in _storey_origins(bundle.model).items()})
    ordered = sorted(origins.items(), key=lambda item: item[1])
    return {
        guid: (level, ordered[index + 1][1] if index + 1 < len(ordered) else float("inf"))
        for index, (guid, level) in enumerate(ordered)
    }


def load_spaces(arc_bundles: Sequence[IfcBundle]) -> Tuple[List[SpaceShape], int]:
    settings = _settings()
    spaces, failures = [], 0
    for bundle in arc_bundles:
        storeys = _storey_of(bundle.model)
        for space in bundle.model.by_type("IfcSpace"):
            mesh = _mesh(settings, space)
            if mesh is None or not mesh[2]:
                failures += 1
                continue
            spaces.append(SpaceShape(space.GlobalId, space.Name, storeys.get(space.GlobalId), *mesh))
    return spaces, failures


def infer_space_locations(
    mep_bundles: Sequence[IfcBundle],
    arc_bundles: Sequence[IfcBundle],
    equipment: Iterable[IfcAsset],
    explicit_relations: Iterable[Relation],
) -> Tuple[List[Relation], List[SpaceDecision], Dict[str, object]]:
    frames = check_frames(mep_bundles, arc_bundles)
    diagnostics: Dict[str, object] = {"method": METHOD, "coordinate_frames": frames}
    if frames["status"] == "mismatch":
        diagnostics["skipped"] = "MEP and ARC storey origins differ; no space was inferred"
        return [], [], diagnostics

    spaces, failures = load_spaces(arc_bundles)
    bands = storey_bands(arc_bundles)
    space_guids = {s.guid for s in spaces}
    by_storey: Dict[str, List[SpaceShape]] = {}
    for space in spaces:
        by_storey.setdefault(space.storey_guid, []).append(space)
    diagnostics.update(arc_spaces_with_geometry=len(spaces), arc_space_geometry_failures=failures)

    explicit = {}
    for item in explicit_relations:
        if item.predicate == "brick:hasLocation" and item.method == "explicit":
            explicit.setdefault(item.subject_guid, []).append(item.object_guid)

    equipment = list(equipment)
    elements: Dict[str, object] = {}
    for bundle in mep_bundles:
        for asset in equipment:
            if asset.ifc_guid in elements:
                continue
            try:
                elements[asset.ifc_guid] = bundle.model.by_guid(asset.ifc_guid)
            except RuntimeError:
                continue

    settings = _settings()
    relations: List[Relation] = []
    decisions: List[SpaceDecision] = []
    for asset in equipment:
        containers = explicit.get(asset.ifc_guid, [])
        if any(guid in space_guids for guid in containers):
            decisions.append(SpaceDecision(asset.ifc_guid, asset.name, None, "explicit_space",
                                           reason="explicitly contained in a space"))
            continue
        storey = next((guid for guid in containers if guid in by_storey), None)
        if storey is None:
            decisions.append(SpaceDecision(asset.ifc_guid, asset.name, containers[0] if containers else None,
                                           "no_storey", reason="not contained in a storey that has ARC spaces"))
            continue
        element = elements.get(asset.ifc_guid)
        mesh = _mesh(settings, element) if element is not None else None
        if mesh is None:
            decisions.append(SpaceDecision(asset.ifc_guid, asset.name, storey, "no_geometry",
                                           reason="equipment has no geometry"))
            continue
        lo, hi, _ = mesh
        point = tuple(round((lo[i] + hi[i]) / 2.0, 4) for i in range(3))
        floor, next_floor = bands.get(storey, (float("-inf"), float("inf")))
        if not floor <= point[2] < next_floor:
            decisions.append(SpaceDecision(asset.ifc_guid, asset.name, storey, "storey_mismatch",
                                           reference_point=point,
                                           reason=f"reference height {point[2]} m is outside its storey "
                                                  f"({floor} m to {next_floor} m)"))
            continue
        hits = [space for space in by_storey[storey] if in_footprint(point[:2], space)]
        if len(hits) != 1:
            status = "outside" if not hits else "ambiguous"
            reason = ("reference point is outside every space footprint on its storey" if not hits
                      else f"reference point is inside {len(hits)} overlapping space footprints")
            decisions.append(SpaceDecision(asset.ifc_guid, asset.name, storey, status,
                                           candidates=tuple(s.guid for s in hits), reference_point=point,
                                           reason=reason))
            continue
        space = hits[0]
        height = ("within_space_height" if space.min_xyz[2] <= point[2] <= space.max_xyz[2]
                  else "above_space" if point[2] > space.max_xyz[2] else "below_space")
        decisions.append(SpaceDecision(asset.ifc_guid, asset.name, storey, "located", space.guid, space.name,
                                       reference_point=point, height_relation=height))
        relations.append(
            Relation(
                subject_guid=asset.ifc_guid,
                predicate="brick:hasLocation",
                object_guid=space.guid,
                source="MEP equipment geometry + ARC IfcSpace geometry",
                method=METHOD,
                evidence={
                    "reference_point_m": point,
                    "storey": storey,
                    "height_relation": height,
                    "coordinate_frames": frames["status"],
                },
            )
        )
    counts: Dict[str, int] = {}
    for item in decisions:
        counts[item.status] = counts.get(item.status, 0) + 1
    diagnostics["decisions"] = counts
    return relations, decisions, diagnostics


def write_space_locations(decisions: Iterable[SpaceDecision], output_path: str | Path) -> str:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    columns = ["equipment_guid", "equipment_name", "storey_guid", "status", "space_guid", "space_name",
               "candidates", "reference_point_m", "height_relation", "reason"]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in decisions:
            writer.writerow({
                "equipment_guid": item.equipment_guid,
                "equipment_name": item.equipment_name or "",
                "storey_guid": item.storey_guid or "",
                "status": item.status,
                "space_guid": item.space_guid or "",
                "space_name": item.space_name or "",
                "candidates": ";".join(item.candidates),
                "reference_point_m": "" if item.reference_point is None else ",".join(map(str, item.reference_point)),
                "height_relation": item.height_relation,
                "reason": item.reason,
            })
    return str(destination)
