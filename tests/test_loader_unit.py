"""Unit tests for the IFC-facing side of recognition.model.

The sample models exercise `load` on real geometry; these tests build tiny IFC
files instead, for the cases the samples do not contain: elements without a
shape, an element nested two containers deep, declared IsExternal flags and
Qto_SpaceBaseQuantities areas.
"""
from __future__ import annotations

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element as ue
import pytest

from recognition import model as M


def api(_action, _file, **kw):
    return ifcopenshell.api.run(_action, _file, **kw)


@pytest.fixture
def ifc(tmp_path):
    """A shape-less IFC4 building: project > site > building > storey."""
    f = ifcopenshell.file(schema="IFC4")
    api("root.create_entity", f, ifc_class="IfcProject", name="P")
    api("unit.assign_unit", f)
    site = api("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = api("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    storey = api("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 1")
    storey.Elevation = 0.0
    api("aggregate.assign_object", f, products=[site], relating_object=f.by_type("IfcProject")[0])
    api("aggregate.assign_object", f, products=[building], relating_object=site)
    api("aggregate.assign_object", f, products=[storey], relating_object=building)
    return f, storey


def write(f, tmp_path):
    path = tmp_path / "minimal.ifc"
    f.write(str(path))
    return path


def test_load_skips_elements_without_geometry(ifc, tmp_path):
    f, storey = ifc
    for cls in ("IfcWall", "IfcDoor", "IfcWindow"):
        el = api("root.create_entity", f, ifc_class=cls, name=cls)
        api("spatial.assign_container", f, products=[el], relating_structure=storey)
    space = api("root.create_entity", f, ifc_class="IfcSpace", name="S")
    api("aggregate.assign_object", f, products=[space], relating_object=storey)

    model = M.load(write(f, tmp_path))
    assert [s.name for s in model.storeys] == ["Level 1"]
    assert (model.walls, model.spaces, model.doors, model.windows) == ([], [], [], [])
    assert model.drawable_storeys() == []


def test_load_reads_the_schema_and_names_unnamed_storeys(ifc, tmp_path):
    f, storey = ifc
    storey.Name = None
    model = M.load(write(f, tmp_path))
    assert model.schema == "IFC4"
    assert [s.name for s in model.storeys] == ["Storey 0"]


def test_load_orders_storeys_by_elevation(ifc, tmp_path):
    f, ground = ifc
    upper = api("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Level 2")
    upper.Elevation = 3.0
    basement = api("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Basement")
    basement.Elevation = -2.5
    building = f.by_type("IfcBuilding")[0]
    api("aggregate.assign_object", f, products=[upper, basement], relating_object=building)

    model = M.load(write(f, tmp_path))
    assert [(s.name, s.elevation, s.index) for s in model.storeys] == [
        ("Basement", -2.5, 0), ("Level 1", 0.0, 1), ("Level 2", 3.0, 2)]


def test_storey_name_walks_up_through_nested_containers(ifc, tmp_path):
    """A door aggregated into an assembly that sits in the storey still resolves."""
    f, storey = ifc
    assembly = api("root.create_entity", f, ifc_class="IfcElementAssembly", name="Curtain wall")
    api("spatial.assign_container", f, products=[assembly], relating_structure=storey)
    door = api("root.create_entity", f, ifc_class="IfcDoor", name="D")
    api("aggregate.assign_object", f, products=[door], relating_object=assembly)

    assert M._storey_name(door) == "Level 1"
    assert M._storey_name(assembly) == "Level 1"


def test_storey_name_is_unknown_for_an_uncontained_element(ifc):
    f, _ = ifc
    orphan = api("root.create_entity", f, ifc_class="IfcWall", name="floating")
    assert M._storey_name(orphan) == "?"


def test_pset_bool_reads_declared_is_external_flags(ifc):
    f, _ = ifc
    wall = api("root.create_entity", f, ifc_class="IfcWall", name="W")
    assert M._pset_bool(wall, "Pset_WallCommon", "IsExternal") is None

    pset = api("pset.add_pset", f, product=wall, name="Pset_WallCommon")
    api("pset.edit_pset", f, pset=pset, properties={"IsExternal": False})
    assert M._pset_bool(wall, "Pset_WallCommon", "IsExternal") is False
    api("pset.edit_pset", f, pset=pset, properties={"IsExternal": True})
    assert M._pset_bool(wall, "Pset_WallCommon", "IsExternal") is True
    assert M._pset_bool(wall, "Pset_WallCommon", "LoadBearing") is None


def test_qto_area_prefers_net_over_gross_floor_area(ifc):
    f, _ = ifc
    space = api("root.create_entity", f, ifc_class="IfcSpace", name="S")
    assert M._qto_area(space) is None

    qto = api("pset.add_qto", f, product=space, name="Qto_SpaceBaseQuantities")
    api("pset.edit_qto", f, qto=qto, properties={"GrossFloorArea": 30.0})
    assert M._qto_area(space) == 30.0
    api("pset.edit_qto", f, qto=qto, properties={"NetFloorArea": 26.4})
    assert M._qto_area(space) == 26.4
    # a zero quantity is not usable data: fall back to the next key / the footprint area
    api("pset.edit_qto", f, qto=qto, properties={"NetFloorArea": 0.0})
    assert M._qto_area(space) == 30.0


def test_host_wall_follows_fills_voids_to_the_hosting_wall(ifc):
    f, storey = ifc
    wall = api("root.create_entity", f, ifc_class="IfcWall", name="W")
    door = api("root.create_entity", f, ifc_class="IfcDoor", name="D")
    api("spatial.assign_container", f, products=[wall, door], relating_structure=storey)
    assert M._host_wall(door) is None

    opening = api("root.create_entity", f, ifc_class="IfcOpeningElement", name="O")
    api("feature.add_feature", f, feature=opening, element=wall)
    api("feature.add_filling", f, opening=opening, element=door)
    assert M._host_wall(door) == wall.GlobalId
    assert ue.get_psets(door) == {}
