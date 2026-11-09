"""Explorer queries (UI GraphDB panel) run against the synthetic linked RDF via rdflib."""
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import explorer
from graphdb import LocalGraph
from test_points_match import BASE_NS, _run


@pytest.fixture
def linked(tmp_path):
    _run(tmp_path)
    return LocalGraph(tmp_path / "3_match" / "linked_brick.ttl")


def _iri_of(source, name):
    rows = explorer.search(source, "", BASE_NS, name)["rows"]
    return next(r["n"] for r in rows if r["name"] == name)


def test_search_finds_equipment_spaces_and_points(linked):
    names = {r["name"] for r in explorer.search(linked, "", BASE_NS, "ahu-0000")["rows"]}

    assert {"AHU-00001", "AHU-00001_SAT", "AHU-00009_SAT"} <= names


def test_neighbors_show_points_and_feeds_but_not_types_or_units(linked):
    ahu = _iri_of(linked, "AHU-00001")
    graph = explorer.neighbors(linked, "", ahu)
    labels = {n["label"] for n in graph["nodes"]}
    predicates = {e["p"] for e in graph["edges"]}

    assert {"hasPoint", "feeds"} <= predicates
    assert "type" not in predicates and "hasUnit" not in predicates
    assert "AHU-00001 Supply Air Temperature" in labels and "VAV-00001" in labels


def test_feeds_paths_walk_upstream_and_downstream(linked):
    vav = _iri_of(linked, "VAV-00001")
    graph = explorer.feeds_paths(linked, "", vav)

    assert [(e["p"]) for e in graph["edges"]] == ["feeds"]
    assert {n["label"] for n in graph["nodes"]} == {"AHU-00001", "VAV-00001"}


def test_preset_tables(linked):
    unlinked = {r["pointId"] for r in explorer.unlinked_points(linked, "", BASE_NS)["rows"]}
    unclassified = {r["pointId"] for r in explorer.unclassified_points(linked, "", BASE_NS)["rows"]}
    feeds = explorer.feeds_table(linked, "", BASE_NS)["rows"]

    assert unlinked == {"ROOM_X", "AHU-00009_SAT"}  # AHU-00009 has a type-level BDNS tag only
    assert unclassified == {"AHU-00001_AI7", "BAD_UNIT", "BAD_BINARY"}
    assert feeds == [{"from": "AHU-00001", "to": "VAV-00001"}]


def test_search_text_cannot_break_out_of_the_query(linked):
    assert explorer.search(linked, "", BASE_NS, 'x") } SELECT * { ?s ?p ?o')["rows"] == []
    with pytest.raises(ValueError):
        explorer.neighbors(linked, "", "not an iri> } DROP ALL {")
