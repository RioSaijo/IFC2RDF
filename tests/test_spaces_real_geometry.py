"""Equipment -> space inference on real (not patched) geometry in a millimetre model.

Guards against scaling ifcopenshell.geom output, which is already in metres.
Space: 10 000 x 5 000 x 3 000 mm at the origin. Equipment: a 500 mm cube at
(2 000, 2 000, 2 500) mm, so its centre is (2.25, 2.25, 2.75) m.
"""
import csv
from pathlib import Path
import sys

import ifcopenshell
import ifcopenshell.guid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.pipeline import run_pipeline

STOREY_1, STOREY_2 = ifcopenshell.guid.new(), ifcopenshell.guid.new()


class _Model:
    def __init__(self):
        f = self.f = ifcopenshell.file(schema="IFC4")
        unit = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
        self.context = f.create_entity(
            "IfcGeometricRepresentationContext", ContextType="Model", CoordinateSpaceDimension=3,
            Precision=1e-5, WorldCoordinateSystem=self._axis(0, 0, 0),
        )
        f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Synthetic",
                        UnitsInContext=f.create_entity("IfcUnitAssignment", Units=[unit]),
                        RepresentationContexts=[self.context])

    def _axis(self, x, y, z):
        point = self.f.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y), float(z)))
        return self.f.create_entity("IfcAxis2Placement3D", Location=point)

    def placement(self, x, y, z):
        return self.f.create_entity("IfcLocalPlacement", RelativePlacement=self._axis(x, y, z))

    def box(self, ifc_class, name, x, y, z, dx, dy, dz, **attributes):
        f = self.f
        profile = f.create_entity(
            "IfcRectangleProfileDef", ProfileType="AREA", XDim=float(dx), YDim=float(dy),
            Position=f.create_entity("IfcAxis2Placement2D",
                                     Location=f.create_entity("IfcCartesianPoint", Coordinates=(dx / 2, dy / 2))),
        )
        solid = f.create_entity(
            "IfcExtrudedAreaSolid", SweptArea=profile, Position=self._axis(0, 0, 0),
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)), Depth=float(dz),
        )
        representation = f.create_entity("IfcShapeRepresentation", ContextOfItems=self.context,
                                          RepresentationIdentifier="Body", RepresentationType="SweptSolid",
                                          Items=[solid])
        return f.create_entity(ifc_class, GlobalId=attributes.pop("GlobalId", ifcopenshell.guid.new()), Name=name,
                               ObjectPlacement=self.placement(x, y, z),
                               Representation=f.create_entity("IfcProductDefinitionShape",
                                                              Representations=[representation]),
                               **attributes)

    def storeys(self):
        return [self.f.create_entity("IfcBuildingStorey", GlobalId=guid, Name=name,
                                     ObjectPlacement=self.placement(0, 0, z))
                for guid, name, z in ((STOREY_1, "L1", 0), (STOREY_2, "L2", 4000))]


def test_millimetre_model_places_equipment_at_metre_coordinates(tmp_path):
    arc = _Model()
    storey_1, _ = arc.storeys()
    space = arc.box("IfcSpace", "R1", 0, 0, 0, 10000, 5000, 3000)
    arc.f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=storey_1,
                        RelatedObjects=[space])
    arc.f.write(tmp_path / "arc.ifc")

    mep = _Model()
    storey_1, _ = mep.storeys()
    unit = mep.box("IfcUnitaryEquipment", "AHU-1", 2000, 2000, 2500, 500, 500, 500)
    reference = mep.f.create_entity("IfcClassificationReference", Identification="AHU-1",
                                    ReferencedSource=mep.f.create_entity("IfcClassification", Name="BDNS"))
    mep.f.create_entity("IfcRelAssociatesClassification", GlobalId=ifcopenshell.guid.new(),
                        RelatedObjects=[unit], RelatingClassification=reference)
    mep.f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                        RelatingStructure=storey_1, RelatedElements=[unit])
    mep.f.write(tmp_path / "mep.ifc")

    run_pipeline(mep_ifc_paths=[tmp_path / "mep.ifc"], arc_ifc_paths=[tmp_path / "arc.ifc"],
                 output_dir=tmp_path / "out", infer_spaces=True,
                 mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv")
    with (tmp_path / "out" / "space_locations.csv").open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["status"] == "located"
    assert row["space_name"] == "R1"
    assert row["height_relation"] == "within_space_height"
    assert [float(v) for v in row["reference_point_m"].split(",")] == [2.25, 2.25, 2.75]
