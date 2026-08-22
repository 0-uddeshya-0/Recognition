"""Triangulate an IFC model into JSON the browser can draw.

Adapted from the Studio viewer on the `studio` branch, moved out of the FastAPI
app and into the pipeline. That move is the point: meshing at *artifact* time,
not at view time, is what lets the Studio be a static file reading a static file.
No server runs when someone looks at a building.

The JSON keeps each element separate and carries its tag, class and storey, so
the viewer can colour walls differently from openings and show a room's tag on
hover without re-deriving anything from the IFC.
"""
from __future__ import annotations

import json
from pathlib import Path

import ifcopenshell.geom

from . import model as M


def _settings() -> ifcopenshell.geom.settings:
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)      # so element coords compose without transforms
    return s


def _triangles(settings, entity) -> tuple[list[float], list[int]] | None:
    """Vertices and faces for one element, or None if it has no drawable shape."""
    try:
        shape = ifcopenshell.geom.create_shape(settings, entity)
    except Exception:
        # An element without a representation is normal (a space can be a volume
        # with no body). Skipping it is correct; failing the build is not.
        return None
    verts = [round(v, 4) for v in shape.geometry.verts]
    faces = [int(i) for i in shape.geometry.faces]
    return (verts, faces) if verts and faces else None


def build(model_path: str | Path) -> dict:
    """Mesh every wall, space, door and window, tagged as in the schedules."""
    m = M.load(Path(model_path))
    settings = _settings()
    elements: list[dict] = []
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3

    groups = (
        ("IfcWall", m.walls, lambda e: e.name),
        ("IfcSpace", m.spaces, lambda e: e.label),
        ("IfcDoor", m.doors, lambda e: e.name),
        ("IfcWindow", m.windows, lambda e: e.name),
    )
    for cls, items, name_of in groups:
        for el in items:
            tri = _triangles(settings, m.ifc.by_guid(el.guid))
            if tri is None:
                continue
            verts, faces = tri
            for i in range(0, len(verts), 3):
                for k in range(3):
                    v = verts[i + k]
                    lo[k] = min(lo[k], v)
                    hi[k] = max(hi[k], v)
            entry = {
                "tag": el.tag, "name": name_of(el), "cls": cls,
                "storey": el.storey, "verts": verts, "faces": faces,
            }
            if cls == "IfcSpace":
                entry["area"] = round(getattr(el, "area", 0.0), 2)
                entry["category"] = getattr(el, "category", "other")
            elements.append(entry)

    bounds = [*lo, *hi] if elements else [0.0] * 6
    return {"elements": elements, "bounds": bounds}


def write(model_path: str | Path, out_path: str | Path) -> Path:
    """Build the mesh and write it compactly — this file ships to the browser."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(build(model_path), separators=(",", ":")), encoding="utf-8")
    return p
