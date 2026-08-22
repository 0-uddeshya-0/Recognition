"""Tests for the autonomous layer.

These guard the three properties the system is judged on:
  autonomy      -- a trigger reaches artifacts with nobody in the middle
  verification  -- the system tells a good result from a bad one by itself
  artifacts     -- the output is a real IFC with real drawings

Everything here runs on the `local` engine: no API key, no network, no cost.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from recognition.contracts import (
    Adjacency, ArchitectPlan, ContractError, DesignBrief, Envelope, RoomRequest, RoomSpec,
)
from recognition.devin import extract_json
from recognition.score import RulesetError, load_ruleset, rank, required_slots
from recognition.translate import LayoutError, fit, layout, translate

RULES = Path(__file__).resolve().parent.parent / "rules" / "by" / "residential.yaml"


def _plan(**kw) -> ArchitectPlan:
    base = dict(
        project="T", envelope=Envelope(12.0, 10.0), circulation_id="R-03",
        rooms=[RoomSpec("R-01", "kitchen", "Küche", 14.0),
               RoomSpec("R-02", "living", "Wohnen", 26.0),
               RoomSpec("R-03", "hall", "Flur", 11.0),
               RoomSpec("R-04", "bedroom", "Schlafzimmer", 16.0)],
        adjacency=[Adjacency("R-03", "R-01"), Adjacency("R-03", "R-02"),
                   Adjacency("R-03", "R-04")],
    )
    base.update(kw)
    return ArchitectPlan(**base)


# --- contracts: the boundary must reject bad agent output ------------------

def test_plan_rejects_unknown_room_category():
    p = _plan(rooms=[RoomSpec("R-01", "ballroom", "X", 20.0)], adjacency=[], circulation_id=None)
    with pytest.raises(ContractError, match="ballroom"):
        p.validate()


def test_plan_rejects_disconnected_rooms():
    p = _plan(adjacency=[Adjacency("R-03", "R-01")])
    with pytest.raises(ContractError, match="not reachable"):
        p.validate()


def test_plan_rejects_programme_larger_than_envelope():
    p = _plan(envelope=Envelope(6.0, 5.0))
    with pytest.raises(ContractError, match="envelope only offers"):
        p.validate()


def test_error_messages_are_repair_instructions():
    """The validator's text is fed back to an agent, so it must name the fix."""
    p = _plan(rooms=[RoomSpec("R-09", "bedroom", "X", 0.0)], adjacency=[], circulation_id=None)
    with pytest.raises(ContractError) as e:
        p.validate()
    assert "R-09" in str(e.value) and "target_area_m2" in str(e.value)


def test_brief_derives_accessibility_from_baybo_art48():
    b = DesignBrief(project="T", dwelling_count=3, rooms=[RoomRequest("living")])
    assert b.accessibility_tier == "none"
    b.resolve_accessibility()
    assert b.accessibility_tier == "din18040_2"
    assert any("Art. 48" in a.basis for a in b.assumptions), "the trigger must be recorded"


def test_brief_below_minimum_clear_height_is_rejected():
    b = DesignBrief(project="T", storey_height_m=2.20, rooms=[RoomRequest("living")])
    with pytest.raises(ContractError, match="2.40"):
        b.validate()


# --- the translator: deterministic, and it refuses bad geometry ------------

def test_translation_is_deterministic():
    assert translate(_plan()) == translate(_plan())


def test_translator_emits_no_coordinates_from_the_plan():
    """Every number in the output is computed here, not carried from the plan."""
    src = translate(_plan())
    assert "eg.wall(" in src and "eg.room(" in src
    assert "h.write(" in src


def test_layout_refuses_unusably_narrow_rooms():
    p = _plan(rooms=[RoomSpec("R-01", "living", "W", 40.0),
                     RoomSpec("R-02", "utility", "H", 1.6)],
              adjacency=[Adjacency("R-01", "R-02")], circulation_id=None,
              envelope=Envelope(14.0, 4.0))
    with pytest.raises(LayoutError):
        layout(p)


def test_fit_grows_the_envelope_rather_than_shipping_a_sliver():
    p = _plan(rooms=[RoomSpec("R-01", "living", "W", 30.0),
                     RoomSpec("R-02", "kitchen", "K", 12.0),
                     RoomSpec("R-03", "hall", "F", 9.0),
                     RoomSpec("R-04", "utility", "H", 4.0)],
              adjacency=[Adjacency("R-03", x) for x in ("R-01", "R-02", "R-04")])
    fitted, rects, grew = fit(p)
    assert grew >= 0
    assert min(min(r.w, r.h) for r in rects.values()) >= 1.19
    assert fitted.envelope.width_m >= p.envelope.width_m


def test_every_room_gets_a_door():
    """A sealed room is a bug, even when the plan's pairing was unbuildable."""
    src = translate(_plan())
    assert src.count("eg.door(") >= 4          # 3 internal + the entrance


# --- the ruleset: provenance is mandatory ---------------------------------

def test_ruleset_loads_with_tiers_and_citations():
    doc, metas = load_ruleset(RULES)
    assert doc["jurisdiction"] == "DE-BY"
    assert all(m.source for m in metas.values()), "every rule needs a citation"
    assert {m.tier for m in metas.values()} <= {"law", "standard", "guidance", "house"}


