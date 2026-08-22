"""Backend tests for the UI with the LocalEngine — no network, no Devin.

The FZK sample runs through the real pipeline (~3 s per run); a module-scoped
job is shared so the suite stays around 10 s.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ["DEVIN_API_KEY"] = ""  # never select the Devin engine in tests, whatever .env says
os.environ.setdefault("RECOGNITION_JOBS_DIR", str(Path(__file__).resolve().parent.parent / "out" / "ui-test-jobs"))

from fastapi.testclient import TestClient  # noqa: E402

from ui import engine as E  # noqa: E402
from ui.app import app, store  # noqa: E402
from ui.jobs import Job  # noqa: E402

client = TestClient(app)


def wait_done(job_id: str, timeout: float = 90) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.25)
    raise AssertionError("job did not finish in time")


@pytest.fixture(scope="module")
def fzk_job() -> dict:
    r = client.post("/api/jobs", data={"sample": "fzk"})
    assert r.status_code == 200, r.text
    return wait_done(r.json()["job_id"])


def test_engines_are_local_only():
    assert "devin" not in __import__("ui.app", fromlist=["engines"]).engines


def test_page_and_rules():
    assert client.get("/").status_code == 200
    assert "window.RECOGNITION" in client.get("/").text
    assert "ROOM-MIN-AREA" in client.get("/api/rules").text
    assert client.get("/jobs/nope").status_code == 404


def test_create_requires_model():
    assert client.post("/api/jobs", data={}).status_code == 400
    assert client.post("/api/jobs", data={"sample": "nope"}).status_code == 400
    r = client.post("/api/jobs", files={"file": ("model.txt", b"not ifc")})
    assert r.status_code == 400
    assert client.post("/api/jobs", data={"sample": "fzk", "engine": "devin"}).status_code == 400


def test_lifecycle_fzk(fzk_job):
    j = fzk_job
    assert j["status"] == "done", j["error"]
    assert [s["status"] for s in j["steps"]] == ["done"] * 5
    assert j["summary"]["compliance"]["status"] == "PASS"
    assert len(j["summary"]["sheets"]) == 2
    assert j["runs"][0]["trigger"] == "initial" and j["delta"] is None
    assert client.get(f"/jobs/{j['id']}").status_code == 200  # deep link renders


def test_package_and_files(fzk_job):
    jid = fzk_job["id"]
    p = client.get(f"/api/jobs/{jid}/package").json()
    assert {k: len(v) for k, v in p["schedules"].items()} == {"rooms": 7, "doors": 5, "windows": 11}
    assert len(p["results"]) == 27 and p["failing_tags"] == []
    assert p["schedules"]["rooms"][0]["tag"] == "R-01"
    for rel, ctype in (("sheets/A-101_Erdgeschoss.png", "image/png"), ("sheets/A-101_Erdgeschoss.pdf", "application/pdf"),
                       ("sheets/A-101_Erdgeschoss.dxf", "application/dxf"), ("schedules/rooms.csv", "text/csv"),
                       ("model.detailed.ifc", "application/x-step"), ("report.md", "text/markdown")):
        r = client.get(f"/jobs/{jid}/files/{rel}")
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype), rel
    assert "attachment" in client.get(f"/jobs/{jid}/files/model.detailed.ifc?download=1").headers["content-disposition"]
    assert client.get(f"/jobs/{jid}/files/../../../pyproject.toml").status_code in (400, 404)
    assert client.get(f"/jobs/{jid}/files/%2e%2e/%2e%2e/pyproject.toml").status_code in (400, 404)
    assert client.get(f"/jobs/{jid}/files/nope.png").status_code == 404
    z = client.get(f"/jobs/{jid}/bundle/pdf")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip" and len(z.content) > 10_000


def test_rules_rerun_changes_status(fzk_job):
    jid = fzk_job["id"]
    rules = client.get("/api/rules").text.replace("bedroom: 9.0", "bedroom: 25.0")
    r = client.post(f"/api/jobs/{jid}/message", json={"text": "", "rules_yaml": rules})
    assert r.status_code == 200, r.text
    j = wait_done(jid)
    assert j["status"] == "done" and j["summary"]["compliance"]["status"] == "FAIL"
    assert j["summary"]["compliance"]["errors"] == 1
    assert j["delta"]["status_before"] == "PASS" and j["delta"]["status_after"] == "FAIL"
    assert j["delta"]["new_failures"] == ["ROOM-MIN-AREA R-04"]
    p = client.get(f"/api/jobs/{jid}/package").json()
    assert p["failing_tags"] == ["R-04"]
    fail = next(r for r in p["results"] if not r["passed"])
    assert fail["element_tag"] == "R-04" and "Schlafzimmer" in fail["message"]
    # the same rules again is a no-op, a free-text request cannot be served locally
    assert client.post(f"/api/jobs/{jid}/message", json={"text": "", "rules_yaml": rules}).status_code == 400
    r = client.post(f"/api/jobs/{jid}/message", json={"text": "add a section through the stair"})
    assert r.status_code == 400 and "Devin" in r.json()["detail"]
    assert client.post(f"/api/jobs/{jid}/message", json={"text": "", "rules_yaml": "rules: [broken"}).status_code == 400


def test_approve_local(fzk_job):
    jid = fzk_job["id"]
    r = client.post(f"/api/jobs/{jid}/approve")
    assert r.status_code == 200 and r.json()["approved"] is True
    assert client.get(f"/api/jobs/{jid}").json()["approved"] is True


def test_upload_file_and_list():
    ifc = Path(__file__).resolve().parent.parent / "samples" / "AC20-FZK-Haus.ifc"
    with ifc.open("rb") as fh:
        r = client.post("/api/jobs", files={"file": ("uploaded.ifc", fh, "application/octet-stream")},
                        data={"instruction": "Bedrooms must be ≥ 10 m²"})
    assert r.status_code == 200
    j = wait_done(r.json()["job_id"])
    assert j["status"] == "done" and j["model_name"] == "uploaded.ifc" and j["project"] == "uploaded"
    assert "Devin" in j["note"]  # free text without Devin: baseline generated, note shown
    assert any(x["id"] == j["id"] for x in client.get("/api/jobs").json())


# --- Devin engine, fully offline -----------------------------------------------

class FakeDevin:
    def __init__(self):
        self.uploaded: list[Path] = []
        self.sessions: dict[str, dict] = {}
        self.messages: list[str] = []
        self.state = {"status_enum": "working", "messages": [], "structured_output": None, "pull_request": None}

    def upload(self, path):
        self.uploaded.append(path)
        return "https://api.devin.ai/attachments/abc123"

    def create_session(self, body):
        self.sessions["devin-1"] = body
        return {"session_id": "devin-1", "url": "https://app.devin.ai/sessions/1"}

    def get_session(self, sid):
        return {"session_id": sid, **self.state}

    def send_message(self, sid, text):
        self.messages.append(text)


def test_devin_engine_offline(tmp_path, monkeypatch):
    fake = FakeDevin()
    eng = E.DevinEngine(client=fake, repo="org/repo", git_dir=tmp_path, poll_interval=0)
    job = Job("abc123def4", time.time(), "House.ifc", str(tmp_path / "House.ifc"), str(tmp_path / "job"), project="House")
    (tmp_path / "House.ifc").write_bytes(b"ISO-10303-21;")
    eng.start(job, tmp_path / "House.ifc", "Bedrooms must be >= 25 m2", None)
    for _ in range(50):
        if job.devin_session_id:
            break
        time.sleep(0.05)
    assert job.devin_session_id == "devin-1" and job.engine == "devin" and job.branch == "detail/house-abc123"
    prompt = fake.sessions["devin-1"]["prompt"]
    assert prompt.startswith("Bedrooms must be >= 25 m2") and 'ATTACHMENT:"https://api.devin.ai/attachments/abc123"' in prompt
    assert "deliveries/House/" in prompt and "org/repo" in prompt and "playbook" in prompt.lower()
    assert fake.sessions["devin-1"]["structured_output_schema"]["required"] == ["branch", "package_dir", "status"]
    assert [s.status for s in job.steps][:3] == ["done", "done", "running"]

    fake.state["messages"] = [{"type": "devin_message", "message": "Editing the ruleset"}]
    eng.poll(job)
    assert job.devin_message == "Editing the ruleset" and job.status == "running"

    # Devin gets stuck (e.g. no push access) and asks: the job stays running but accepts a reply
    fake.state.update(status_enum="blocked", messages=[{"type": "devin_message", "message": "I cannot push, please grant access"}])
    eng.poll(job)
    assert job.status == "running" and job.devin_waiting and job.devin_message == "I cannot push, please grant access"
    eng.message(job, "Access granted, push now", None)
    assert fake.messages[-1].startswith("Access granted") and not job.devin_waiting and len(job.runs) == 1
    fake.state.update(status_enum="working")

    # Devin finishes: a PR and structured output appear; the package is fetched from git (stubbed)
    fake.state.update(status_enum="blocked", pull_request={"url": "https://github.com/org/repo/pull/7"},
                      structured_output={"branch": "detail/house-abc123", "package_dir": "deliveries/House", "status": "FAIL", "changed": "bedroom 9 -> 25"})
    monkeypatch.setattr(eng, "_remote_head", lambda branch: "deadbeef" * 5)

    def fetch(branch, package_dir, dest):
        src = Path(__file__).resolve().parent.parent / "examples" / "Duplex"
        for name in ("summary.json", "report.json", "report.md"):
            (dest / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(eng, "_fetch_package", fetch)
    eng.poll(job)
    assert job.status == "done" and job.pr_url == "https://github.com/org/repo/pull/7"
    assert job.summary["compliance"]["status"] == "FAIL" and job.runs[-1].commit.startswith("deadbeef")
    assert [s.status for s in job.steps] == ["done"] * 5

    # follow-up message goes to the same session and starts a new run
    eng.message(job, "Also widen D-03", None)
    assert fake.messages and "Also widen D-03" in fake.messages[-1] and "deliveries/House" in fake.messages[-1]
    assert job.status == "running" and len(job.runs) == 2

    # approve without a PR URL or merge tool is a clean error
    job.pr_url = None
    with pytest.raises(E.EngineError):
        eng.approve(job)
