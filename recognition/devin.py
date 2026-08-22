"""Devin API v1 client and parallel session fan-out.

The org's key is a legacy `apk_user_` key: the v3 endpoints return 403 for it and
v1 works, so v1 is what this speaks. The version lives in one constant.

Two v1 quirks that will bite anyone reading this later:

* A finished session reports ``status_enum: "blocked"`` *with* ``structured_output``
  populated. It never reports "finished". Treating "blocked" as failure will hang
  the orchestrator forever.
* Attachment upload returns a bare text URL, which goes into the prompt as an
  ``ATTACHMENT:"<url>"`` line rather than a JSON field.

Nothing in this module decides whether work is good. It starts sessions, polls
them, and reports what they produced; `recognition.score` is the only judge.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

DEVIN_API = "https://api.devin.ai/v1"

# A session is done when it is blocked *and* has handed back structured output.
TERMINAL = ("blocked", "finished", "expired", "stopped")


class DevinError(RuntimeError):
    pass


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an agent message.

    Handles a ```json fence and a bare object, and tolerates prose either side.
    Returns None rather than raising: a message with no JSON in it is a normal
    outcome (the session asked a question), not an error.
    """
    if not text:
        return None
    fence = text.find("```")
    if fence != -1:
        rest = text[fence + 3:]
        if rest[:4].lower().startswith("json"):
            rest = rest[4:]
        end = rest.find("```")
        candidate = rest[:end] if end != -1 else rest
        try:
            v = json.loads(candidate.strip())
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(text[start:i + 1])
                        if isinstance(v, dict):
                            return v
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


@dataclass
class SessionResult:
    """What one Devin session produced. No judgement attached."""
    session_id: str
    status: str = "unknown"
    structured_output: dict | None = None
    pull_request_url: str = ""
    branch: str = ""
    last_message: str = ""
    error: str = ""

    @property
    def done(self) -> bool:
        if self.error:
            return True
        if self.status in ("expired", "stopped", "finished"):
            return True
        # The important one: blocked + structured output means success in v1.
        return self.status == "blocked" and self.structured_output is not None

    @property
    def produced_output(self) -> bool:
        return bool(self.structured_output)


class DevinClient:
    """Thin, synchronous v1 client. One method per endpoint we actually use."""

    def __init__(self, api_key: str | None = None, *, base: str = DEVIN_API,
                 timeout: float = 60.0) -> None:
        key = api_key or os.environ.get("DEVIN_API_KEY", "")
        if not key:
            raise DevinError(
                "No Devin API key. Set DEVIN_API_KEY in the environment or a local .env "
                "(never commit it), or run the pipeline with --engine local."
            )
        self._key = key
        self.base = base.rstrip("/")
        self._http = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )

    # -- endpoints ---------------------------------------------------------

    def create_session(self, prompt: str, *, title: str | None = None,
                       playbook_id: str | None = None, tags: list[str] | None = None,
                       max_acu: int | None = None,
                       structured_output: dict | str | None = None) -> str:
        body: dict[str, Any] = {"prompt": prompt}
        if title:
            body["title"] = title[:120]
        if playbook_id:
            body["playbook_id"] = playbook_id
        if tags:
            body["tags"] = tags
        if max_acu is not None:
            body["max_acu_limit"] = max_acu
        if structured_output is not None:
            # The v1 request field is `structured_output_schema` (JSON Schema
            # object, not a string). The old name `structured_output` was
            # silently ignored on create, which is why sessions "sometimes"
            # answered only in prose -- the schema was never attached and the
            # message-extraction fallback in snapshot() was carrying the run.
            body["structured_output_schema"] = (
                json.loads(structured_output) if isinstance(structured_output, str)
                else structured_output
            )
        r = self._http.post(f"{self.base}/sessions", json=body)
        if r.status_code >= 400:
            raise DevinError(f"create_session failed ({r.status_code}): {r.text[:400]}")
        sid = r.json().get("session_id")
        if not sid:
            raise DevinError(f"create_session returned no session_id: {r.text[:300]}")
        return sid

    def get_session(self, session_id: str) -> dict:
        r = self._http.get(f"{self.base}/session/{session_id}")
        if r.status_code >= 400:
            raise DevinError(f"get_session failed ({r.status_code}): {r.text[:300]}")
        return r.json()

    def send_message(self, session_id: str, text: str) -> None:
        r = self._http.post(f"{self.base}/session/{session_id}/message",
                            json={"message": text})
        if r.status_code >= 400:
            raise DevinError(f"send_message failed ({r.status_code}): {r.text[:300]}")

    def upload_attachment(self, path: str | Path) -> str:
        """Returns a bare URL string, which belongs in the prompt as ATTACHMENT:"…"."""
        p = Path(path)
        with p.open("rb") as fh:
            r = httpx.post(f"{self.base}/attachments",
                           headers={"Authorization": f"Bearer {self._key}"},
                           files={"file": (p.name, fh)}, timeout=120.0)
        if r.status_code >= 400:
            raise DevinError(f"upload_attachment failed ({r.status_code}): {r.text[:300]}")
        return r.text.strip().strip('"')

    def close(self) -> None:
        self._http.close()

    # -- polling -----------------------------------------------------------

    def snapshot(self, session_id: str) -> SessionResult:
        try:
            s = self.get_session(session_id)
        except DevinError as e:
            return SessionResult(session_id, status="error", error=str(e))
        so = s.get("structured_output")
        if isinstance(so, str):
            try:
                so = json.loads(so)
            except json.JSONDecodeError:
                so = {"raw": so}
        pr = s.get("pull_request") or {}
        msgs = s.get("messages") or []
        last = ""
        last_full = ""
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("message") and m.get("type") != "initial_user_message":
                last_full = str(m["message"])
                last = last_full[:800]
                break

        # Observed in v1: a session can answer correctly in a normal message and
        # never populate structured_output at all. Waiting on that field alone
        # hangs the run until timeout, so recover the payload from the message.
        if not isinstance(so, dict) and last_full:
            so = extract_json(last_full)
        return SessionResult(
            session_id=session_id,
            status=str(s.get("status_enum") or s.get("status") or "unknown"),
            structured_output=so if isinstance(so, dict) else None,
            pull_request_url=str(pr.get("url", "") or ""),
            branch=str(s.get("branch_name", "") or ""),
            last_message=last,
        )


