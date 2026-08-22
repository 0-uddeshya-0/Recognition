"""Shapely helpers shared by the model, the rules and the drawing code.

Anything that reasons about footprints — bounding rectangles, centrelines,
unions, coordinate snapping — lives here so the geometry is computed one way
only and SVG, DXF, schedules and rules can never disagree about it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from shapely import minimum_rotated_rectangle
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

Geom = Polygon | MultiPolygon
XY = tuple[float, float]


def parts(g: Geom) -> list[Polygon]:
    """The polygons of a (multi)polygon, so callers can treat both alike."""
    return list(g.geoms) if isinstance(g, MultiPolygon) else [g]


def union(geoms: Iterable[Geom]) -> Geom:
    return unary_union(list(geoms))


def union_bounds(geoms: Iterable[Geom]) -> tuple[float, float, float, float]:
    bs = [g.bounds for g in geoms if not g.is_empty]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def snap(v: float, step: float = 0.01) -> float:
    return round(round(v / step) * step, 3)


def _corners(g: Geom) -> list[XY]:
    """The four corners of the minimum rotated bounding rectangle."""
    return list(minimum_rotated_rectangle(g).exterior.coords)[:4]


def _mid(a: XY, b: XY) -> XY:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _dist(a: XY, b: XY) -> float:
    return Point(a).distance(Point(b))


def rect_dims(g: Geom) -> tuple[float, float]:
    """(short side, long side) of the minimum rotated bounding rectangle."""
    c = _corners(g)
    a, b = _dist(c[0], c[1]), _dist(c[1], c[2])
    return (min(a, b), max(a, b))


def long_axis(g: Geom) -> tuple[XY, XY, float]:
    """Return (p0, p1, short_side) where p0->p1 is the centreline along the long axis."""
    c = _corners(g)
    d01, d12 = _dist(c[0], c[1]), _dist(c[1], c[2])
    if d01 >= d12:
        return _mid(c[0], c[3]), _mid(c[1], c[2]), d12
    return _mid(c[0], c[1]), _mid(c[2], c[3]), d01


@dataclass(frozen=True)
class Centreline:
    """Centreline of an element footprint along its long axis."""

    p0: XY
    p1: XY
    short: float  # the footprint's short side (wall/opening thickness)
    length: float
    u: XY  # unit vector p0 -> p1
    n: XY  # unit left normal of u

    @property
    def mid(self) -> XY:
        return _mid(self.p0, self.p1)

    def offset(self, at: XY, distance: float) -> XY:
        """`at` moved `distance` along the left normal (negative = right)."""
        return (at[0] + self.n[0] * distance, at[1] + self.n[1] * distance)


def centreline(g: Geom) -> Centreline:
    p0, p1, short = long_axis(g)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1.0
    u = (dx / L, dy / L)
    return Centreline(p0, p1, short, L, u, (-u[1], u[0]))