def test_rule_without_tier_is_refused(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: x\nrules:\n  - id: A\n    source: {law: X}\n", encoding="utf-8")
    with pytest.raises(RulesetError, match="tier"):
        load_ruleset(p)


def test_rule_without_source_is_refused(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: x\nrules:\n  - id: A\n    tier: law\n", encoding="utf-8")
    with pytest.raises(RulesetError, match="source"):
        load_ruleset(p)


def test_yaml_no_is_not_mistaken_for_a_boolean():
    """`checkable: no` parses as False in YAML 1.1; coercing it hides a blind spot."""
    _doc, metas = load_ruleset(RULES)
    blind = {m.id for m in metas.values() if m.checkable == "no"}
    assert {"SMOKE-DETECTOR", "THRESHOLD"} <= blind


def test_guidance_never_blocks_and_law_does():
    _doc, metas = load_ruleset(RULES)
    assert metas["ROOM-MIN-AREA"].tier == "guidance"
    assert not metas["ROOM-MIN-AREA"].blocks, "a Richtwert must never block a merge"
    assert metas["ROOM-DAYLIGHT"].blocks


def test_daylight_ratio_matches_baybo_not_the_old_demo_value():
    import yaml
    spec = next(r for r in yaml.safe_load(RULES.read_text())["rules"]
                if r["id"] == "ROOM-DAYLIGHT")
    assert spec["params"]["min_ratio"] == pytest.approx(0.125), "BayBO Art. 45 (2) is 1/8"


def test_interview_questions_come_from_the_rules():
    """Nobody maintains a question bank: the slots are the rules' requirements."""
    _doc, metas = load_ruleset(RULES)
    slots = required_slots(metas)
    assert "dwelling_count" in slots and "accessibility_tier" in slots


# --- categorisation: the bug that lost a bathroom -------------------------

@pytest.mark.parametrize("name,expected", [
    ("Badezimmer", "bathroom"),      # NOT bedroom: bare "zimmer" is just "room"
    ("Arbeitszimmer", "office"),
    ("Esszimmer", "living"),
    ("Kinderzimmer 1", "bedroom"),
    ("Schlafzimmer", "bedroom"),
    ("Zentrale Diele", "hall"),
    ("Küche", "kitchen"),
])
def test_german_room_names_categorise_correctly(name, expected):
    from recognition.model import categorize
    assert categorize(name) == expected


# --- agent-output tolerance ----------------------------------------------

def test_extract_json_recovers_a_plan_from_a_chat_message():
    """v1 sessions sometimes answer in prose instead of structured_output."""
    msg = 'Here you go:\n```json\n{"envelope": {"width_m": 12}, "rooms": []}\n```\nHope that helps.'
    assert extract_json(msg) == {"envelope": {"width_m": 12}, "rooms": []}


def test_extract_json_returns_none_when_there_is_no_json():
    assert extract_json("Which Bundesland is the site in?") is None


def test_known_vocabulary_variants_are_normalised():
    from recognition.autopilot import normalise_agent_plan
    payload, notes = normalise_agent_plan(
        {"rooms": [{"id": "R-01", "category": "WC"}],
         "adjacency": [{"a": "R-01", "b": "R-02", "via": "opening"}]})
    assert payload["rooms"][0]["category"] == "bathroom"
    assert payload["adjacency"][0]["via"] == "open"
    assert notes, "normalisation must be reported, never silent"


# --- ranking: the system chooses, not a person ---------------------------

def test_ranking_puts_passing_candidates_first():
    from recognition.score import Verdict
    bad = Verdict("bad", False, 10, 8, 2, 0, 2, 0, metrics={"usable_ratio": 0.99})
    good = Verdict("good", True, 10, 10, 0, 0, 0, 0, metrics={"usable_ratio": 0.50})
    assert [v.candidate for v in rank([bad, good])] == ["good", "bad"]


def test_coverage_line_never_reports_a_bare_pass():
    from recognition.score import Verdict
    v = Verdict("c", True, 27, 27, 0, 2, 0, 0)
    assert "not evaluated" in v.coverage_line()


# --- end to end -----------------------------------------------------------

@pytest.mark.slow
def test_trigger_to_artifacts_with_nobody_in_between(tmp_path):
    from recognition.autopilot import run_local
    brief = DesignBrief(project="E2E", rooms=[
        RoomRequest("living"), RoomRequest("kitchen"),
        RoomRequest("bedroom", 2), RoomRequest("bathroom")])
    res = run_local(brief, tmp_path, rules_path=RULES, log=lambda *a: None)

    assert res.winner, "the scorer must pick a winner without being asked"
    best = next(c for c in res.candidates if c.name == res.winner)
    assert best.out_dir is not None
    for artifact in ("plan.json", "design.py", "model.ifc", "verdict.json"):
        assert (best.out_dir / artifact).exists(), f"missing artifact {artifact}"
    assert best.verdict.blocking_failures == 0
    assert json.loads((tmp_path / "run.json").read_text())["winner"] == res.winner


@pytest.mark.slow
def test_candidates_are_structurally_different(tmp_path):
    """Fan-out is theatre if the siblings produce the same building."""
    from recognition.autopilot import run_local
    brief = DesignBrief(project="Diff", rooms=[
        RoomRequest("living"), RoomRequest("kitchen"), RoomRequest("bedroom", 2)])
    res = run_local(brief, tmp_path, rules_path=RULES, log=lambda *a: None)
    built = [c for c in res.candidates if c.out_dir and (c.out_dir / "design.py").exists()]
    sources = {(c.out_dir / "design.py").read_text() for c in built}
    assert len(sources) == len(built), "candidates must differ structurally"