# --------------------------------------------------------------------------
# Fan-out
# --------------------------------------------------------------------------

@dataclass
class SessionSpec:
    """One candidate to explore. `strategy` is what makes the siblings differ."""
    name: str
    strategy: str
    prompt: str
    tags: list[str] = field(default_factory=list)
    max_acu: int | None = None


def fan_out(client: DevinClient, specs: list[SessionSpec], *,
            structured_output: dict | str | None = None,
            playbook_id: str | None = None) -> dict[str, str]:
    """Start every session up front so they explore concurrently.

    Returns {spec.name: session_id}. A session that fails to start is recorded as
    an empty id rather than aborting its siblings -- one dead candidate must not
    take the run down.
    """
    ids: dict[str, str] = {}
    for spec in specs:
        try:
            ids[spec.name] = client.create_session(
                spec.prompt, title=f"Recognition · {spec.name}",
                playbook_id=playbook_id, tags=spec.tags or ["recognition", "autopilot"],
                max_acu=spec.max_acu, structured_output=structured_output,
            )
        except DevinError as e:
            ids[spec.name] = ""
            print(f"  ! session '{spec.name}' failed to start: {e}")
    return ids


def wait_all(client: DevinClient, ids: dict[str, str], *, timeout_s: float = 1800,
             interval_s: float = 15.0,
             on_update: Callable[[str, SessionResult], None] | None = None,
             ) -> dict[str, SessionResult]:
    """Poll every live session until each is done or the whole run times out.

    Timing out is a normal outcome, not an exception: the orchestrator scores
    whatever finished. A slow sibling must never block a good answer.
    """
    results: dict[str, SessionResult] = {
        name: SessionResult(sid, status="error" if not sid else "starting",
                            error="" if sid else "session did not start")
        for name, sid in ids.items()
    }
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = [n for n, r in results.items() if not r.done]
        if not pending:
            break
        for name in pending:
            snap = client.snapshot(results[name].session_id)
            if snap.status != results[name].status or snap.done:
                if on_update:
                    on_update(name, snap)
            results[name] = snap
        if all(r.done for r in results.values()):
            break
        time.sleep(interval_s)
    for name, r in results.items():
        if not r.done and not r.error:
            r.error = f"timed out after {timeout_s:.0f}s in status '{r.status}'"
    return results


# The shape every builder session must hand back. Declared once, sent to Devin as
# the structured-output schema so the reply is machine-readable by construction.
PLAN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "branch": {"type": "string", "description": "branch the work was pushed to"},
        "plan_path": {"type": "string", "description": "path to the ArchitectPlan JSON in the repo"},
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"],
                    "description": "result of `recognition verify` that the session ran itself"},
        "blocking_failures": {"type": "integer"},
        "notes": {"type": "string", "description": "what strategy was taken and why"},
    },
    "required": ["verdict", "notes"],
}
