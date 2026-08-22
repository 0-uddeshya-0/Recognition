"""In-memory job store.

A Job is one uploaded model — or one house written as code — plus a sequence
of *runs*: the initial package, then re-runs triggered by an edited ruleset,
an edited design or a Devin session. Each run writes its own package
directory; ``job.result_dir`` always points at the latest successful one.
Nothing is persisted beyond the files on disk — this is a proof of concept,
restart the server and the list is empty.
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_ROOT = Path(os.environ.get("RECOGNITION_JOBS_DIR", REPO_ROOT / "out" / "ui-jobs"))

LOCAL_STEPS = ["Load model", "Schedules", "Compliance", "Sheets", "Enriched IFC"]
CODE_STEPS = ["Build model", *LOCAL_STEPS]  # a design written as code is built into an IFC first
DEVIN_STEPS = ["Upload model", "Devin session", "Working", "Pull request", "Fetch package"]


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-") or "model"


@dataclass
class Step:
    name: str
    status: str = "pending"  # pending | running | done | failed
    detail: str = ""


@dataclass
class Run:
    index: int
    started_at: float
    out_dir: str
    trigger: str  # initial | rules | code | devin
    instruction: str | None = None
    rules_yaml: str | None = None
    finished_at: float | None = None
    summary: dict | None = None
    error: str | None = None
    commit: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "failed"
        return "done" if self.summary else "running"


@dataclass
class Job:
    id: str
    created_at: float
    model_name: str
    model_path: str
    dir: str
    project: str
    engine: str = "local"  # local | devin
    status: str = "queued"  # queued | running | done | failed
    steps: list[Step] = field(default_factory=list)
    result_dir: str | None = None
    summary: dict | None = None
    pr_url: str | None = None
    branch: str | None = None
    devin_session_id: str | None = None
    devin_session_url: str | None = None
    devin_message: str | None = None
    devin_acus: float | None = None
    devin_waiting: bool = False  # Devin asked something / is blocked; replies are allowed while 'running'
    error: str | None = None
    note: str | None = None
    approved: bool = False
    approved_at: float | None = None
    rules_yaml: str | None = None  # active custom ruleset (None = repo default)
    instruction: str | None = None
    runs: list[Run] = field(default_factory=list)
    finished_at: float | None = None
    source: str = "ifc"  # ifc | code — where the model comes from
    code: str | None = None  # the house as Python (source == "code"); built into model_path on each run
    chat: list[dict] = field(default_factory=list)  # [{role, text, changed, at}] — the conversation that edits the code
    chat_conversation: str | None = None  # nakle conversation id, so the model remembers earlier turns

    # --- lifecycle helpers ------------------------------------------------

    def reset_steps(self, names: list[str]) -> None:
        self.steps = [Step(n) for n in names]

    def step(self, name: str) -> Step:
        return next(s for s in self.steps if s.name == name)

    def set_step(self, name: str, status: str, detail: str | None = None) -> None:
        s = self.step(name)
        s.status = status
        if detail is not None:
            s.detail = detail

    def running_step(self) -> Step | None:
        return next((s for s in self.steps if s.status == "running"), None)

    def new_run(self, trigger: str, instruction: str | None = None, rules_yaml: str | None = None) -> Run:
        idx = len(self.runs) + 1
        out_dir = Path(self.dir) / f"run-{idx}"
        out_dir.mkdir(parents=True, exist_ok=True)
        run = Run(idx, time.time(), str(out_dir), trigger, instruction, rules_yaml)
        self.runs.append(run)
        self.status = "running"
        self.error = None
        self.finished_at = None
        self.approved = False
        return run

    def current_run(self) -> Run | None:
        return self.runs[-1] if self.runs else None

    def finish_run(self, run: Run, summary: dict) -> None:
        run.summary = summary
        run.finished_at = time.time()
        self.result_dir = run.out_dir
        self.summary = summary
        self.status = "done"
        self.finished_at = run.finished_at
        for s in self.steps:
            if s.status in ("pending", "running"):
                s.status = "done"

    def fail_run(self, run: Run, error: str) -> None:
        run.error = error
        run.finished_at = time.time()
        self.status = "failed"
        self.error = error
        self.finished_at = run.finished_at
        cur = self.running_step()
        if cur:
            cur.status = "failed"
            cur.detail = error.splitlines()[-1][:200] if error else "failed"

    def elapsed(self) -> float:
        run = self.current_run()
        start = run.started_at if run else self.created_at
        end = run.finished_at if run and run.finished_at else time.time()
        return round(end - start, 1)

    # --- views ------------------------------------------------------------

    def delta(self) -> dict | None:
        """Compliance difference between the two latest completed runs."""
        done = [r for r in self.runs if r.summary]
        if len(done) < 2:
            return None
        prev, cur = done[-2], done[-1]
        pf, cf = failing_keys(Path(prev.out_dir)), failing_keys(Path(cur.out_dir))
        pc, cc = prev.summary["compliance"], cur.summary["compliance"]
        return {
            "from_run": prev.index, "to_run": cur.index,
            "status_before": pc["status"], "status_after": cc["status"],
            "errors": cc["errors"] - pc["errors"], "warnings": cc["warnings"] - pc["warnings"],
            "new_failures": sorted(f"{rid} {tag}" for rid, tag in cf - pf),
            "fixed": sorted(f"{rid} {tag}" for rid, tag in pf - cf),
        }

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "created_at": self.created_at, "model_name": self.model_name, "project": self.project,
            "engine": self.engine, "status": self.status, "steps": [asdict(s) for s in self.steps],
            "elapsed": self.elapsed(), "summary": self.summary, "pr_url": self.pr_url, "branch": self.branch,
            "devin_session_id": self.devin_session_id, "devin_session_url": self.devin_session_url,
            "devin_message": self.devin_message, "devin_acus": self.devin_acus, "devin_waiting": self.devin_waiting,
            "error": self.error, "note": self.note, "approved": self.approved,
            "rules_yaml": self.rules_yaml, "instruction": self.instruction,
            "source": self.source, "code": self.code, "chat": self.chat,
            "runs": [{"index": r.index, "trigger": r.trigger, "status": r.status, "instruction": r.instruction,
                      "started_at": r.started_at, "finished_at": r.finished_at, "commit": r.commit,
                      "compliance": (r.summary or {}).get("compliance", {}).get("status"),
                      "errors": (r.summary or {}).get("compliance", {}).get("errors"),
                      "warnings": (r.summary or {}).get("compliance", {}).get("warnings")} for r in self.runs],
            "delta": self.delta(),
            "has_result": self.result_dir is not None,
        }
        return d


# --- package reading --------------------------------------------------------

def failing_keys(out_dir: Path) -> set[tuple[str, str]]:
    p = out_dir / "report.json"
    if not p.exists():
        return set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return {(r["rule_id"], r["element_tag"]) for r in data.get("results", []) if not r.get("passed")}


def _read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_package(out_dir: Path) -> dict:
    """Everything the result screen needs, read once per run."""
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    report_p = out_dir / "report.json"
    report = json.loads(report_p.read_text(encoding="utf-8")) if report_p.exists() else {"results": []}
    results = report.get("results", [])
    failing_tags = sorted({r["element_tag"] for r in results if not r.get("passed")})
    sched = out_dir / "schedules"
    return {
        "summary": summary,
        "results": results,
        "failing_tags": failing_tags,
        "schedules": {k: _read_csv(sched / f"{k}.csv") for k in ("rooms", "doors", "windows")},
        "report_md": (out_dir / "report.md").read_text(encoding="utf-8") if (out_dir / "report.md").exists() else "",
    }


# --- store ------------------------------------------------------------------

class JobStore:
    def __init__(self, root: Path = JOBS_ROOT):
        self.root = Path(root)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, model_path: Path, model_name: str, engine: str = "local", project: str | None = None) -> Job:
        jid = uuid.uuid4().hex[:10]
        jdir = self.root / jid
        jdir.mkdir(parents=True, exist_ok=True)
        job = Job(jid, time.time(), model_name, str(model_path), str(jdir), project=project or Path(model_name).stem,
                  engine=engine)
        with self._lock:
            self._jobs[jid] = job
        return job

    def get(self, jid: str) -> Job | None:
        return self._jobs.get(jid)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
