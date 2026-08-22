"""Chat that edits the house: a request in plain words → a new ``house.py`` → rebuild.

The model is reached through nakle, an OpenAI-style ``chat/completions`` service
in front of Claude (``NAKLE_URL``, default the team's instance; ``NAKLE_MODEL``
default ``sonnet``). Every turn sends the current script and the latest check
result; the answer comes back as structured JSON ``{"reply", "code"}`` — ``code``
is the complete new file, or null when nothing needs to change (a question,
a refusal, a clarification). The web layer rebuilds when ``code`` differs.
"""
from __future__ import annotations

import os
import re

import httpx

NAKLE_URL = os.environ.get("NAKLE_URL", "http://20.64.149.209").rstrip("/")
NAKLE_MODEL = os.environ.get("NAKLE_MODEL", "sonnet")
SOURCE = "recognition-studio"

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "one or two plain sentences for the architect: what changed, or the answer"},
        "code": {"type": ["string", "null"], "description": "the COMPLETE new house.py when the request changes the building; null otherwise"},
    },
    "required": ["reply", "code"],
    "additionalProperties": False,
}

SYSTEM = """You are the detailer for an architecture practice. The building is a Python script (house.py) that
uses the `recognition.design` API; you change the building by rewriting that script. The architect reads
drawings, not code — keep replies to one or two plain sentences (what you changed and the numbers that matter).

The API, in metres, x east / y north, on a storey:
  h = House("Name"); eg = h.storey("Erdgeschoss", elevation=0.0, height=2.5)
  eg.wall(name, (x0, y0), (x1, y1), thickness=0.30, external=True|False)   # centre-line; thickness centred on it
  eg.room(name, [(x, y), ...])               # floor outline on the INSIDE faces of the walls; the name sets the category
                                             # (Schlafzimmer/Kind → bedroom, Wohnen → living, Küche → kitchen, Bad/WC → bathroom, Büro → office, Flur → hall)
  eg.door(name, on=<wall name>, at=<m from the wall's start to the door centre>, width=, height=, external=None, type_name="")
  eg.window(name, on=<wall name>, at=, width=, height=, sill=0.9, type_name="")
  The script must keep its `if __name__ == "__main__":` block that writes the IFC to sys.argv[1].

Rules of the craft:
- Moving a wall means moving its centre-line AND every room outline that touches it (inside face = centre ± thickness/2),
  and keeping `at` positions of doors/windows inside their wall's length.
- Keep names, order and comments; change only what the request needs. Never remove rooms, doors or windows unless asked.
- Areas: outline width × depth. Check your arithmetic against the request (e.g. "≥ 25 m²") before answering.
- If the request is not a change to the building (a question, something the API cannot express), answer it and return code: null.
Return JSON: {"reply": "...", "code": "<the complete new house.py>" or null}."""


class NakleClient:
    def __init__(self, base_url: str = NAKLE_URL, model: str = NAKLE_MODEL, timeout: float = 240.0):
        self.base_url, self.model = base_url, model
        self.http = httpx.Client(base_url=base_url, timeout=timeout)

    def complete(self, system: str, user: str, conversation_id: str | None = None) -> dict:
        body = {"model": self.model, "system": system, "messages": [{"role": "user", "content": user}],
                "allowed_tools": [], "source": SOURCE, "timeout": 240,
                "response_format": {"type": "json_schema", "json_schema": SCHEMA}}
        if conversation_id:
            body["conversation_id"] = conversation_id
        r = self.http.post("/chat/completions", json=body)
        r.raise_for_status()
        d = r.json()
        return {"content": d["choices"][0]["message"]["content"], "structured_output": d.get("structured_output"),
                "conversation_id": d.get("conversation_id"), "usage": d.get("usage")}


def context(code: str, summary: dict | None, results: list[dict] | None) -> str:
    lines = ["Current house.py:", "```python", code.rstrip(), "```", ""]
    if summary:
        c = summary["compliance"]
        lines.append(f"Latest check: {c['status']} — {c['checks']} checks, {c['errors']} errors, {c['warnings']} warnings.")
        fails = [r for r in (results or []) if not r.get("passed")]
        for r in fails[:12]:
            lines.append(f"- {r['rule_id']} {r['element_tag']}: {r['message']}")
    return "\n".join(lines)


_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def parse(answer: dict) -> tuple[str, str | None]:
    """(reply, code|None) from a nakle answer — structured output first, a fenced block as fallback."""
    so = answer.get("structured_output")
    if isinstance(so, dict) and "reply" in so:
        code = so.get("code")
        return str(so["reply"]).strip(), (code.strip() + "\n" if isinstance(code, str) and code.strip() else None)
    text = answer.get("content") or ""
    m = _BLOCK.findall(text)
    reply = _BLOCK.sub("", text).strip() or ("Here is the updated house." if m else "")
    return reply, (m[-1].strip() + "\n" if m else None)


def propose(client: NakleClient, text: str, code: str, summary: dict | None, results: list[dict] | None,
            conversation_id: str | None = None) -> tuple[str, str | None, str | None]:
    """Ask for a change. Returns (reply, new_code|None, conversation_id)."""
    user = f"{text.strip()}\n\n{context(code, summary, results)}"
    answer = client.complete(SYSTEM, user, conversation_id)
    reply, new_code = parse(answer)
    if new_code is not None and new_code.strip() == code.strip():
        new_code = None
    return reply, new_code, answer.get("conversation_id")
