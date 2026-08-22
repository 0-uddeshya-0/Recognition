"""Triangle meshes for the 3D viewer.

One JSON document per package: every wall, room, door and window of the model
the package was generated from, triangulated by ifcopenshell in world
coordinates, tagged with the same R-xx / D-xx / W-xx tags as the schedules
(so the viewer can colour the failing elements the report names). Built on
first request and cached next to the package as ``mesh.json``.

    {"elements": [{"tag": "R-04", "name": "Schlafzimmer", "cls": "IfcSpace", "storey": "Erdgeschoss",
                   "verts": [x, y, z, ...], "faces": [i, j, k, ...]}, ...],
     "bounds": [minx, miny, minz, maxx, maxy, maxz]}
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import ifcopenshell.geom

from recognition import model as M

MESH_FILE = "mesh.json"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _settings() -> ifcopenshell.geom.settings:
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def _triangles(settings, entity) -> tuple[list[float], list[int]] | None:
    try:
        shape = ifcopenshell.geom.create_shape(settings, entity)
    except Exception:
        return None
    verts = [round(v, 4) for v in shape.geometry.verts]
    faces = [int(i) for i in shape.geometry.faces]
    return (verts, faces) if verts and faces else None


def build_mesh(model_path: Path) -> dict:
    """Mesh every wall, space, door and window of the model, tags as in the schedules."""
    m = M.load(model_path)
    settings = _settings()
    elements: list[dict] = []
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    groups = (("IfcWall", m.walls, lambda e: e.name), ("IfcSpace", m.spaces, lambda e: e.label),
              ("IfcDoor", m.doors, lambda e: e.name), ("IfcWindow", m.windows, lambda e: e.name))
    for cls, items, name_of in groups:
        for el in items:
            tri = _triangles(settings, m.ifc.by_guid(el.guid))
            if tri is None:
                continue
            verts, faces = tri
            for i in range(0, len(verts), 3):
                for k in range(3):
                    v = verts[i + k]
                    lo[k] = v if v < lo[k] else lo[k]
                    hi[k] = v if v > hi[k] else hi[k]
            elements.append({"tag": el.tag, "name": name_of(el), "cls": cls, "storey": el.storey,
                             "verts": verts, "faces": faces})
    bounds = [*lo, *hi] if elements else [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return {"elements": elements, "bounds": bounds}


def mesh_json(model_path: Path, out_dir: Path) -> Path:
    """Path of <out_dir>/mesh.json, building it from the model on first call."""
    target = out_dir / MESH_FILE
    if target.is_file():
        return target
    with _locks_guard:
        lock = _locks.setdefault(str(target), threading.Lock())
    with lock:  # two viewers asking at once build once
        if target.is_file():
            return target
        data = build_mesh(model_path)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, target)
    return target
