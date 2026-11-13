"""Equipment -> space inference (src/spaces.py) with synthetic geometry.

Shapes are injected by patching ifcopenshell.geom.create_shape, keyed by
element Name. Storey 1 holds an L-shaped space A, overlapping spaces C and D;
storey 2 holds space B. Both models share storey GlobalIds.

    y
    10 +----+                      B (storey 2): x 20..30
       | A  |  notch               C, D (storey 1): x 40..50, overlapping
     4 |    +-----+
       |    A     |
     0 +----------+ x
       0    4    10
"""
import csv
from pathlib import Path
from types import SimpleNamespace
import sys

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.guid
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.pipeline import run_pipeline

S1, S2 = ifcopenshell.guid.new(), ifcopenshell.guid.new()


def _box(x0, y0, z0, x1, y1, z1, offset=0):
    verts = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    faces = [i + offset for a, b, c, d in quads for i in (a, b, c, a, c, d)]
    return [v for p in verts for v in p], faces


def _mesh(*boxes):
    verts, faces = [], []
    for box in boxes:
        v, f = _box(*box, offset=len(verts) // 3)
        verts += v
        faces += f
    return SimpleNamespace(geometry=SimpleNamespace(verts=verts, faces=faces))


SHAPES = {
    "A": _mesh((0, 0, 0, 10, 4, 3), (0, 4, 0, 4, 10, 3)),
    "B": _mesh((20, 0, 0, 30, 10, 3)),
    "C": _mesh((40, 0, 0, 50, 10, 3)),
    "D": _mesh((40, 0, 0, 50, 10, 3)),
    "AHU-1": _mesh((1.5, 1.5, 3.2, 2.5, 2.5, 3.8)),  # inside A, above its ceiling
    "AHU-2": _mesh((7.5, 7.5, 1, 8.5, 8.5, 2)),  # inside A's bounding box, in the notch
    "AHU-3": _mesh((24.5, 4.5, 1, 25.5, 5.5, 2)),  # under B, but contained in storey 1
    "AHU-4": _mesh((44.5, 4.5, 1, 45.5, 5.5, 2)),  # inside both C and D
    "AHU-5": _mesh((1, 1, 1, 2, 2, 2)),  # explicitly contained in space A
    "AHU-6": _mesh((1.5, 1.5, 12, 2.5, 2.5, 13)),  # contained in storey 1 but at storey 2 height
}


def _placement(model, x=0.0, z=0.0):
    point = model.create_entity("IfcCartesianPoint", Coordinates=(x, 0.0, z))
    return model.create_entity("IfcLocalPlacement",
                               RelativePlacement=model.create_entity("IfcAxis2Placement3D", Location=point))


def _models(tmp_path, arc_offset=0.0):
    arc = ifcopenshell.file(schema="IFC4")
    storeys = {g: arc.create_entity("IfcBuildingStorey", GlobalId=g, Name=n,
                                    ObjectPlacement=_placement(arc, arc_offset, z))
               for g, n, z in ((S1, "L1", 0.0), (S2, "L2", 10.0))}
    spaces = {n: arc.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name=n) for n in "ABCD"}
    for storey, names in ((S1, "ACD"), (S2, "B")):
        arc.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=storeys[storey],
                          RelatedObjects=[spaces[n] for n in names])
    arc_path = tmp_path / "arc.ifc"
    arc.write(arc_path)

    mep = ifcopenshell.file(schema="IFC4")
    storey = mep.create_entity("IfcBuildingStorey", GlobalId=S1, Name="L1", ObjectPlacement=_placement(mep))
    space_a = mep.create_entity("IfcSpace", GlobalId=spaces["A"].GlobalId, Name="A")
    classification = mep.create_entity("IfcClassification", Name="BDNS")
    units = {}
    for name in ("AHU-1", "AHU-2", "AHU-3", "AHU-4", "AHU-5", "AHU-6"):
        unit = mep.create_entity("IfcUnitaryEquipment", GlobalId=ifcopenshell.guid.new(), Name=name)
        reference = mep.create_entity("IfcClassificationReference", Identification=name, ReferencedSource=classification)
        mep.create_entity("IfcRelAssociatesClassification", GlobalId=ifcopenshell.guid.new(),
                          RelatedObjects=[unit], RelatingClassification=reference)
        units[name] = unit
    mep.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(), RelatingStructure=storey,
                      RelatedElements=[units[n] for n in ("AHU-1", "AHU-2", "AHU-3", "AHU-4", "AHU-6")])
    mep.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                      RelatingStructure=space_a, RelatedElements=[units["AHU-5"]])
    mep_path = tmp_path / "mep.ifc"
    mep.write(mep_path)
    return mep_path, arc_path


@pytest.fixture(autouse=True)
def fake_shapes(monkeypatch):
    def create_shape(_settings, element):
        if element.Name not in SHAPES:
            raise RuntimeError("no geometry")
        return SHAPES[element.Name]

    monkeypatch.setattr(ifcopenshell.geom, "create_shape", create_shape)


def _run(tmp_path, arc_offset=0.0):
    mep, arc = _models(tmp_path, arc_offset)
    result = run_pipeline(mep_ifc_paths=[mep], arc_ifc_paths=[arc], output_dir=tmp_path / "out",
                          mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
                          infer_spaces=True)
    rows = {}
    path = tmp_path / "out" / "space_locations.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            rows = {r["equipment_name"]: r for r in csv.DictReader(handle)}
    return result, rows


def test_equipment_inside_a_footprint_is_located_even_above_the_ceiling(tmp_path):
    _, rows = _run(tmp_path)

    assert rows["AHU-1"]["status"] == "located"
    assert rows["AHU-1"]["space_name"] == "A"
    assert rows["AHU-1"]["height_relation"] == "above_space"


def test_bounding_box_alone_does_not_place_equipment(tmp_path):
    _, rows = _run(tmp_path)

    assert rows["AHU-2"]["status"] == "outside"


def test_only_spaces_on_the_equipment_storey_are_candidates(tmp_path):
    _, rows = _run(tmp_path)

    assert rows["AHU-3"]["status"] == "outside"


def test_overlapping_spaces_are_ambiguous_and_not_written(tmp_path):
    result, rows = _run(tmp_path)

    assert rows["AHU-4"]["status"] == "ambiguous"
    assert len(rows["AHU-4"]["candidates"].split(";")) == 2
    # AHU-1 inferred, AHU-5 explicit; AHU-2..4 stay in their storey only
    assert "1 inferred; 2 in a space" in result["capabilities"]["LOCATION"]["evidence"]


def test_height_outside_the_explicit_storey_is_a_storey_mismatch(tmp_path):
    _, rows = _run(tmp_path)

    assert rows["AHU-6"]["status"] == "storey_mismatch"


def test_explicit_space_containment_wins(tmp_path):
    _, rows = _run(tmp_path)

    assert rows["AHU-5"]["status"] == "explicit_space"


def test_mismatched_coordinate_frames_stop_inference(tmp_path):
    result, rows = _run(tmp_path, arc_offset=5.0)

    assert rows == {}
    assert "0 inferred; 1 in a space" in result["capabilities"]["LOCATION"]["evidence"]  # AHU-5 explicit
