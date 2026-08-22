"""Design as code: describe a building in Python, get an IFC the pipeline accepts.

    from recognition.design import House

    h = House("My house")
    eg = h.storey("Erdgeschoss", elevation=0.0, height=2.5)
    eg.wall("W1", (0, 0), (12, 0), thickness=0.30, external=True)
    eg.room("Küche", [(0.3, 0.3), (4.7, 0.3), (4.7, 4.2), (0.3, 4.2)])
    eg.door("D1", on="W1", at=8.3, width=2.01, height=2.2, external=True)
    eg.window("F1", on="W1", at=1.5, width=2.0, height=1.2, sill=0.9)
    h.write("out/house.ifc")           # 3D: IfcWall / IfcSpace / IfcDoor / IfcWindow with real solids
    h.axonometric("out/house.png")     # a quick 3D view
    # then: recognition run out/house.ifc out/house   → 2D sheets, schedules, compliance

Coordinates are metres in the storey plane (x east, y north); walls are
centre-lines; `at` is the distance from the wall's start to the opening's
centre. The IFC is deliberately plain — extruded solids, openings cut into
walls, standard psets — so any viewer or CAD tool reads it and
``recognition.model.load`` gets the same walls, rooms, doors and windows
back. Roofs, slabs, stairs and materials are out of scope: this is the layout.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cairosvg
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import numpy as np
import svgwrite

run = ifcopenshell.api.run
Pt = tuple[float, float]


@dataclass
class Wall:
    name: str
    start: Pt
    end: Pt
    thickness: float
    height: float
    external: bool
    entity: ifcopenshell.entity_instance

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def direction(self) -> Pt:
        L = self.length
        return ((self.end[0] - self.start[0]) / L, (self.end[1] - self.start[1]) / L)

    @property
    def normal(self) -> Pt:
        d = self.direction
        return (-d[1], d[0])

    def footprint(self, extend: float = 0.0) -> list[Pt]:
        d, n, t = self.direction, self.normal, self.thickness / 2
        s = (self.start[0] - d[0] * extend, self.start[1] - d[1] * extend)
        e = (self.end[0] + d[0] * extend, self.end[1] + d[1] * extend)
        return [(s[0] + n[0] * t, s[1] + n[1] * t), (e[0] + n[0] * t, e[1] + n[1] * t),
                (e[0] - n[0] * t, e[1] - n[1] * t), (s[0] - n[0] * t, s[1] - n[1] * t)]

    def slot(self, at: float, width: float, depth: float) -> list[Pt]:
        """Rectangle on the wall axis centred `at` metres from the start, `width` along, `depth` across."""
        d, n = self.direction, self.normal
        c = (self.start[0] + d[0] * at, self.start[1] + d[1] * at)
        w, t = width / 2, depth / 2
        return [(c[0] - d[0] * w + n[0] * t, c[1] - d[1] * w + n[1] * t), (c[0] + d[0] * w + n[0] * t, c[1] + d[1] * w + n[1] * t),
                (c[0] + d[0] * w - n[0] * t, c[1] + d[1] * w - n[1] * t), (c[0] - d[0] * w - n[0] * t, c[1] - d[1] * w - n[1] * t)]


@dataclass
class Storey:
    house: "House"
    name: str
    elevation: float
    height: float
    entity: ifcopenshell.entity_instance
    walls: dict[str, Wall] = field(default_factory=dict)
    rooms: list[ifcopenshell.entity_instance] = field(default_factory=list)
    openings: list[ifcopenshell.entity_instance] = field(default_factory=list)

    def wall(self, name: str, start: Pt, end: Pt, thickness: float = 0.30, height: float | None = None,
             external: bool = False) -> Wall:
        if name in self.walls:
            raise ValueError(f"wall {name!r} already exists on {self.name}")
        h = height or self.height
        ent = self.house._product("IfcWall", name)
        wall = Wall(name, tuple(start), tuple(end), thickness, h, external, ent)
        self.house._solid(ent, wall.footprint(extend=thickness / 2), self.elevation, h)
        run("spatial.assign_container", self.house.f, relating_structure=self.entity, products=[ent])
        self.house._pset(ent, "Pset_WallCommon", {"IsExternal": external, "LoadBearing": external})
        self.walls[name] = wall
        return wall

    def room(self, name: str, polygon: list[Pt], height: float | None = None, tag: str | None = None) -> ifcopenshell.entity_instance:
        """A room as its floor outline. The name drives the category (Küche → kitchen …)."""
        ent = self.house._product("IfcSpace", tag or name)
        ent.LongName = name
        ent.PredefinedType = "INTERNAL"
        self.house._solid(ent, list(polygon), self.elevation, height or self.height)
        run("aggregate.assign_object", self.house.f, relating_object=self.entity, products=[ent])
        self.rooms.append(ent)
        return ent

    def door(self, name: str, on: str, at: float, width: float = 0.885, height: float = 2.01, sill: float = 0.0,
             external: bool | None = None, type_name: str = "") -> ifcopenshell.entity_instance:
        return self._opening("IfcDoor", name, on, at, width, height, sill, external, type_name)

    def window(self, name: str, on: str, at: float, width: float = 1.2, height: float = 1.2, sill: float = 0.9,
               external: bool | None = None, type_name: str = "") -> ifcopenshell.entity_instance:
        return self._opening("IfcWindow", name, on, at, width, height, sill, external, type_name)

    def _opening(self, ifc_class, name, on, at, width, height, sill, external, type_name):
        wall = self.walls.get(on)
        if wall is None:
            raise ValueError(f"no wall {on!r} on {self.name}; have {sorted(self.walls)}")
        if not 0 < at < wall.length:
            raise ValueError(f"{name}: at={at} is outside wall {on} (length {wall.length:.2f})")
        f = self.house.f
        z = self.elevation + sill
        hole = self.house._product("IfcOpeningElement", f"{name} opening")
        self.house._solid(hole, wall.slot(at, width, wall.thickness + 0.04), z, height)
        run("feature.add_feature", f, feature=hole, element=wall.entity)
        ent = self.house._product(ifc_class, name)
        self.house._solid(ent, wall.slot(at, width, max(0.05, wall.thickness / 2)), z, height)
        ent.OverallWidth, ent.OverallHeight = float(width), float(height)
        if ifc_class == "IfcDoor":
            ent.PredefinedType = "DOOR"
        run("feature.add_filling", f, opening=hole, element=ent)
        run("spatial.assign_container", f, relating_structure=self.entity, products=[ent])
        if type_name:
            typ = run("root.create_entity", f, ifc_class=ifc_class + "Type", name=type_name)
            run("type.assign_type", f, related_objects=[ent], relating_type=typ)
        self.house._pset(ent, "Pset_DoorCommon" if ifc_class == "IfcDoor" else "Pset_WindowCommon",
                         {"IsExternal": wall.external if external is None else external})
        self.openings.append(ent)
        return ent


class House:
    def __init__(self, name: str, schema: str = "IFC4"):
        self.name = name
        f = self.f = run("project.create_file", version=schema)
        self.project = run("root.create_entity", f, ifc_class="IfcProject", name=name)
        run("unit.assign_unit", f)  # SI: metres
        ctx = run("context.add_context", f, context_type="Model")
        self.body = run("context.add_context", f, context_type="Model", context_identifier="Body",
                        target_view="MODEL_VIEW", parent=ctx)
        self.site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
        self.building = run("root.create_entity", f, ifc_class="IfcBuilding", name=name)
        run("aggregate.assign_object", f, relating_object=self.project, products=[self.site])
        run("aggregate.assign_object", f, relating_object=self.site, products=[self.building])
        self.storeys: list[Storey] = []

    # --- authoring -------------------------------------------------------

    def storey(self, name: str, elevation: float = 0.0, height: float = 2.5) -> Storey:
        ent = run("root.create_entity", self.f, ifc_class="IfcBuildingStorey", name=name)
        ent.Elevation = float(elevation)
        run("aggregate.assign_object", self.f, relating_object=self.building, products=[ent])
        st = Storey(self, name, float(elevation), float(height), ent)
        self.storeys.append(st)
        return st

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f.write(str(path))
        return path

    def axonometric(self, path: str | Path, scale: float = 40.0) -> Path:
        return axonometric(self.f, path, scale=scale, title=self.name)

    # --- ifc plumbing ------------------------------------------------------

    def _product(self, ifc_class: str, name: str):
        return run("root.create_entity", self.f, ifc_class=ifc_class, name=name)

    def _solid(self, product, polygon: list[Pt], z: float, height: float) -> None:
        pts = [(float(x), float(y)) for x, y in polygon]
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        profile = run("profile.add_arbitrary_profile", self.f, profile=pts, name=product.Name)
        rep = run("geometry.add_profile_representation", self.f, context=self.body, profile=profile, depth=float(height))
        m = np.eye(4)
        m[2, 3] = float(z)
        run("geometry.edit_object_placement", self.f, product=product, matrix=m)
        run("geometry.assign_representation", self.f, product=product, representation=rep)

    def _pset(self, product, name: str, props: dict) -> None:
        pset = run("pset.add_pset", self.f, product=product, name=name)
        run("pset.edit_pset", self.f, pset=pset, properties=props)


# --- a quick 3D view ----------------------------------------------------------

COLOURS = {"IfcWall": "#6B7480", "IfcDoor": "#B5651D", "IfcWindow": "#2F6FE4", "IfcSpace": "#DCE6F5"}


def axonometric(ifc: ifcopenshell.file | str | Path, path: str | Path, scale: float = 40.0, title: str = "") -> Path:
    """Isometric projection of walls, doors and windows (rooms as floor tints), painter-sorted. PNG via SVG."""
    f = ifc if isinstance(ifc, ifcopenshell.file) else ifcopenshell.open(str(ifc))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    c30, s30 = math.cos(math.radians(30)), math.sin(math.radians(30))
    faces = []  # (depth, points2d, colour, shade)
    for cls, colour in COLOURS.items():
        for el in f.by_type(cls):
            try:
                shape = ifcopenshell.geom.create_shape(settings, el)
            except Exception:
                continue
            v, fc = shape.geometry.verts, shape.geometry.faces
            pts = [(v[i], v[i + 1], v[i + 2]) for i in range(0, len(v), 3)]
            if cls == "IfcSpace":  # floor only
                z0 = min(p[2] for p in pts)
                pts = [p for p in pts if abs(p[2] - z0) < 1e-6]
            for i in range(0, len(fc), 3):
                tri = [pts[fc[i]], pts[fc[i + 1]], pts[fc[i + 2]]] if cls != "IfcSpace" else None
                if tri is None:
                    break
                a, b, c = (np.array(p) for p in tri)
                n = np.cross(b - a, c - a)
                if np.linalg.norm(n) < 1e-9:
                    continue
                n = n / np.linalg.norm(n)
                shade = 0.62 + 0.38 * max(0.0, float(np.dot(n, [0.3, -0.5, 0.81])))
                faces.append((sum(p[0] + p[1] + p[2] * 0.5 for p in tri), tri, colour, shade))
            if cls == "IfcSpace" and pts:
                xs = sorted(set(pts))
                from shapely.geometry import MultiPoint
                hull = MultiPoint([(p[0], p[1]) for p in xs]).convex_hull
                if hull.geom_type == "Polygon":
                    z0 = pts[0][2]
                    poly = [(x, y, z0 + 0.01) for x, y in hull.exterior.coords]
                    faces.append((-1e9, poly, colour, 1.0))

    def proj(p):
        return ((p[0] - p[1]) * c30 * scale, -((p[0] + p[1]) * s30 + p[2]) * scale)

    faces.sort(key=lambda t: t[0])
    projected = [([proj(p) for p in poly], col, sh) for _, poly, col, sh in faces]
    xs = [x for poly, _, _ in projected for x, _ in poly]
    ys = [y for poly, _, _ in projected for _, y in poly]
    pad = 30
    minx, miny = min(xs) - pad, min(ys) - pad
    W, H = max(xs) - minx + pad, max(ys) - miny + pad + (28 if title else 0)
    dwg = svgwrite.Drawing(size=(W, H))
    dwg.add(dwg.rect((0, 0), (W, H), fill="white"))
    for poly, col, sh in projected:
        r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
        fill = f"rgb({int(r * sh)},{int(g * sh)},{int(b * sh)})"
        dwg.add(dwg.polygon([(x - minx, y - miny) for x, y in poly], fill=fill, stroke=fill, stroke_width=0.4))
    if title:
        dwg.add(dwg.text(title, insert=(pad, H - 10), font_size=13, font_family="Helvetica, Arial, sans-serif", fill="#59646E"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=dwg.tostring().encode("utf-8"), write_to=str(path), background_color="white")
    return path
