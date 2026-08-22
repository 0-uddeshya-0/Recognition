"""Engines: who produces the package for a job.

* ``LocalEngine`` runs ``recognition run`` in a subprocess on this machine and
  ticks the step list by watching the output directory fill up (the CLI only
  prints when it is finished, so the files *are* the progress signal). A job
  written as code gets one extra step in front: the house script is run to
  build the IFC the pipeline then reads.
* ``DevinEngine`` uploads the model, opens a Devin session (API v1 — the key
  format this org has) that works in the GitHub repo, and pulls the package
  Devin committed on its branch back into the job directory.

Both expose the same four calls so the web layer does not care which one it
is talking to.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

import httpx
import yaml

from .jobs import CODE_STEPS, DEVIN_STEPS, LOCAL_STEPS, REPO_ROOT, Job, Run, slug

DEFAULT_RULES = REPO_ROOT / "rules" / "residential.yaml"
EXAMPLE_DESIGN = REPO_ROOT / "design" / "house.py"
DEVIN_API = "https://api.devin.ai/v1"
PACKAGE_DIR = "deliveries"  # tracked folder where a Devin session commits the package
UI_PLAYBOOK = REPO_ROOT / "playbooks" / "detailing-ui.devin.md"
BUILD_TIMEOUT = 90.0  # seconds a house script may take to write its IFC


class EngineError(Exception):
    """A request the engine cannot honour; the message is shown to the architect."""


class Engine(Protocol):
    name: str

    def start(self, job: Job, ifc_path: Path, instruction: str | None, rules_yaml: str | None) -> None: ...
    def poll(self, job: Job) -> None: ...
    def message(self, job: Job, text: str, rules_yaml: str | None = None, code: str | None = None) -> None: ...
    def approve(self, job: Job) -> None: ...


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Tiny .env reader so ``uv run recognition-ui`` picks up credentials without another dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def default_rules_yaml() -> str:
    return DEFAULT_RULES.read_text(encoding="utf-8")


def example_design() -> str:
    """The repo's example house script — what the code editor starts from."""
    return EXAMPLE_DESIGN.read_text(encoding="utf-8")


def code_changed(job: Job, code: str | None) -> bool:
    return code is not None and code.strip() != (job.code or "").strip()


