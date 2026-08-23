"""The interview: intent in prose, a sealed DesignBrief out. This is L1.

A client describes a house in their own words. Somebody has to turn that into
the typed brief the autopilot runs on -- and the design rule for this layer is
the same as everywhere else in the stack:

* **Which facts are needed is computed, not guessed.** The slot manifest comes
  from the ruleset's `requires:` fields (`score.required_slots`), so adding a
  rule adds its question with no question bank to maintain.
* **The model reads and phrases; code decides.** Devin identifies intent and
  asks the clarifying questions, but every value it returns is validated at
  this boundary against the DesignBrief contract, and unconfirmed values must
  arrive as assumptions with a stated basis -- the silent default is the
  failure mode this product exists to remove.

The Studio cannot call the Devin API from the browser (api.devin.ai does not
allow cross-origin calls, and the page must never hold a key anyway), so a chat
round trips through GitHub Actions: the page posts a `repository_dispatch`,
the `interview` workflow runs `recognition interview` here with the org's key,
and the reply lands as a JSON file the page can read back. One CLI call is one
conversational round; the Devin session persists across rounds by id.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .contracts import CATEGORIES, ContractError, DesignBrief
from .score import load_ruleset, required_slots

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = REPO_ROOT / "rules" / "by" / "residential.yaml"
PLAYBOOK = REPO_ROOT / "playbooks" / "interview.devin.md"
SKILL = REPO_ROOT / ".agents" / "skills" / "interview-brief" / "SKILL.md"

MAX_ROUNDS = 3          # the architecture's stopping rule: cap at 3 rounds
MAX_QUESTIONS = 4       # ... of at most 4 questions each

# A ceiling per interview session. An interview is a handful of short
# structured turns, so this is generous for the work -- and it bounds the cost
# when the trigger is reachable from a public page.
MAX_INTERVIEW_ACU = 3

# What one interview round hands back. `message` is what the client reads;
# everything else is structure the Studio renders as chips and fields.
INTERVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "What you say to the client next. Short, plain words, "
                           "no regulation numbers unless they asked.",
        },
        "brief": {
            "type": "object",
            "description": "Every DesignBrief field you can already fill from the "
                           "conversation: project, building_class (free-form; not "
                           "every building is a home — offices, studios, practices "
                           "are welcome), dwelling_count (1 for any non-residential "
                           "building, registered as an assumption), occupants (the "
                           "people living or working there — it sizes workspaces), "
                           "plot_width_m, plot_depth_m, storey_count (1 or 2; "
                           "bedrooms stack above living around one stair core), "
                           "storey_height_m, "
                           "rooms[{category,count,min_area_m2,label}], "
                           "accessibility_tier, notes.",
        },
        "questions": {
            "type": "array",
            "description": "The clarifying questions still open, at most 4. "
                           "Only ask what a rule genuinely needs.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "kind": {"type": "string", "enum": ["single", "multi", "number", "free"]},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "unit": {"type": "string"},
                    "blocking": {"type": "boolean"},
                },
                "required": ["id", "question", "kind"],
            },
        },
        "assumptions": {
            "type": "array",
            "description": "Every value you inferred rather than were told, with "
                           "the reason. There is no third category.",
            "items": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string"},
                    "value": {},
                    "basis": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["slot", "value", "basis"],
            },
        },
        "done": {
            "type": "boolean",
            "description": "True when no blocking slot is empty and the brief is "
                           "ready to seal.",
        },
    },
    "required": ["message", "done"],
}


@dataclass
class InterviewReply:
    """One round's result, shaped for the Studio. Never raw model output."""
    message: str
    brief: dict = field(default_factory=dict)
    questions: list[dict] = field(default_factory=list)
    assumptions: list[dict] = field(default_factory=list)
    done: bool = False
    sealed_brief: dict | None = None      # set only when done and valid
    contract_error: str = ""              # set when done but the brief failed validation
    session_id: str = ""
    session_url: str = ""
    round: int = 1
    engine: str = "devin"

    def to_dict(self) -> dict:
        return asdict(self)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return p


