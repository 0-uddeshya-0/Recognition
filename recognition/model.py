"""Load an IFC file into a small, geometry-aware domain model.

Everything downstream (schedules, rules, drawings) works on these dataclasses,
never on raw IFC entities, so the rest of the harness stays tool-agnostic.
Tags (R-01, D-01, W-01 ...) are assigned deterministically by storey and
position so that re-running on an unchanged model produces identical output —
that is what makes the generated drawings and schedules diffable in git.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
from shapely.geometry import Point, Polygon

from .geometry import Geom, parts, rect_dims, union

# Room classification by name keyword (English + German, covers the sample models).
ROOM_CATEGORIES: dict[str, list[str]] = {
    "bedroom": ["bedroom", "schlaf", "bed ", "zimmer", "kind", "slaapkamer"],
    "living": ["living", "wohn", "lounge", "woonkamer", "essen", "dining"],
    "kitchen": ["kitchen", "küche", "kueche", "kochen", "keuken"],
    "bathroom": ["bath", "bad", "wc", "toilet", "shower", "badkamer", "dusche"],
    "office": ["office", "büro", "buero", "study", "kantoor"],
    "meeting": ["meeting", "conference", "besprechung", "seminar"],
    "lab": ["labor", "lab "],
    "hall": ["hall", "flur", "corridor", "foyer", "entry", "lobby", "gang", "diele", "entree"],
    "utility": ["utility", "storage", "store", "technik", "hwr", "closet", "keller", "abstell", "berging"],
    "stair": ["stair", "treppe", "trap"],
    "roof": ["roof", "dach", "attic", "galerie", "loft", "zolder"],
}


def categorize(name: str | None) -> str:
    n = (name or "").lower()
    for cat, keys in ROOM_CATEGORIES.items():
        if any(k in n for k in keys):
            return cat
    return "other"


@dataclass
class Storey:
    name: str
    elevation: float
    index: int


@dataclass
class Element:
    guid: str
    name: str
    storey: str
    footprint: Geom
    z_min: float
    z_max: float
    tag: str = ""

    @property
    def centroid(self) -> Point:
        return self.footprint.centroid

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.footprint.bounds


@dataclass
class Wall(Element):
    is_external: bool | None = None
    thickness: float = 0.0
    length: float = 0.0


@dataclass
class Space(Element):
    long_name: str = ""
    category: str = "other"
    area: float = 0.0
    height: float = 0.0

    @property
    def label(self) -> str:
        return self.long_name or self.name


@dataclass
class Opening(Element):
    kind: str = "door"  # "door" | "window"
    type_name: str = ""
    width: float = 0.0
    height: float = 0.0
    is_external: bool | None = None
    host_wall: str | None = None  # wall guid


@dataclass
class Model:
    path: Path
    schema: str
    ifc: ifcopenshell.file
    storeys: list[Storey]
    walls: list[Wall] = field(default_factory=list)
    spaces: list[Space] = field(default_factory=list)
    doors: list[Opening] = field(default_factory=list)
    windows: list[Opening] = field(default_factory=list)

    # --- queries -----------------------------------------------------------
    def storey(self, name: str) -> Storey:
        return next(s for s in self.storeys if s.name == name)

    def walls_on(self, storey: str) -> list[Wall]:
        return _on(self.walls, storey)

    def spaces_on(self, storey: str) -> list[Space]:
        return _on(self.spaces, storey)

    def doors_on(self, storey: str) -> list[Opening]:
        return _on(self.doors, storey)

    def windows_on(self, storey: str) -> list[Opening]:
        return _on(self.windows, storey)

    def openings_on(self, storey: str) -> list[Opening]:
        return self.doors_on(storey) + self.windows_on(storey)

    def plan_footprints(self, storey: str) -> list[Geom]:
        """Wall and space footprints of the storey — the built extent in plan."""
        return [w.footprint for w in self.walls_on(storey)] + [s.footprint for s in self.spaces_on(storey)]

    def spaces_touching(self, el: Element, buffer: float = 0.35) -> list[Space]:
        """Spaces on the same storey whose footprint overlaps the element (buffered).

        Openings probe at least their host wall's thickness so a window set in the
        outer leaf of a thick wall still finds the room behind it."""
        host = getattr(el, "host_wall", None)
        if host:
            wall = next((w for w in self.walls if w.guid == host), None)
            if wall is not None:
                buffer = max(buffer, wall.thickness + 0.1)
        probe = el.footprint.buffer(buffer)
        hits = [(s, probe.intersection(s.footprint).area) for s in self.spaces_on(el.storey)]
        hits = [(s, a) for s, a in hits if a > 1e-4]
        hits.sort(key=lambda t: -t[1])
        return [s for s, _ in hits]

    def drawable_storeys(self) -> list[Storey]:
        return [s for s in self.storeys if self.walls_on(s.name)]


def _on(items: list, storey: str) -> list:
    return [i for i in items if i.storey == storey]


# --- loading ---------------------------------------------------------------

def _geom_settings() -> ifcopenshell.geom.settings:
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def _footprint(settings, el) -> tuple[Geom, float, float] | None:
    """XY projection of the element's 3D shape as a (multi)polygon, plus z range."""
    try:
        shape = ifcopenshell.geom.create_shape(settings, el)
    except Exception:
        return None
    v, fc = shape.geometry.verts, shape.geometry.faces
    pts = [(v[i], v[i + 1], v[i + 2]) for i in range(0, len(v), 3)]
    tris = []
    for i in range(0, len(fc), 3):
        a, b, c = pts[fc[i]], pts[fc[i + 1]], pts[fc[i + 2]]
        p = Polygon([a[:2], b[:2], c[:2]])
        if p.area > 1e-9:
            tris.append(p)
    if not tris:
        return None
    g = union(tris).buffer(0)
    if g.is_empty:
        return None
    zs = [p[2] for p in pts]
    return g, min(zs), max(zs)


