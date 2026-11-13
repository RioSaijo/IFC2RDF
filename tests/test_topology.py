"""Synthetic IFC2x3 topology cases for brick:feeds path inference.

Layout (arrows are explicit SOURCE -> SINK port connections, "--" is
SOURCEANDSINK on both ports):

    AHU-1 -> DUW -> tee0 -> FD-1 -> DUW -> VAV-1 -> DUW -> tee1 -> DUW -> SG-1
                     |                              |  \\
                     +-> DUW -> VAV-2 -> DUW (end)  |   +-- DUW -- SG-2
                                                    +<- DUW <- SG-3

    DUW -> SG-1 also has a parallel connection in the opposite direction.
    SEF-1 -> SEF-2 and SEF-2 -> SEF-1 are both asserted by parallel connections.
    FD-1 is a fire damper, a pass-through topology role.
"""
import csv
from pathlib import Path
import sys

import ifcopenshell
import ifcopenshell.guid
from rdflib import Graph
from rdflib.namespace import RDF


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
EXAMPLES = PROJECT_ROOT / "examples"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(EXAMPLES))

from app.pipeline import run_pipeline
from create_synthetic_inputs import _create_arc
from rdf import BRICK, equipment_iri


BASE_NS = "https://example.org/topology#"


class _Builder:
    def __init__(self):
        self.model = ifcopenshell.file(schema="IFC2X3")
        self.bdns = self.model.create_entity(
            "IfcClassification", Source="Synthetic", Edition="example", Name="BDNS"
        )

    def element(self, ifc_class, name, bdns_code=None):
        element = self.model.create_entity(
            ifc_class, GlobalId=ifcopenshell.guid.new(), Name=name
        )
        if bdns_code:
            reference = self.model.create_entity(
                "IfcClassificationReference",
                ItemReference=bdns_code,
                Name=name,
                ReferencedSource=self.bdns,
            )
            self.model.create_entity(
                "IfcRelAssociatesClassification",
                GlobalId=ifcopenshell.guid.new(),
                RelatedObjects=[element],
                RelatingClassification=reference,
            )
        return element

    def _port(self, element, direction):
        port = self.model.create_entity(
            "IfcDistributionPort", GlobalId=ifcopenshell.guid.new(), FlowDirection=direction
        )
        self.model.create_entity(
            "IfcRelConnectsPortToElement",
            GlobalId=ifcopenshell.guid.new(),
            RelatingPort=port,
            RelatedElement=element,
        )
        return port

    def flow(self, upstream, downstream):
        self.model.create_entity(
            "IfcRelConnectsPorts",
            GlobalId=ifcopenshell.guid.new(),
            RelatingPort=self._port(upstream, "SOURCE"),
            RelatedPort=self._port(downstream, "SINK"),
        )

    def undirected(self, first, second):
        self.model.create_entity(
            "IfcRelConnectsPorts",
            GlobalId=ifcopenshell.guid.new(),
            RelatingPort=self._port(first, "SOURCEANDSINK"),
            RelatedPort=self._port(second, "SOURCEANDSINK"),
        )


def _build(tmp_path):
    b = _Builder()
    ducts = iter(range(1, 1000))
    duct = lambda: (lambda n: b.element("IfcFlowSegment", f"DUW-{n}", f"DUW-{n}"))(next(ducts))
    ahu = b.element("IfcEnergyConversionDevice", "AHU-1", "AHU-1")
    vav1 = b.element("IfcFlowController", "VAV-1", "VAV-1")
    vav2 = b.element("IfcFlowController", "VAV-2", "VAV-2")
    sg1 = b.element("IfcFlowTerminal", "SG-1", "SG-1")
    sg2 = b.element("IfcFlowTerminal", "SG-2", "SG-2")
    sg3 = b.element("IfcFlowTerminal", "SG-3", "SG-3")
    sef1 = b.element("IfcFlowMovingDevice", "SEF-1", "SEF-1")
    sef2 = b.element("IfcFlowMovingDevice", "SEF-2", "SEF-2")
    fd = b.element("IfcFlowController", "FD-1", "FD-1")
    tee0 = b.element("IfcFlowFitting", "tee0")
    tee1 = b.element("IfcFlowFitting", "tee1")

    d_ahu, d_vav1_in, d_vav2_in, d_vav2_out = duct(), duct(), duct(), duct()
    d_vav1_out, d_sg1, d_sg2, d_sg3 = duct(), duct(), duct(), duct()

    b.flow(ahu, d_ahu)
    b.flow(d_ahu, tee0)
    b.flow(tee0, fd)
    b.flow(fd, d_vav1_in)
    b.flow(d_vav1_in, vav1)
    b.flow(tee0, d_vav2_in)
    b.flow(d_vav2_in, vav2)
    b.flow(vav2, d_vav2_out)
    b.flow(vav1, d_vav1_out)
    b.flow(d_vav1_out, tee1)
    b.flow(tee1, d_sg1)
    b.flow(d_sg1, sg1)
    b.flow(sg1, d_sg1)  # parallel connection asserting the opposite direction
    b.undirected(tee1, d_sg2)
    b.undirected(d_sg2, sg2)
    b.flow(sg3, d_sg3)  # reversed branch: a supply diffuser drawn as the source
    b.flow(d_sg3, tee1)
    b.flow(sef1, sef2)
    b.flow(sef2, sef1)

    mep_path = tmp_path / "topology_mep.ifc"
    b.model.write(mep_path)
    arc_path = tmp_path / "topology_arc.ifc"
    _create_arc(arc_path, ifcopenshell.guid.new(), "T")
    guids = {
        name: element.GlobalId
        for name, element in {
            "ahu": ahu, "vav1": vav1, "vav2": vav2, "sg1": sg1, "sg2": sg2, "sg3": sg3,
            "sef1": sef1, "sef2": sef2, "d_ahu": d_ahu, "tee0": tee0, "d_sg1": d_sg1, "fd": fd,
        }.items()
    }
    return mep_path, arc_path, guids