# --------------------------------------------------------------------------
# Prompt construction -- deterministic, testable, no network
# --------------------------------------------------------------------------

def render_transcript(messages: list[dict]) -> str:
    """The conversation so far, as plain labelled lines.

    Only two roles reach the model: the client and the interviewer. Studio
    bookkeeping messages (mode switches, status lines) must be filtered out by
    the caller -- the model reads a conversation, not a UI log.
    """
    out = []
    for m in messages:
        who = "CLIENT" if str(m.get("role", "client")).lower() in ("client", "you", "user") else "INTERVIEWER"
        text = str(m.get("text", "")).strip()
        if text:
            out.append(f"{who}: {text}")
    return "\n".join(out)


def slot_manifest(rules_path: Path = DEFAULT_RULES) -> dict:
    """What the interview must and may ask, computed from the rules in force.

    Blocking slots are the ones a `tier: law` rule requires -- legal inputs are
    never assumed. Everything else may be defaulted, but only into the
    assumption register.
    """
    _doc, metas = load_ruleset(rules_path)
    blocking: set[str] = set()
    for m in metas.values():
        if m.tier == "law":
            blocking.update(m.requires)
    return {
        "slots": required_slots(metas),
        "blocking": sorted(blocking),
        "categories": list(CATEGORIES),
    }


def build_prompt(messages: list[dict], *, rules_path: Path = DEFAULT_RULES,
                 round_no: int = 1, known: dict | None = None) -> str:
    """The whole instruction for one interview session, playbook inlined.

    Written to Devin's own guidance for instructing Devin: context first, the
    procedure as numbered steps, explicit success criteria, and the exact
    output contract. The playbook file is the single source of the procedure;
    this function only assembles it with the live facts (manifest, transcript,
    round number).
    """
    manifest = slot_manifest(rules_path)
    playbook = PLAYBOOK.read_text(encoding="utf-8") if PLAYBOOK.exists() else ""
    skill = SKILL.read_text(encoding="utf-8") if SKILL.exists() else ""
    known_json = json.dumps(known or {}, indent=2, ensure_ascii=False)
    parts = [
        "You are the intake interviewer for Recognition, an autonomous layer that "
        "turns a residential design brief into a verified building. "
        "@skills:interview-brief covers this procedure if you have the repo indexed; "
        "its content is also inlined below so you need no repository access.",
        "",
        f"ROUND {round_no} of {MAX_ROUNDS}. Ask at most {MAX_QUESTIONS} questions this round. "
        f"By round {MAX_ROUNDS} you must set done=true, filling every non-blocking gap "
        "with an assumption that states its basis.",
        "",
        "SLOT MANIFEST (computed from the ruleset in force -- do not invent slots):",
        json.dumps(manifest, indent=2),
        "",
        "WHAT IS ALREADY KNOWN (from earlier rounds; do not re-ask):",
        known_json,
        "",
        "THE CONVERSATION SO FAR:",
        render_transcript(messages) or "CLIENT: (nothing yet)",
        "",
        "Return your reply via the structured output tool, matching the schema you "
        "were given. The `message` field is what the client reads -- plain words, "
        "warm, at most three sentences.",
    ]
    if playbook:
        parts += ["", "--- PLAYBOOK ---", playbook]
    if skill:
        parts += ["", "--- SKILL: interview-brief ---", skill]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Reply shaping -- validate whatever came back, never trust it unchecked
# --------------------------------------------------------------------------

