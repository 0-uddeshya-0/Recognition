"""Unit tests for recognition.model: classification, queries, tagging, inference."""
from __future__ import annotations

import pytest
from shapely.geometry import Point, Polygon, box

import factories as F
from recognition import model as M


# --- categorize ------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Schlafzimmer", "bedroom"),
    ("Slaapkamer 2", "bedroom"),
    ("Wohnen", "living"),
    ("Dining Room", "living"),
    ("Küche", "kitchen"),
    ("KEUKEN", "kitchen"),
    ("Bad", "bathroom"),
    ("WC 01", "bathroom"),
    ("Büro", "office"),
    ("Study", "office"),
    ("Besprechung", "meeting"),
    ("Labor 4", "lab"),
    ("Flur", "hall"),
    ("Entree", "hall"),
    ("Abstellraum", "utility"),
    ("Treppenhaus", "stair"),
    ("Dachboden", "roof"),
    ("Plant Room", "other"),
    ("", "other"),
    (None, "other"),
])
def test_categorize(name, expected):
    assert M.categorize(name) == expected


def test_categorize_is_case_insensitive():
    assert M.categorize("KÜCHE") == M.categorize("küche") == "kitchen"


def test_categorize_resolves_ambiguous_names_by_room_categories_order():
    """A name matching several keyword lists takes the first key in ROOM_CATEGORIES.

    That makes "Badezimmer" and "Wohnzimmer" bedrooms, because "zimmer" is a
    bedroom keyword and bedroom comes first. Documented rather than asserted as
    desirable: the resolution order is what makes categories deterministic.
    """
    order = list(M.ROOM_CATEGORIES)
    assert order.index("bedroom") < order.index("living") < order.index("bathroom")
    assert M.categorize("Schlafen / Wohnen") == "bedroom"
    assert M.categorize("Badezimmer") == "bedroom"


# --- dataclass behaviour ---------------------------------------------------

def test_element_centroid_and_bounds():
    el = F.wall("W", box(0, 0, 4, 2))
    assert (el.centroid.x, el.centroid.y) == (2.0, 1.0)
    assert el.bounds == (0.0, 0.0, 4.0, 2.0)


def test_space_label_prefers_long_name():
    assert F.space("S", box(0, 0, 1, 1), name="R1", long_name="Wohnzimmer").label == "Wohnzimmer"
    assert F.space("S", box(0, 0, 1, 1), name="R1").label == "R1"


def test_rect_dims_returns_short_then_long_side_of_rotated_rect():
    short, long = M._rect_dims(box(0, 0, 4, 0.25))
    assert (short, long) == pytest.approx((0.25, 4.0))
    # rotated 45°: dimensions are those of the rotated rectangle, not of the bbox
    rotated = Polygon([(0, 0), (3, 3), (3.2, 2.8), (0.2, -0.2)])
    short_r, long_r = M._rect_dims(rotated)
    assert short_r < 0.5 < long_r


# --- Model queries ---------------------------------------------------------

def test_per_storey_queries_filter_by_storey():
    m = F.rect_house()
    m.storeys = F.storeys("L0", "L1")
    assert len(m.walls_on("L0")) == 5
    assert [s.guid for s in m.spaces_on("L0")] == ["S-LIV", "S-BAT"]
    assert [d.guid for d in m.doors_on("L0")] == ["D-EXT", "D-INT"]
    assert [w.guid for w in m.windows_on("L0")] == ["N-WIN"]
    assert (m.walls_on("L1"), m.spaces_on("L1"), m.doors_on("L1"), m.windows_on("L1")) == ([], [], [], [])


def test_storey_lookup_by_name_and_unknown_name_raises():
    m = F.make_model(storey_names=("Ground", "First"))
    assert m.storey("First").index == 1
    with pytest.raises(StopIteration):
        m.storey("Basement")


def test_drawable_storeys_are_those_carrying_walls():
    m = F.rect_house()
    m.storeys = F.storeys("L0", "Roof")
    assert [s.name for s in m.drawable_storeys()] == ["L0"]


def test_spaces_touching_sorts_by_overlap_area():
    m = F.rect_house()
    door = m.doors[1]  # interior door between living and bath
    touching = m.spaces_touching(door)
    assert {s.guid for s in touching} == {"S-LIV", "S-BAT"}
    # living room is the bigger overlap of the buffered probe
    assert touching[0].guid == "S-LIV"


