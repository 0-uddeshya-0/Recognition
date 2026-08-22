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


# --- design as code -------------------------------------------------------------

EXAMPLE = Path(__file__).resolve().parent.parent / "design" / "house.py"


def move_wall_i3_west(code: str) -> str:
    """Wall I3 (and the end of I4) 600 mm west; Flur/Bad shrink, the Schlafzimmer grows to 5.0 × 5.5 m."""
    return (code.replace("7.375", "6.775")          # I3 both ends, I4 end
                .replace("(7.45,", "(6.85,")        # Schlafzimmer x0
                .replace("(7.3,", "(6.7,"))         # Flur and Bad x1


@pytest.fixture(scope="module")
def code_job() -> dict:
    r = client.post("/api/jobs", data={"code": EXAMPLE.read_text(encoding="utf-8"), "project": "Haus am Hang"})
    assert r.status_code == 200, r.text
    return wait_done(r.json()["job_id"])


def test_design_example_endpoint():
    r = client.get("/api/design/example")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text == EXAMPLE.read_text(encoding="utf-8") and "House(" in r.text


def test_code_job_builds_and_runs(code_job, fzk_job):
    j = code_job
    assert j["status"] == "done", j["error"]
    assert j["source"] == "code" and j["code"] == EXAMPLE.read_text(encoding="utf-8")
    assert j["project"] == "Haus am Hang" and j["model_name"] == "haus-am-hang.py"
    assert [s["name"] for s in j["steps"]][:2] == ["Build model", "Load model"] and len(j["steps"]) == 6
    assert [s["status"] for s in j["steps"]] == ["done"] * 6
    assert "model.ifc" in j["steps"][0]["detail"]
    c = j["summary"]["counts"]
    assert {k: c[k] for k in ("walls", "spaces", "doors", "windows")} == {"walls": 9, "spaces": 6, "doors": 6, "windows": 9}
    assert j["summary"]["compliance"]["status"] == "PASS"
    run_dir = Path(store.get(j["id"]).result_dir)
    assert (run_dir / "house.py").read_text(encoding="utf-8") == j["code"] and (run_dir / "model.ifc").is_file()
    # uploaded / sample jobs are IFC jobs without code
    assert fzk_job["source"] == "ifc" and fzk_job["code"] is None