def shape_reply(payload: dict, *, session_id: str = "", session_url: str = "",
                round_no: int = 1) -> InterviewReply:
    """Turn raw structured output into an InterviewReply the Studio can render.

    A done-flagged brief is validated against the DesignBrief contract right
    here. If it fails, `done` is withdrawn and the contract error is carried in
    the reply -- the validator's message is the repair instruction, same as in
    the autopilot.
    """
    if not isinstance(payload, dict):
        payload = {}
    questions = [q for q in payload.get("questions") or [] if isinstance(q, dict)][:MAX_QUESTIONS]
    assumptions = [a for a in payload.get("assumptions") or [] if isinstance(a, dict)]
    brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}
    reply = InterviewReply(
        message=str(payload.get("message", "")).strip() or "…",
        brief=brief,
        questions=questions,
        assumptions=assumptions,
        done=bool(payload.get("done")),
        session_id=session_id,
        session_url=session_url,
        round=round_no,
    )
    if reply.done and brief:
        try:
            candidate = DesignBrief.from_dict({**brief, "project": brief.get("project") or "Neubau"})
            # The interviewer's registered assumptions belong on the sealed
            # brief itself -- the register travels with the intent, or it is
            # not an honesty surface.
            from .contracts import Assumption
            have = {a.slot for a in candidate.assumptions}
            for a in assumptions:
                if a.get("slot") and a["slot"] not in have:
                    candidate.assumptions.append(Assumption(
                        slot=str(a["slot"]), value=a.get("value"),
                        basis=str(a.get("basis", "")),
                        confidence=str(a.get("confidence", "medium")),
                    ))
            candidate.resolve_accessibility()
            reply.sealed_brief = candidate.validate().to_dict()
        except (ContractError, TypeError) as e:
            reply.done = False
            reply.contract_error = str(e)
    elif reply.done and not brief:
        reply.done = False
        reply.contract_error = "done=true but no brief fields were returned"
    return reply


def _fingerprint(snap) -> str:
    raw = json.dumps({"so": snap.structured_output, "msg": snap.last_message},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# One conversational round against a live session
# --------------------------------------------------------------------------

def conduct(messages: list[dict], *, session_id: str = "", round_no: int = 1,
            known: dict | None = None, rules_path: Path = DEFAULT_RULES,
            client=None, timeout_s: float = 600, poll_s: float = 6,
            log=print) -> InterviewReply:
    """Run one interview round. Creates the session on round 1, reuses it after.

    The waiting rule: after sending, poll until the session's output
    fingerprint changes and it settles back into a terminal state. v1 sessions
    report `blocked` when they are waiting on us -- that plus fresh output is
    the reply.
    """
    from .devin import DevinClient, TERMINAL

    own_client = client is None
    client = client or DevinClient()
    try:
        if session_id:
            before = client.snapshot(session_id)
            prev_fp = _fingerprint(before)
            latest = [m for m in messages if str(m.get("role", "")).lower() in ("client", "you", "user")]
            text = latest[-1].get("text", "") if latest else render_transcript(messages)
            log(f"  interview round {round_no}: continuing session {session_id}")
            client.send_message(session_id, str(text))
            url = ""
        else:
            prompt = build_prompt(messages, rules_path=rules_path, round_no=round_no, known=known)
            log(f"  interview round {round_no}: opening a session")
            session_id = client.create_session(
                prompt,
                title="Recognition · interview",
                tags=["recognition", "interview"],
                max_acu=MAX_INTERVIEW_ACU,
                structured_output=INTERVIEW_SCHEMA,
            )
            prev_fp = ""
            url = ""
        deadline = time.monotonic() + timeout_s
        snap = None
        while time.monotonic() < deadline:
            snap = client.snapshot(session_id)
            url = url or f"https://app.devin.ai/sessions/{session_id.removeprefix('devin-')}"
            fp = _fingerprint(snap)
            settled = snap.status in TERMINAL or snap.status == "error"
            if snap.error and not snap.structured_output:
                break
            if settled and snap.structured_output is not None and fp != prev_fp:
                return shape_reply(snap.structured_output, session_id=session_id,
                                   session_url=url, round_no=round_no)
            time.sleep(poll_s)
        detail = (snap.error or f"status '{snap.status}'") if snap else "no snapshot"
        reply = InterviewReply(
            message="Devin has not answered yet. The session is still open -- "
                    "try again in a minute, or continue without it.",
            session_id=session_id, session_url=url, round=round_no,
        )
        reply.contract_error = f"no reply within {timeout_s:.0f}s ({detail})"
        return reply
    finally:
        if own_client:
            client.close()
