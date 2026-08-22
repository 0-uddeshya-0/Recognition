"""Unit tests for the shared geometry / writing utilities.

The pipeline tests cover behaviour end to end; these pin the small helpers the
whole harness now shares, because a change here moves every drawing at once.
"""
from __future__ import annotations

import math

from shapely.geometry import MultiPolygon, Polygon, box

from recognition import geometry as G
from recognition.drawings import DimChain
from recognition.writers import markdown_table


def test_parts_treats_polygon_and_multipolygon_alike():
    p = box(0, 0, 1, 1)
    assert G.parts(p) == [p]
    assert len(G.parts(MultiPolygon([p, box(2, 2, 3, 3)]))) == 2


def test_rect_dims_returns_short_then_long_side():
    short, long = G.rect_dims(box(0, 0, 3, 0.5))
    assert (round(short, 6), round(long, 6)) == (0.5, 3.0)


def test_union_bounds_spans_all_geometries():
    assert G.union_bounds([box(0, 0, 1, 1), box(2, -1, 3, 4)]) == (0.0, -1.0, 3.0, 4.0)


def test_snap_rounds_to_the_centimetre():
    assert G.snap(1.2349) == 1.23
    assert G.snap(1.2351) == 1.24


def test_centreline_runs_along_the_long_axis_with_a_left_normal():
    cl = G.centreline(box(0, 0, 2, 0.4))
    assert cl.mid == (1.0, 0.2)
    assert round(cl.length, 6) == 2.0
    assert round(cl.short, 6) == 0.4
    assert math.isclose(cl.u[0] * cl.n[0] + cl.u[1] * cl.n[1], 0.0, abs_tol=1e-12)
    assert cl.offset(cl.mid, 0.5) == (1.0 + cl.n[0] * 0.5, 0.2 + cl.n[1] * 0.5)


def test_centreline_of_a_diagonal_element_is_normalised():
    cl = G.centreline(Polygon([(0, 0), (2, 2), (2.1, 1.9), (0.1, -0.1)]))
    assert math.isclose(math.hypot(*cl.u), 1.0, rel_tol=1e-9)


def test_dim_chain_point_maps_stations_onto_either_axis():
    assert DimChain("x", -1.5, [0.0, 2.0]).point(2.0) == (2.0, -1.5)
    assert DimChain("x", -1.5, [0.0, 2.0]).point(2.0, 0.3) == (2.0, -1.2)
    assert DimChain("y", -1.5, [0.0, 2.0]).point(2.0) == (-1.5, 2.0)


def test_markdown_table_renders_none_as_an_empty_cell():
    lines = markdown_table(("a", "b"), [(1, None)])
    assert lines == ["| a | b |", "|---|---|", "| 1 |  |"]