def _storey_name(el) -> str:
    c = ue.get_container(el) or ue.get_aggregate(el)
    while c is not None and not c.is_a("IfcBuildingStorey"):
        c = ue.get_container(c) or ue.get_aggregate(c)
    return c.Name if c is not None else "?"


def _pset_bool(el, pset: str, prop: str) -> bool | None:
    v = ue.get_psets(el).get(pset, {}).get(prop)
    return None if v is None else bool(v)


def _qto_area(el) -> float | None:
    q = ue.get_psets(el, qtos_only=True).get("Qto_SpaceBaseQuantities", {})
    for key in ("NetFloorArea", "GrossFloorArea"):
        if q.get(key):
            return float(q[key])
    return None


def _host_wall(el) -> str | None:
    try:
        opening = el.FillsVoids[0].RelatingOpeningElement
        return opening.VoidsElements[0].RelatingBuildingElement.GlobalId
    except Exception:
        return None


def _assign_tags(model: Model) -> None:
    order = {s.name: s.index for s in model.storeys}

    def key(e: Element):
        c = e.centroid
        return (order.get(e.storey, 99), round(c.y, 1), round(c.x, 1))

    for prefix, items in (("R", model.spaces), ("D", model.doors), ("W", model.windows)):
        for i, e in enumerate(sorted(items, key=key), start=1):
            e.tag = f"{prefix}-{i:02d}"


def load(path: str | Path) -> Model:
    path = Path(path)
    f = ifcopenshell.open(str(path))
    settings = _geom_settings()

    storeys = [
        Storey(s.Name or f"Storey {i}", float(s.Elevation or 0.0), i)
        for i, s in enumerate(sorted(f.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0.0))
    ]
    model = Model(path=path, schema=f.schema, ifc=f, storeys=storeys)

    for el in f.by_type("IfcWall"):  # includes IfcWallStandardCase
        fp = _footprint(settings, el)
        if not fp:
            continue
        g, z0, z1 = fp
        t, L = rect_dims(g)
        model.walls.append(Wall(el.GlobalId, el.Name or "", _storey_name(el), g, z0, z1,
                                is_external=_pset_bool(el, "Pset_WallCommon", "IsExternal"),
                                thickness=t, length=L))

    for el in f.by_type("IfcSpace"):
        fp = _footprint(settings, el)
        if not fp:
            continue
        g, z0, z1 = fp
        long_name = getattr(el, "LongName", None) or ""
        model.spaces.append(Space(el.GlobalId, el.Name or "", _storey_name(el), g, z0, z1,
                                  long_name=long_name, category=categorize(long_name or el.Name),
                                  area=_qto_area(el) or g.area, height=z1 - z0))

    for cls, kind, pset in (("IfcDoor", "door", "Pset_DoorCommon"), ("IfcWindow", "window", "Pset_WindowCommon")):
        for el in f.by_type(cls):
            fp = _footprint(settings, el)
            if not fp:
                continue
            g, z0, z1 = fp
            t, L = rect_dims(g)
            typ = ue.get_type(el)
            op = Opening(el.GlobalId, el.Name or "", _storey_name(el), g, z0, z1,
                         kind=kind, type_name=(typ.Name if typ is not None else "") or "",
                         width=float(getattr(el, "OverallWidth", None) or L),
                         height=float(getattr(el, "OverallHeight", None) or (z1 - z0)),
                         is_external=_pset_bool(el, pset, "IsExternal"), host_wall=_host_wall(el))
            (model.doors if kind == "door" else model.windows).append(op)

    _infer_external(model)
    _assign_tags(model)
    return model


def _infer_external(model: Model, tol: float = 0.03) -> None:
    """Fill in IsExternal where the IFC lacks Pset_*Common.

    A wall is external if its footprint lies on the outer boundary of the
    storey's built envelope. An opening inherits from its host wall; if the
    host is unknown it is external when it sits within 25 cm of that boundary.
    """
    walls_by_guid = {w.guid: w for w in model.walls}
    for st in model.storeys:
        walls = model.walls_on(st.name)
        if not walls:
            continue
        envelope = union(model.plan_footprints(st.name)).buffer(tol).buffer(-tol)
        outer = union([p.exterior for p in parts(envelope)]).buffer(tol)
        for w in walls:
            if w.is_external is None:
                w.is_external = w.footprint.boundary.intersection(outer).length > 0.3
        for op in model.openings_on(st.name):
            if op.is_external is not None:
                continue
            host = walls_by_guid.get(op.host_wall or "")
            if host is not None and host.is_external is not None:
                op.is_external = host.is_external
            else:
                op.is_external = op.footprint.buffer(0.25).intersects(outer)