def validate_rules(text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise EngineError(f"Rules YAML does not parse: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise EngineError("Rules YAML needs a top-level `rules:` list.")
    return data


def rules_changed(job: Job, rules_yaml: str | None) -> bool:
    if rules_yaml is None:
        return False
    current = job.rules_yaml if job.rules_yaml is not None else default_rules_yaml()
    return rules_yaml.strip() != current.strip()


# --- local ------------------------------------------------------------------

class LocalEngine:
    name = "local"

    def __init__(self, python: str = sys.executable, poll_interval: float = 0.2):
        self.python = python
        self.poll_interval = poll_interval

    def start(self, job: Job, ifc_path: Path, instruction: str | None, rules_yaml: str | None) -> None:
        job.instruction = instruction or None
        if rules_yaml is not None and rules_changed(job, rules_yaml):
            validate_rules(rules_yaml)
            job.rules_yaml = rules_yaml
        if job.instruction and job.rules_yaml is None:
            job.note = ("Free-text requests need Devin mode. The baseline package was generated with the "
                        "default rules; edit the rules below to re-run locally.")
        self._launch(job, "initial", job.instruction, job.rules_yaml)

    def poll(self, job: Job) -> None:  # the worker thread keeps the job current
        return

    def message(self, job: Job, text: str, rules_yaml: str | None = None, code: str | None = None) -> None:
        rules_new = rules_yaml is not None and rules_changed(job, rules_yaml)
        if rules_new:
            validate_rules(rules_yaml)
        if code_changed(job, code):
            if job.source != "code":
                raise EngineError("This job started from an IFC file; only jobs written as code can be rebuilt.")
            if not code.strip():
                raise EngineError("The design is empty — nothing to build.")
            job.code = code
            if rules_new:
                job.rules_yaml = rules_yaml
            job.note = None
            self._launch(job, "code", text or None, job.rules_yaml)
            return
        if rules_new:
            job.rules_yaml = rules_yaml
            job.note = None
            self._launch(job, "rules", text or None, rules_yaml)
            return
        if text and text.strip():
            raise EngineError("Free-text requests need Devin mode; this server runs locally. "
                              "Edit the rules YAML and apply it to re-run here.")
        raise EngineError("Nothing changed — edit the rules or describe a change.")

    def approve(self, job: Job) -> None:
        if job.status != "done":
            raise EngineError("Nothing to approve yet.")
        job.approved = True
        job.approved_at = time.time()

    # --- internals -------------------------------------------------------

    def _launch(self, job: Job, trigger: str, instruction: str | None, rules_yaml: str | None) -> None:
        if job.status == "running":
            raise EngineError("A run is already in progress.")
        run = job.new_run(trigger, instruction, rules_yaml)
        job.reset_steps(CODE_STEPS if job.source == "code" else LOCAL_STEPS)
        t = threading.Thread(target=self._worker, args=(job, run), daemon=True, name=f"run-{job.id}-{run.index}")
        t.start()

    def _command(self, job: Job, run: Run) -> list[str]:
        cmd = [self.python, "-m", "recognition.cli", "run", job.model_path, run.out_dir, "--project", job.project]
        if run.rules_yaml is not None:
            rules_path = Path(run.out_dir) / "rules.yaml"
            rules_path.write_text(run.rules_yaml, encoding="utf-8")
            cmd += ["--rules", str(rules_path)]
        return cmd

    def _build(self, job: Job, run: Run) -> bool:
        """Run the house script to write <out_dir>/model.ifc; False (and the run failed) if it did not."""
        out = Path(run.out_dir)
        script, ifc = out / "house.py", out / "model.ifc"
        script.write_text(job.code or "", encoding="utf-8")
        job.set_step("Build model", "running", script.name)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO_ROOT), env.get("PYTHONPATH")) if p)
        try:
            proc = subprocess.run([self.python, str(script), str(ifc)], cwd=REPO_ROOT, env=env,
                                  capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._fail_build(job, run, f"the design script did not finish within {BUILD_TIMEOUT:.0f} s")
            return False
        except OSError as e:
            self._fail_build(job, run, f"could not run the design script: {e}")
            return False
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        if proc.returncode != 0:
            self._fail_build(job, run, tail or f"the design script exited with {proc.returncode}")
            return False
        if not ifc.is_file():
            self._fail_build(job, run, tail or f"the design script exited cleanly but did not write {ifc.name} "
                                               "(it must write its IFC to sys.argv[1])")
            return False
        job.model_path = str(ifc)
        job.set_step("Build model", "done", f"{script.name} → {ifc.name} ({ifc.stat().st_size / 1e3:.0f} kB)")
        return True

    @staticmethod
    def _fail_build(job: Job, run: Run, detail: str) -> None:
        job.fail_run(run, detail)
        job.set_step("Build model", "failed", detail[-1200:])  # the traceback tail, not just its last line

    def _worker(self, job: Job, run: Run) -> None:
        out = Path(run.out_dir)
        if job.source == "code" and not self._build(job, run):
            return
        job.set_step("Load model", "running", Path(job.model_path).name)
        try:
            proc = subprocess.Popen(self._command(job, run), cwd=REPO_ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
        except OSError as e:
            job.fail_run(run, f"could not start pipeline: {e}")
            return
        while proc.poll() is None:
            self._tick(job, out)
            time.sleep(self.poll_interval)
        self._tick(job, out)
        _, err = proc.communicate()
        summary_p = out / "summary.json"
        if proc.returncode == 0 and summary_p.exists():
            summary = json.loads(summary_p.read_text(encoding="utf-8"))
            self._final_details(job, summary)
            job.finish_run(run, summary)
        else:
            tail = "\n".join((err or "").strip().splitlines()[-8:]) or f"pipeline exited with {proc.returncode}"
            job.fail_run(run, tail)

    @staticmethod
    def _tick(job: Job, out: Path) -> None:
        """Advance steps from what the pipeline has written so far (it writes in this order)."""
        if (out / "schedules").exists():
            job.set_step("Load model", "done")
            job.set_step("Schedules", "running" if not (out / "report.json").exists() else "done")
        if (out / "report.json").exists():
            job.set_step("Schedules", "done")
            if job.step("Compliance").status != "done":
                try:
                    s = json.loads((out / "report.json").read_text(encoding="utf-8"))["summary"]
                    job.set_step("Compliance", "done", f"{s['checks']} checks · {s['errors']} errors · {s['warnings']} warnings")
                except (OSError, ValueError, KeyError):
                    job.set_step("Compliance", "running")
            job.set_step("Sheets", "running" if job.step("Sheets").status == "pending" else job.step("Sheets").status)
        sheets = out / "sheets"
        if sheets.exists():
            pngs = sorted(p.stem for p in sheets.glob("*.png"))
            if pngs and job.step("Sheets").status != "done":
                job.set_step("Sheets", "running", " · ".join(p.split("_", 1)[0] for p in pngs))
        if (out / "model.detailed.ifc").exists():
            job.set_step("Sheets", "done")
            job.set_step("Enriched IFC", "running")
        if (out / "summary.json").exists():
            job.set_step("Enriched IFC", "done")

    @staticmethod
    def _final_details(job: Job, summary: dict) -> None:
        c = summary["counts"]
        job.set_step("Load model", "done", f"{c['storeys']} storeys · {c['walls']} walls · {c['spaces']} rooms · "
                                           f"{c['doors']} doors · {c['windows']} windows")
        s = summary["schedules"]
        job.set_step("Schedules", "done", f"{s['rooms']} rooms · {s['doors']} doors · {s['windows']} windows")
        job.set_step("Sheets", "done", " · ".join(f"{sh['sheet']} {sh['storey']}" for sh in summary["sheets"]))
        job.set_step("Enriched IFC", "done", summary["files"]["enriched_ifc"])


# --- devin ------------------------------------------------------------------

class DevinClient:
    """Thin wrapper over the Devin v1 REST API; swapped for a fake in tests."""

    def __init__(self, api_key: str, base_url: str = DEVIN_API, timeout: float = 120.0):
        self.http = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)

    def upload(self, path: Path) -> str:
        with path.open("rb") as fh:
            r = self.http.post("/attachments", files={"file": (path.name, fh, "application/octet-stream")})
        r.raise_for_status()
        return r.text.strip().strip('"')

    def create_session(self, body: dict) -> dict:
        r = self.http.post("/sessions", json=body)
        r.raise_for_status()
        return r.json()

    def get_session(self, session_id: str) -> dict:
        r = self.http.get(f"/sessions/{session_id}")
        r.raise_for_status()
        return r.json()

    def send_message(self, session_id: str, text: str) -> None:
        r = self.http.post(f"/sessions/{session_id}/message", json={"message": text})
        r.raise_for_status()

    def create_playbook(self, title: str, body: str, macro: str | None = None) -> dict:
        r = self.http.post("/playbooks", json={"title": title, "body": body, "macro": macro})
        r.raise_for_status()
        return r.json()


STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "branch": {"type": "string", "description": "git branch the package was committed to"},
        "pr_url": {"type": "string", "description": "URL of the pull request"},
        "package_dir": {"type": "string", "description": "repo-relative directory holding summary.json"},
        "status": {"type": "string", "enum": ["PASS", "WARN", "FAIL"]},
        "checks": {"type": "integer"}, "errors": {"type": "integer"}, "warnings": {"type": "integer"},
        "sheets": {"type": "integer"},
        "changed": {"type": "string", "description": "one paragraph: what you changed in the repo and why"},
        "assumptions": {"type": "string"},
    },
    "required": ["branch", "package_dir", "status"],
}