def _run(tmp_path):
    mep_path, arc_path, guids = _build(tmp_path)
    output = tmp_path / "output"
    result = run_pipeline(
        mep_ifc_paths=[mep_path],
        arc_ifc_paths=[arc_path],
        output_dir=output,
        mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
        base_ns=BASE_NS,
        topology_roles_path=PROJECT_ROOT / "data" / "resources" / "topology_roles.csv",
    )
    graph = Graph().parse(output / "building_brick.ttl", format="turtle")
    with (output / "topology_paths.csv").open(encoding="utf-8", newline="") as handle:
        paths = list(csv.DictReader(handle))
    return result, graph, paths, guids


def _feeds(graph, guids):
    by_iri = {equipment_iri(BASE_NS, guid): name for name, guid in guids.items()}
    return {
        (by_iri.get(s, str(s)), by_iri.get(o, str(o)))
        for s, o in graph.subject_objects(BRICK.feeds)
    }


def _path(paths, guids, source, target):
    return next(
        row for row in paths
        if row["source_equipment_guid"] == guids[source]
        and row["target_equipment_guid"] == guids[target]
    )


def test_feeds_follow_explicit_paths_through_unmapped_ducts(tmp_path):
    _, graph, _, guids = _run(tmp_path)

    assert _feeds(graph, guids) == {("ahu", "vav1"), ("ahu", "vav2"), ("vav1", "sg1")}


def test_intermediate_ducts_and_fittings_are_path_evidence_not_rdf(tmp_path):
    _, graph, paths, guids = _run(tmp_path)

    row = _path(paths, guids, "ahu", "vav1")
    traversed = row["traversed_element_guids"].split(";")
    assert guids["d_ahu"] in traversed and guids["tee0"] in traversed
    assert row["hop_count"] == "5"
    assert row["decision_status"] == "inferred"
    assert row["review_required"] == "false"
    for name in ("d_ahu", "tee0"):
        assert not list(graph.triples((equipment_iri(BASE_NS, guids[name]), RDF.type, None)))


def test_passthrough_damper_is_traversed_but_kept_as_equipment(tmp_path):
    _, graph, paths, guids = _run(tmp_path)

    row = _path(paths, guids, "ahu", "vav1")
    assert row["traversed_equipment_guids"] == guids["fd"]
    assert guids["fd"] in row["traversed_element_guids"].split(";")
    assert not any(guids["fd"] in (r["source_equipment_guid"], r["target_equipment_guid"]) for r in paths)
    assert (equipment_iri(BASE_NS, guids["fd"]), RDF.type, BRICK.Damper) in graph


def test_undirected_branch_is_not_forced(tmp_path):
    _, graph, paths, guids = _run(tmp_path)

    assert not any(guids["sg2"] in (r["source_equipment_guid"], r["target_equipment_guid"]) for r in paths)
    assert (equipment_iri(BASE_NS, guids["sg2"]), RDF.type, BRICK.Air_Diffuser) in graph


def test_diffuser_as_source_is_a_role_conflict(tmp_path):
    _, _, paths, guids = _run(tmp_path)

    row = _path(paths, guids, "sg3", "sg1")
    assert row["decision_status"] == "role_conflict"
    assert not any(
        r["source_equipment_guid"] in (guids["sg1"], guids["sg3"]) and r["decision_status"] == "inferred"
        for r in paths
    )


def test_conflicting_parallel_connection_resolved_by_role_needs_review(tmp_path):
    _, _, paths, guids = _run(tmp_path)

    row = _path(paths, guids, "vav1", "sg1")
    assert row["decision_status"] == "inferred"
    assert row["conflicting_connection_pairs"] == "1"
    assert row["review_required"] == "true"
    assert float(row["confidence"]) < 1.0


def test_mutually_asserted_direction_is_excluded(tmp_path):
    _, graph, paths, guids = _run(tmp_path)

    assert _path(paths, guids, "sef1", "sef2")["decision_status"] == "direction_conflict"
    assert _path(paths, guids, "sef2", "sef1")["decision_status"] == "direction_conflict"
    assert ("sef1", "sef2") not in _feeds(graph, guids)


def test_dead_end_branch_produces_no_downstream_feed(tmp_path):
    _, _, paths, guids = _run(tmp_path)

    assert not any(r["source_equipment_guid"] == guids["vav2"] for r in paths)


def test_flow_topology_capability_reports_path_counts(tmp_path):
    result, _, _, _ = _run(tmp_path)

    flow = result["capabilities"]["FLOW_TOPOLOGY"]
    assert flow["status"] == "WARN"
    assert "3 inferred feeds" in flow["evidence"]
    assert "1 role conflicts" in flow["evidence"]
    assert "2 direction conflicts" in flow["evidence"]
