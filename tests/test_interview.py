"""Tests for the interview layer (L1).

Same doctrine as the rest of the suite: the deterministic parts are tested
directly, the network is replaced by a fake, and what we assert is the
*properties* the layer is trusted for -- the manifest comes from the rules,
model output is validated at the boundary, and a done-flagged brief that does
not survive the contract is not allowed to stay done.
"""
from __future__ import annotations

import json
from pathlib import Path

from recognition.devin import SessionResult
from recognition.interview import (
    INTERVIEW_SCHEMA, build_prompt, conduct, render_transcript, shape_reply, slot_manifest,
)

RULES = Path(__file__).resolve().parent.parent / "rules" / "by" / "residential.yaml"


# --- the manifest: questions come from the rules, nowhere else -------------

def test_slot_manifest_is_computed_from_the_ruleset():
    m = slot_manifest(RULES)
    assert "dwelling_count" in m["blocking"], "a tier:law rule requires it"
    assert "storey_height_m" in m["blocking"]
    assert "accessibility_tier" in m["slots"]
    assert "bedroom" in m["categories"]


def test_prompt_carries_manifest_transcript_and_stopping_rule():
    p = build_prompt([{"role": "client", "text": "ein Haus für uns vier"}],
                     rules_path=RULES, round_no=2)
    assert "dwelling_count" in p
    assert "ein Haus für uns vier" in p
    assert "ROUND 2 of 3" in p
    assert "Forbidden actions" in p, "the playbook must be inlined"


def test_transcript_rendering_labels_roles():
    txt = render_transcript([
        {"role": "client", "text": "three bedrooms"},
        {"role": "interviewer", "text": "How many homes?"},
        {"role": "client", "text": ""},                      # empty lines dropped
    ])
    assert txt.splitlines() == ["CLIENT: three bedrooms", "INTERVIEWER: How many homes?"]


# --- boundary validation ---------------------------------------------------

def _good_brief() -> dict:
    return {
        "project": "Testhaus", "dwelling_count": 1,
        "rooms": [{"category": "living"}, {"category": "kitchen"}, {"category": "bathroom"}],
    }


def test_done_brief_is_validated_and_sealed():
    r = shape_reply({"message": "ready", "done": True, "brief": _good_brief()})
    assert r.done and r.sealed_brief is not None
    assert r.sealed_brief["schema"] == "designbrief/v1"


def test_done_is_withdrawn_when_the_brief_fails_the_contract():
    bad = _good_brief() | {"storey_count": 5}          # one or two storeys only
    r = shape_reply({"message": "ready", "done": True, "brief": bad})
    assert not r.done
    assert "storey_count" in r.contract_error


def test_done_without_a_brief_is_withdrawn():
    r = shape_reply({"message": "all set", "done": True})
    assert not r.done and r.contract_error


def test_question_count_is_capped():
    qs = [{"id": f"q{i}", "question": "?", "kind": "free"} for i in range(9)]
    r = shape_reply({"message": "m", "done": False, "questions": qs})
    assert len(r.questions) == 4, "the stopping rule caps questions per round"


# --- one round against a fake session -------------------------------------

class FakeClient:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.created: list[dict] = []
        self.sent: list[tuple[str, str]] = []

    def create_session(self, prompt, **kw):
        self.created.append({"prompt": prompt, **kw})
        return "devin-fake-1"

    def send_message(self, sid, text):
        self.sent.append((sid, text))

    def snapshot(self, sid):
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]

    def close(self):
        pass


def test_round_one_creates_a_session_with_the_schema():
    out = {"message": "Which rooms?", "done": False,
           "questions": [{"id": "rooms", "question": "Which rooms?", "kind": "free"}]}
    fake = FakeClient([SessionResult("devin-fake-1", status="blocked", structured_output=out)])
    r = conduct([{"role": "client", "text": "a small house"}],
                client=fake, poll_s=0, timeout_s=5)
    assert r.session_id == "devin-fake-1"
    assert r.questions and not r.done
    assert fake.created[0]["structured_output"] == INTERVIEW_SCHEMA


def test_continuation_waits_for_the_output_to_change():
    stale = {"message": "old", "done": False}
    fresh = {"message": "new", "done": False}
    fake = FakeClient([
        SessionResult("s", status="blocked", structured_output=stale),   # pre-send snapshot
        SessionResult("s", status="working", structured_output=stale),   # still thinking
        SessionResult("s", status="blocked", structured_output=stale),   # old output again
        SessionResult("s", status="blocked", structured_output=fresh),   # the reply
    ])
    r = conduct([{"role": "client", "text": "two of them"}],
                session_id="s", round_no=2, client=fake, poll_s=0, timeout_s=5)
    assert fake.sent == [("s", "two of them")]
    assert r.message == "new" and r.round == 2


def test_timeout_returns_an_honest_not_yet_reply():
    stale = {"message": "old", "done": False}
    fake = FakeClient([SessionResult("s", status="working", structured_output=stale)])
    r = conduct([{"role": "client", "text": "hello"}], session_id="s",
                client=fake, poll_s=0, timeout_s=0.05)
    assert not r.done
    assert "no reply within" in r.contract_error


def test_reply_serialises_for_the_studio(tmp_path):
    r = shape_reply({"message": "ok", "done": False})
    p = r.write(tmp_path / "reply.json")
    doc = json.loads(p.read_text())
    assert doc["message"] == "ok" and doc["engine"] == "devin"