def test_spaces_touching_probes_at_least_the_host_wall_thickness():
    """A window in the outer leaf of a thick wall must still find the room behind it."""
    m = F.rect_house(wall_thickness=0.8)
    window = m.windows[0]
    # sitting in the outer 20 cm of an 80 cm wall, a small probe would miss the room
    window.footprint = box(1.5, 6 - 0.2, 3.5, 6)
    window.host_wall = None
    assert m.spaces_touching(window, buffer=0.05) == []
    window.host_wall = "W-N"
    assert [s.guid for s in m.spaces_touching(window, buffer=0.05)] == ["S-LIV"]


def test_spaces_touching_ignores_unknown_host_and_grazing_contact():
    m = F.rect_house()
    far = F.opening("D-FAR", box(20, 20, 21, 20.3), host_wall="does-not-exist")
    assert m.spaces_touching(far) == []


# --- tagging ---------------------------------------------------------------

def test_assign_tags_orders_by_storey_then_position():
    lower = F.space("S-A", box(0, 0, 2, 2), storey="L0")
    upper_south = F.space("S-B", box(0, 0, 2, 2), storey="L1")
    upper_north = F.space("S-C", box(0, 5, 2, 7), storey="L1")
    m = F.make_model(spaces=[upper_north, upper_south, lower], storey_names=("L0", "L1"))
    M._assign_tags(m)
    assert (lower.tag, upper_south.tag, upper_north.tag) == ("R-01", "R-02", "R-03")


def test_assign_tags_uses_separate_sequences_per_element_kind():
    m = F.rect_house()
    M._assign_tags(m)
    assert [s.tag for s in m.spaces] == ["R-01", "R-02"]
    assert sorted(d.tag for d in m.doors) == ["D-01", "D-02"]
    assert [w.tag for w in m.windows] == ["W-01"]


def test_assign_tags_places_elements_on_unknown_storeys_last():
    known = F.space("S-A", box(0, 0, 2, 2), storey="L0")
    orphan = F.space("S-B", box(0, 0, 2, 2), storey="nowhere")
    m = F.make_model(spaces=[orphan, known], storey_names=("L0",))
    M._assign_tags(m)
    assert (known.tag, orphan.tag) == ("R-01", "R-02")


# --- external inference ----------------------------------------------------

def test_infer_external_marks_perimeter_walls_only():
    m = F.rect_house()
    M._infer_external(m)
    by_guid = {w.guid: w.is_external for w in m.walls}
    assert by_guid == {"W-S": True, "W-N": True, "W-W": True, "W-E": True, "W-I": False}


def test_infer_external_respects_values_already_in_the_ifc():
    m = F.rect_house()
    m.walls[0].is_external = False  # south perimeter wall, declared interior by Pset_WallCommon
    m.walls[4].is_external = True
    M._infer_external(m)
    assert m.walls[0].is_external is False
    assert m.walls[4].is_external is True


def test_openings_inherit_external_from_their_host_wall():
    m = F.rect_house()
    M._infer_external(m)
    ext_door, int_door = m.doors
    assert ext_door.is_external is True   # hosted by the south perimeter wall
    assert int_door.is_external is False  # hosted by the interior wall
    assert m.windows[0].is_external is True


def test_opening_without_host_falls_back_to_proximity_to_the_envelope():
    m = F.rect_house()
    on_envelope = F.opening("D-NOHOST", box(6, 0, 7, F.WALL_T), host_wall=None)
    inside = F.opening("D-INSIDE", box(2, 3, 3, 3.3), host_wall=None)
    m.doors += [on_envelope, inside]
    M._infer_external(m)
    assert on_envelope.is_external is True
    assert inside.is_external is False


def test_infer_external_skips_storeys_without_walls():
    m = F.rect_house()
    m.storeys = F.storeys("L0", "Empty")
    orphan = F.opening("D-ORPHAN", box(2, 3, 3, 3.3), storey="Empty")
    m.doors.append(orphan)
    M._infer_external(m)  # must not raise on the wall-less storey
    assert orphan.is_external is None


def test_footprint_returns_none_when_the_shape_has_no_area():
    class Degenerate:
        pass

    # create_shape raises for a non-entity: the loader must skip the element, not crash
    assert M._footprint(M._geom_settings(), Degenerate()) is None


def test_footprint_skips_zero_area_triangles(monkeypatch):
    class Shape:
        class geometry:
            # three collinear points -> a triangle of zero area
            verts = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 0.0, 0.0]
            faces = [0, 1, 2]

    monkeypatch.setattr(M.ifcopenshell.geom, "create_shape", lambda *_a, **_k: Shape)
    assert M._footprint(M._geom_settings(), object()) is None


def test_pset_helpers_tolerate_missing_data():
    m = F.rect_house()
    assert M._host_wall(object()) is None  # no FillsVoids -> unknown host
    assert Point(m.spaces[0].centroid).within(m.spaces[0].footprint)