def devin_configured() -> bool:
    return bool(os.environ.get("DEVIN_API_KEY"))


def github_repo() -> str:
    """owner/name of the origin remote, unless GITHUB_REPO overrides it."""
    if os.environ.get("GITHUB_REPO"):
        return os.environ["GITHUB_REPO"]
    try:
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    return m.group(1) if m else ""


class DevinEngine:
    name = "devin"

    def __init__(self, client: DevinClient | None = None, repo: str | None = None, git_dir: Path = REPO_ROOT,
                 poll_interval: float = 2.0, max_acu: int | None = None):
        self.client = client or DevinClient(os.environ["DEVIN_API_KEY"])
        self.repo = repo if repo is not None else github_repo()
        self.git_dir = git_dir
        self.poll_interval = poll_interval
        self.max_acu = max_acu or int(os.environ.get("DEVIN_MAX_ACU", "5"))
        self.playbook_id = os.environ.get("DEVIN_PLAYBOOK_ID") or None
        self._last_poll: dict[str, float] = {}
        self._last_commit: dict[str, str] = {}

    # --- protocol --------------------------------------------------------

    def start(self, job: Job, ifc_path: Path, instruction: str | None, rules_yaml: str | None) -> None:
        if job.status == "running":
            raise EngineError("A run is already in progress.")
        job.engine = "devin"
        job.instruction = instruction or None
        if rules_yaml is not None and rules_changed(job, rules_yaml):
            validate_rules(rules_yaml)
            job.rules_yaml = rules_yaml
        job.note = None
        job.branch = job.branch or f"detail/{slug(job.project).lower()}-{job.id[:6]}"
        run = job.new_run("devin", job.instruction, job.rules_yaml)
        job.reset_steps(DEVIN_STEPS)
        threading.Thread(target=self._open_session, args=(job, run, ifc_path), daemon=True).start()

    def poll(self, job: Job) -> None:
        if not job.devin_session_id or job.status != "running":
            return
        now = time.time()
        if now - self._last_poll.get(job.id, 0) < self.poll_interval:
            return
        self._last_poll[job.id] = now
        try:
            s = self.client.get_session(job.devin_session_id)
        except httpx.HTTPError as e:
            job.set_step("Working", "running", f"polling failed: {e}")
            return
        self._apply_session(job, s)

    def message(self, job: Job, text: str, rules_yaml: str | None = None, code: str | None = None) -> None:
        if not job.devin_session_id:
            raise EngineError("No Devin session for this job.")
        if job.status == "running" and not job.devin_waiting:
            raise EngineError("Devin is still working on the previous request.")
        parts = [text.strip()] if text and text.strip() else []
        if rules_yaml is not None and rules_changed(job, rules_yaml):
            validate_rules(rules_yaml)
            job.rules_yaml = rules_yaml
            parts.append("Apply this ruleset (write it to the package directory as rules.yaml and pass it with --rules):\n"
                         f"```yaml\n{rules_yaml.strip()}\n```")
        if code_changed(job, code):
            raise EngineError("Rebuilding a house written as code is a local-engine feature.")
        if not parts:
            raise EngineError("Nothing changed — describe a change or edit the rules.")
        parts.append(f"Regenerate the package under {PACKAGE_DIR}/{slug(job.project)}/ on branch {job.branch}, "
                     "commit, push, update the pull request, and call the structured output tool again.")
        self.client.send_message(job.devin_session_id, "\n\n".join(parts))
        job.devin_waiting = False
        if job.status == "running":  # a reply to a blocked session continues the current run
            job.set_step("Working", "running", "reply sent")
            job.devin_message = None
            return
        run = job.new_run("devin", text or None, job.rules_yaml)
        job.reset_steps(DEVIN_STEPS)
        job.set_step("Upload model", "done", "attached to session")
        job.set_step("Devin session", "done", job.devin_session_id)
        job.set_step("Working", "running", "request sent")
        job.devin_message = None
        run.commit = None

    def approve(self, job: Job) -> None:
        if not job.pr_url:
            raise EngineError("No pull request to merge yet.")
        if job.approved:
            return
        self._merge(job.pr_url)
        job.approved = True
        job.approved_at = time.time()

    # --- internals -------------------------------------------------------

    def prompt(self, job: Job, attachment_url: str | None) -> str:
        pkg = f"{PACKAGE_DIR}/{slug(job.project)}"
        model_line = f"Model: {job.model_name} (attached). Project name: \"{job.project}\"."
        lines = [
            job.instruction or "Produce the detailing package for the attached model.",
            "",
            f"Repository: https://github.com/{self.repo} — base branch `poc/ifc-detailing`. Work on branch `{job.branch}`.",
            model_line,
            f"Commit the generated package to `{pkg}/` (summary.json, report.json, report.md, schedules/, sheets/, "
            "model.detailed.ifc) and open a pull request against `poc/ifc-detailing`.",
            "When done, call the structured output tool with branch, pr_url, package_dir and the compliance counts.",
        ]
        if not self.playbook_id and UI_PLAYBOOK.exists():
            lines += ["", "Follow this playbook:", "", UI_PLAYBOOK.read_text(encoding="utf-8")]
        if job.rules_yaml:
            lines += ["", f"Use this ruleset instead of rules/residential.yaml (save it as `{pkg}/rules.yaml` and pass "
                          "`--rules`):", "```yaml", job.rules_yaml.strip(), "```"]
        if attachment_url:
            lines += ["", f'ATTACHMENT:"{attachment_url}"']
        return "\n".join(lines)

    def _open_session(self, job: Job, run: Run, ifc_path: Path) -> None:
        try:
            job.set_step("Upload model", "running", f"{ifc_path.name} ({ifc_path.stat().st_size / 1e6:.1f} MB)")
            url = self.client.upload(ifc_path)
            job.set_step("Upload model", "done", ifc_path.name)
            job.set_step("Devin session", "running", "creating")
            body = {
                "prompt": self.prompt(job, url),
                "title": f"{job.project} — {job.instruction or 'detailing package'}"[:120],
                "tags": ["recognition", "ui"],
                "max_acu_limit": self.max_acu,
                "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
            }
            if self.playbook_id:
                body["playbook_id"] = self.playbook_id
            s = self.client.create_session(body)
            job.devin_session_id = s["session_id"]
            job.devin_session_url = s.get("url")
            job.set_step("Devin session", "done", s["session_id"])
            job.set_step("Working", "running", "session started")
        except (httpx.HTTPError, OSError, KeyError) as e:
            job.fail_run(run, f"Devin API: {e}")

    def _apply_session(self, job: Job, s: dict) -> None:
        run = job.current_run()
        msgs = [m for m in s.get("messages", []) if m.get("type") == "devin_message"]
        if msgs:
            job.devin_message = msgs[-1].get("message")
        if s.get("acus_consumed") is not None:
            job.devin_acus = s["acus_consumed"]
        pr = s.get("pull_request") or {}
        if pr.get("url"):
            job.pr_url = pr["url"]
            job.set_step("Pull request", "done", pr["url"])
        enum = s.get("status_enum") or s.get("status")
        so = s.get("structured_output") or {}
        branch = so.get("branch") or job.branch
        if so.get("pr_url") and not job.pr_url:
            job.pr_url = so["pr_url"]
            job.set_step("Pull request", "done", so["pr_url"])
        if enum in ("expired", "error") and not so:
            job.fail_run(run, f"Devin session {enum}")
            return
        if so:
            commit = self._remote_head(branch)
            if commit and commit != self._last_commit.get(job.id):
                job.set_step("Working", "done", so.get("changed") or "done")
                job.set_step("Fetch package", "running", f"{branch} @ {commit[:7]}")
                try:
                    self._fetch_package(branch, so.get("package_dir") or f"{PACKAGE_DIR}/{slug(job.project)}", Path(run.out_dir))
                except (OSError, subprocess.CalledProcessError, ValueError) as e:
                    job.fail_run(run, f"could not fetch package from {branch}: {e}")
                    return
                self._last_commit[job.id] = commit
                run.commit = commit
                job.branch = branch
                summary = json.loads((Path(run.out_dir) / "summary.json").read_text(encoding="utf-8"))
                job.set_step("Fetch package", "done", f"{commit[:7]} · {summary['compliance']['status']}")
                if not job.pr_url:
                    job.set_step("Pull request", "done", "not opened")
                job.finish_run(run, summary)
                return
        job.devin_waiting = enum == "blocked"
        if job.devin_waiting:
            job.set_step("Working", "running", "Devin is waiting for your answer — reply below")
        elif enum == "working":
            job.set_step("Working", "running", (job.devin_message or "working")[:160])

    def _remote_head(self, branch: str) -> str | None:
        try:
            out = subprocess.check_output(["git", "ls-remote", "origin", f"refs/heads/{branch}"], cwd=self.git_dir,
                                          text=True, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        return out.split()[0] if out.strip() else None

    def _fetch_package(self, branch: str, package_dir: str, dest: Path) -> None:
        subprocess.run(["git", "fetch", "--quiet", "origin", branch], cwd=self.git_dir, check=True, timeout=120)
        dest.mkdir(parents=True, exist_ok=True)
        depth = len(Path(package_dir).parts)
        archive = subprocess.run(["git", "archive", f"origin/{branch}", package_dir], cwd=self.git_dir,
                                 check=True, capture_output=True, timeout=120)
        subprocess.run(["tar", "-x", f"--strip-components={depth}", "-C", str(dest)], input=archive.stdout,
                       check=True, timeout=120)
        if not (dest / "summary.json").exists():
            raise ValueError(f"{package_dir} on {branch} has no summary.json")

    def _merge(self, pr_url: str) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url)
            if not m:
                raise EngineError(f"unrecognised PR URL {pr_url}")
            r = httpx.put(f"https://api.github.com/repos/{m.group(1)}/pulls/{m.group(2)}/merge",
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                          json={"merge_method": "squash"}, timeout=60)
            if r.status_code >= 300:
                raise EngineError(f"GitHub merge failed: {r.status_code} {r.text[:200]}")
            return
        try:
            subprocess.run(["gh", "pr", "merge", pr_url, "--squash"], cwd=self.git_dir, check=True,
                           capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            raise EngineError("Set GITHUB_TOKEN or install gh to merge pull requests.") from e
        except subprocess.CalledProcessError as e:
            raise EngineError(f"gh pr merge failed: {(e.stderr or '').strip()[:300]}") from e


def make_engine(name: str) -> Engine:
    if name == "devin":
        if not devin_configured():
            raise EngineError("Devin mode is not configured on this server (DEVIN_API_KEY missing).")
        return DevinEngine()
    return LocalEngine()
