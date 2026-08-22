"""Builders for synthetic in-memory models.

The end-to-end suite (`test_pipeline.py`) uses the committed IFC files as its
fixtures. The unit suites use these builders instead: a hand-made rectangular
house lets a single function be exercised on geometry chosen for it — thick
walls, interior openings, rooms without doors — cases the two sample models do
not contain.
"""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import Polygon, box

from recognition import model as M

WALL_T = 0.3
WALL_H = 2.6


def storeys(*names: str) -> list[M.Storey]:
    return [M.Storey(n, 3.0 * i, i) for i, n in enumerate(names)]


def wall(guid: str, geom: Polygon, *, storey: str = "L0", is_external: bool | None = None,
         name: str = "") -> M.Wall:
    t, L = M._rect_dims(geom)
    return M.Wall(guid, name or guid, storey, geom, 0.0, WALL_H,
                  is_external=is_external, thickness=t, length=L)


def space(guid: str, geom: Polygon, *, storey: str = "L0", name: str = "Room", long_name: str = "",
          area: float | None = None, height: float = WALL_H, category: str | None = None) -> M.Space:
    label = long_name or name
    return M.Space(guid, name, storey, geom, 0.0, height, long_name=long_name,
                   category=category or M.categorize(label), area=area if area is not None else geom.area,
                   height=height)


def opening(guid: str, geom: Polygon, *, kind: str = "door", storey: str = "L0", width: float = 0.9,
            height: float = 2.0, is_external: bool | None = None, host_wall: str | None = None,
            name: str = "", type_name: str = "") -> M.Opening:
    return M.Opening(guid, name or guid, storey, geom, 0.0, height, kind=kind, type_name=type_name,
                     width=width, height=height, is_external=is_external, host_wall=host_wall)


def make_model(*, walls=(), spaces=(), doors=(), windows=(), storey_names=("L0",),
               path: str = "synthetic.ifc", schema: str = "IFC4") -> M.Model:
    return M.Model(path=Path(path), schema=schema, ifc=None, storeys=storeys(*storey_names),
                   walls=list(walls), spaces=list(spaces), doors=list(doors), windows=list(windows))


def rect_house(*, wall_thickness: float = WALL_T, storey: str = "L0") -> M.Model:
    """8 x 6 m box, split by an interior wall into a 5 m living room and a 2.5 m bath.

    Layout (metres, exterior faces at 0/8 and 0/6)::

        +---------------------+
        |  living   |  bath   |   <- interior wall at x = 5
        +---------------------+
             ^ door at x=2 in the south wall (external), window in the north wall

    The interior wall carries an interior door so opening classification,
    schedules and dimension chains all see both cases.
    """
    t = wall_thickness
    walls = [
        wall("W-S", box(0, 0, 8, t), storey=storey),
        wall("W-N", box(0, 6 - t, 8, 6), storey=storey),
        wall("W-W", box(0, 0, t, 6), storey=storey),
        wall("W-E", box(8 - t, 0, 8, 6), storey=storey),
        wall("W-I", box(5, t, 5 + t, 6 - t), storey=storey),
    ]
    spaces = [
        space("S-LIV", box(t, t, 5, 6 - t), storey=storey, name="Wohnen", category="living"),
        space("S-BAT", box(5 + t, t, 8 - t, 6 - t), storey=storey, name="Bad"),
    ]
    doors = [
        opening("D-EXT", box(2, 0, 3, t), storey=storey, width=1.0, host_wall="W-S"),
        opening("D-INT", box(5, 2, 5 + t, 2.9), storey=storey, width=0.9, host_wall="W-I"),
    ]
    windows = [
        opening("N-WIN", box(1.5, 6 - t, 3.5, 6), kind="window", storey=storey, width=2.0, height=1.4,
                host_wall="W-N"),
    ]
    return make_model(walls=walls, spaces=spaces, doors=doors, windows=windows, storey_names=(storey,))
