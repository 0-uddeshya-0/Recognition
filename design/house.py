"""A small house, written as code.

    uv run python design/house.py                 # → out/design/house.ifc
    uv run recognition run out/design/house.ifc out/design/pkg --project Haus-am-Hang

Change a number, rerun: new 3D model, new 2D sheets, new compliance report.
Layout loosely follows the FZK-Haus ground floor (12 × 10 m, six rooms).
"""
import sys
from pathlib import Path

from recognition.design import House

h = House("Haus am Hang")
eg = h.storey("Erdgeschoss", elevation=0.0, height=2.5)

# external walls, 30 cm, clockwise from the south-west corner (centre-lines on the 12 × 10 m outline)
eg.wall("S", (0.0, 0.0), (12.0, 0.0), thickness=0.30, external=True)
eg.wall("E", (12.0, 0.0), (12.0, 10.0), thickness=0.30, external=True)
eg.wall("N", (12.0, 10.0), (0.0, 10.0), thickness=0.30, external=True)
eg.wall("W", (0.0, 10.0), (0.0, 0.0), thickness=0.30, external=True)

# internal walls, 15 cm
eg.wall("I1", (4.825, 0.15), (4.825, 4.275), thickness=0.15)    # Küche | Wohnen
eg.wall("I2", (0.15, 4.275), (11.85, 4.275), thickness=0.15)    # south side of Flur and Schlafzimmer
eg.wall("I3", (7.375, 4.275), (7.375, 9.85), thickness=0.15)    # Flur + Bad | Schlafzimmer
eg.wall("I4", (0.15, 5.925), (7.375, 5.925), thickness=0.15)    # Flur | Büro + Bad
eg.wall("I5", (3.625, 5.925), (3.625, 9.85), thickness=0.15)    # Büro | Bad

# rooms as floor outlines (inside faces of the walls)
eg.room("Küche",        [(0.15, 0.15), (4.75, 0.15), (4.75, 4.2), (0.15, 4.2)])
eg.room("Wohnen",       [(4.9, 0.15), (11.85, 0.15), (11.85, 4.2), (4.9, 4.2)])
eg.room("Flur",         [(0.15, 4.35), (7.3, 4.35), (7.3, 5.85), (0.15, 5.85)])
eg.room("Schlafzimmer", [(7.45, 4.35), (11.85, 4.35), (11.85, 9.85), (7.45, 9.85)])
eg.room("Büro",         [(0.15, 6.0), (3.55, 6.0), (3.55, 9.85), (0.15, 9.85)])
eg.room("Bad",          [(3.7, 6.0), (7.3, 6.0), (7.3, 9.85), (3.7, 9.85)])

# doors: `at` = metres from the wall's start to the door centre
eg.door("Haustür",     on="W",  at=4.9, width=1.01, height=2.10, type_name="Eingangstür")        # W runs north→south
eg.door("Terrassentür", on="S", at=8.3, width=2.01, height=2.20, type_name="Schiebetür")
eg.door("Tür Küche",   on="I1", at=2.2, width=0.885, height=2.01, type_name="Innentür")
eg.door("Tür Schlafen", on="I3", at=0.8, width=0.885, height=2.01, type_name="Innentür")
eg.door("Tür Büro",    on="I4", at=1.9, width=0.885, height=2.01, type_name="Innentür")
eg.door("Tür Bad",     on="I4", at=5.5, width=0.885, height=2.01, type_name="Innentür")

# windows, 2.0 × 1.2 m, sill at 0.9 m
for name, wall, at in [("F1", "S", 2.4), ("F2", "S", 10.4), ("F3", "E", 2.2), ("F4", "E", 7.1),
                       ("F5", "N", 2.4), ("F6", "N", 6.5), ("F7", "N", 10.2), ("F8", "W", 2.1), ("F9", "W", 7.8)]:
    eg.window(name, on=wall, at=at, width=2.0, height=1.2, sill=0.9, type_name="Fenster 2-flg.")

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("out/design/house.ifc")
    h.write(out)
    print(f"wrote {out}")