def test_mesh_json(code_job, fzk_job):
    jid = code_job["id"]
    r = client.get(f"/jobs/{jid}/mesh.json?r=1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    mesh = r.json()
    assert set(mesh) == {"elements", "bounds"} and len(mesh["bounds"]) == 6
    els = mesh["elements"]
    assert {e["cls"] for e in els} == {"IfcWall", "IfcSpace", "IfcDoor", "IfcWindow"}
    assert sum(e["cls"] == "IfcWall" for e in els) == 9 and sum(e["cls"] == "IfcSpace" for e in els) == 6
    bedroom = next(e for e in els if e["cls"] == "IfcSpace" and e["tag"] == "R-04")
    assert bedroom["name"] == "Schlafzimmer" and bedroom["storey"] == "Erdgeschoss"
    for e in els:
        assert set(e) == {"tag", "name", "cls", "storey", "verts", "faces"}
        assert len(e["verts"]) % 3 == 0 and len(e["faces"]) % 3 == 0 and e["faces"]
        assert max(e["faces"]) < len(e["verts"]) // 3 and min(e["faces"]) >= 0
        assert all(isinstance(v, float) and round(v, 4) == v for v in e["verts"])
        assert e["cls"] != "IfcWall" or e["tag"] == "" and e["name"]
    assert {e["tag"] for e in els if e["cls"] == "IfcDoor"} == {f"D-{i:02d}" for i in range(1, 7)}
    minx, miny, minz, maxx, maxy, maxz = mesh["bounds"]
    assert (minx, miny, minz) == pytest.approx((-0.15, -0.15, 0.0), abs=0.01)
    assert (maxx, maxy, maxz) == pytest.approx((12.15, 10.15, 2.5), abs=0.01)
    # cached next to the package, served again from the cache, not bundled as a deliverable
    assert (Path(store.get(jid).result_dir) / "mesh.json").is_file()
    assert client.get(f"/jobs/{jid}/mesh.json").json()["bounds"] == mesh["bounds"]
    import io as _io, zipfile as _zip
    names = _zip.ZipFile(_io.BytesIO(client.get(f"/jobs/{jid}/bundle/all").content)).namelist()
    assert not any(n.endswith("mesh.json") for n in names) and any(n.endswith("house.py") for n in names)
    # an IFC job meshes its uploaded model with the same contract
    m = client.get(f"/jobs/{fzk_job['id']}/mesh.json").json()
    assert any(e["cls"] == "IfcSpace" and e["tag"] == "R-04" for e in m["elements"])
    assert len([e for e in m["elements"] if e["cls"] == "IfcWall"]) == 13


def test_code_message_rebuilds(code_job, fzk_job):
    jid = code_job["id"]
    before = client.get(f"/api/jobs/{jid}/package").json()["schedules"]["rooms"]
    assert float(next(r for r in before if r["tag"] == "R-04")["area_m2"]) < 25
    code = move_wall_i3_west(code_job["code"])
    assert code != code_job["code"]
    r = client.post(f"/api/jobs/{jid}/message", json={"code": code})
    assert r.status_code == 200, r.text
    j = wait_done(jid)
    assert j["status"] == "done", j["error"]
    assert len(j["runs"]) == 2 and j["runs"][-1]["trigger"] == "code" and j["code"] == code
    assert j["steps"][0]["name"] == "Build model" and j["steps"][0]["status"] == "done"
    rooms = client.get(f"/api/jobs/{jid}/package").json()["schedules"]["rooms"]
    bedroom = next(r for r in rooms if r["tag"] == "R-04")
    assert bedroom["name"] == "Schlafzimmer" and float(bedroom["area_m2"]) > 26
    # the mesh follows the new package: the bedroom now starts further west
    mesh = client.get(f"/jobs/{jid}/mesh.json?r=2").json()
    bed = next(e for e in mesh["elements"] if e["cls"] == "IfcSpace" and e["tag"] == "R-04")
    assert min(bed["verts"][0::3]) == pytest.approx(6.85, abs=0.01)
    # the same code again is a no-op; code on an IFC job is refused
    assert client.post(f"/api/jobs/{jid}/message", json={"code": code}).status_code == 400
    r = client.post(f"/api/jobs/{fzk_job['id']}/message", json={"code": code})
    assert r.status_code == 400 and "IFC" in r.json()["detail"]


def test_code_with_syntax_error_fails_and_has_no_mesh():
    code = EXAMPLE.read_text(encoding="utf-8").replace("eg = h.storey(", "eg = h.storey((")
    r = client.post("/api/jobs", data={"code": code})
    assert r.status_code == 200, r.text
    j = wait_done(r.json()["job_id"])
    assert j["status"] == "failed" and j["project"] == "House" and j["source"] == "code"
    assert "SyntaxError" in j["error"] and "house.py" in j["error"]
    assert j["steps"][0]["name"] == "Build model" and j["steps"][0]["status"] == "failed"
    assert "SyntaxError" in j["steps"][0]["detail"]
    assert [s["status"] for s in j["steps"][1:]] == ["pending"] * 5
    assert client.get(f"/jobs/{j['id']}/mesh.json").status_code == 409
    assert client.get(f"/api/jobs/{j['id']}/package").status_code == 409
    # a script that runs but writes nothing is reported too
    r = client.post("/api/jobs", data={"code": "print('hello')\n"})
    j = wait_done(r.json()["job_id"])
    assert j["status"] == "failed" and "model.ifc" in j["error"]


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


def test_studio_pages(fzk_job):
    assert client.get("/studio").status_code == 200
    assert "house.py" in client.get("/studio").text
    assert client.get(f"/studio/{fzk_job['id']}").status_code == 200
    assert client.get("/studio/nope").status_code == 404


class FakeNakle:
    """Stands in for ui.chat.NakleClient: canned structured answers, no network."""
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
    def complete(self, system, user, conversation_id=None):
        self.calls.append({"system": system, "user": user, "conversation_id": conversation_id})
        reply, code = self.answers.pop(0)
        return {"content": reply, "structured_output": {"reply": reply, "code": code}, "conversation_id": "conv-1", "usage": {}}


def test_chat_edits_the_house(code_job, monkeypatch):
    import ui.app as A
    jid = code_job["id"]
    current = client.get(f"/api/jobs/{jid}").json()["code"]   # earlier tests may have rebuilt this shared job
    taller = current.replace('height=2.5)', 'height=2.7)', 1)
    assert taller != current
    fake = FakeNakle([("Raised the storey to 2.70 m clear height.", taller),
                      ("The hall is 9.8 m²; hallways have no minimum area in this ruleset.", None)])
    monkeypatch.setattr(A, "chat_client", fake)
    r = client.post(f"/api/jobs/{jid}/chat", json={"text": "make the rooms 2.7 m high"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True and "2.70" in r.json()["reply"]
    assert "Current house.py" in fake.calls[0]["user"] and "Latest check:" in fake.calls[0]["user"]
    j = wait_done(jid)
    assert j["status"] == "done" and j["code"] == taller and j["runs"][-1]["trigger"] == "code"
    rooms = client.get(f"/api/jobs/{jid}/package").json()["schedules"]["rooms"]
    assert all(float(x["height_m"]) == 2.7 for x in rooms)
    assert [m["role"] for m in j["chat"]] == ["user", "assistant"] and j["chat"][1]["changed"] is True
    # a question: no code, no rebuild, memory via the conversation id
    r = client.post(f"/api/jobs/{jid}/chat", json={"text": "how big is the hall?"})
    assert r.status_code == 200 and r.json()["changed"] is False
    assert fake.calls[1]["conversation_id"] == "conv-1"
    assert len(client.get(f"/api/jobs/{jid}").json()["runs"]) == len(j["runs"])
    assert client.post(f"/api/jobs/{jid}/chat", json={"text": ""}).status_code == 400


def test_chat_refuses_ifc_jobs_and_reports_model_errors(fzk_job, code_job, monkeypatch):
    import httpx
    import ui.app as A
    assert client.post(f"/api/jobs/{fzk_job['id']}/chat", json={"text": "widen the doors"}).status_code == 400

    class Down:
        def complete(self, *a, **k):
            raise httpx.ConnectError("nakle is down")
    monkeypatch.setattr(A, "chat_client", Down())
    r = client.post(f"/api/jobs/{code_job['id']}/chat", json={"text": "add a window"})
    assert r.status_code == 502 and "down" in r.json()["detail"]
    assert client.get(f"/api/jobs/{code_job['id']}").json()["chat"][-1].get("error") is True


def test_chat_parse_fallback_to_code_block():
    from ui import chat as C
    reply, code = C.parse({"content": "Done.\n```python\nprint(1)\n```", "structured_output": None})
    assert reply == "Done." and code == "print(1)\n"
    reply, code = C.parse({"content": "Just an answer.", "structured_output": None})
    assert reply == "Just an answer." and code is None
    reply, code = C.parse({"content": "", "structured_output": {"reply": "ok", "code": "   "}})
    assert reply == "ok" and code is None
