"""FastAPI app: one page, three states, no login.

    uv run recognition-ui            # http://localhost:8000

Routes
    GET  /                          page (state 1)
    GET  /jobs/{id}                 same page, deep-linked to a job (state 2/3)
    POST /api/jobs                  multipart: ifc file | sample=<key> | code=<house.py> (+ project?),
                                    instruction?, rules_yaml?, engine?
    GET  /api/jobs                  recent jobs
    GET  /api/jobs/{id}             job JSON (status, steps, summary, pr_url, delta, source, code)
    GET  /api/jobs/{id}/package     summary + findings + schedules of the latest run
    POST /api/jobs/{id}/message     {text, rules_yaml?, code?}  — request change / apply rules / rebuild design
    POST /api/jobs/{id}/approve
    GET  /jobs/{id}/files/{path}    files from the latest package (traversal-safe)
    GET  /jobs/{id}/bundle/{kind}   zip: pdf | dxf | schedules | all
    GET  /jobs/{id}/mesh.json       triangle meshes of the latest package's model for the 3D viewer
    GET  /api/rules                 default rules YAML
    GET  /studio[/{id}]             code | 3D + 2D, one Build button (the focused view)
    POST /api/jobs/{id}/chat        {text} — ask for a change in words; the model rewrites house.py, the job rebuilds
    GET  /api/design/example        design/house.py — the starting point for a house written as code
"""
from __future__ import annotations

import io
import os
import time
import shutil
import zipfile
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from recognition import __version__

from . import chat as C
from . import engine as E
from .jobs import REPO_ROOT, Job, JobStore, load_package, slug
from .mesh import MESH_FILE, mesh_json

E.load_dotenv()

HERE = Path(__file__).resolve().parent
MAX_UPLOAD = 100 * 1024 * 1024
SAMPLES = {
    "fzk": {"label": "FZK-Haus", "hint": "2 storeys · passes", "path": REPO_ROOT / "samples" / "AC20-FZK-Haus.ifc"},
    "duplex": {"label": "Duplex", "hint": "4 storeys · fails on doors", "path": REPO_ROOT / "samples" / "Duplex.ifc"},
    "smiley": {"label": "Smiley West", "hint": "10 houses · ~20 s", "path": REPO_ROOT / "samples" / "extended" / "AC20-Smiley-West.ifc"},
}
MEDIA = {".png": "image/png", ".svg": "image/svg+xml", ".pdf": "application/pdf", ".dxf": "application/dxf",
         ".csv": "text/csv", ".md": "text/markdown", ".json": "application/json", ".ifc": "application/x-step",
         ".yaml": "text/yaml"}

app = FastAPI(title="Recognition UI", version=__version__)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

store = JobStore()
chat_client = C.NakleClient()
engines: dict[str, E.Engine] = {"local": E.LocalEngine()}
if E.devin_configured():
    engines["devin"] = E.DevinEngine()


def engine_for(job: Job) -> E.Engine:
    return engines.get(job.engine) or engines["local"]


def get_job(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return job


def page(request: Request, job_id: str | None) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {
        "job_id": job_id, "devin": "devin" in engines, "repo": E.github_repo(),
        "samples_json": [{"key": k, "label": v["label"], "hint": v["hint"]} for k, v in SAMPLES.items()],
        "default_rules": E.default_rules_yaml(), "version": __version__,
    })


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return page(request, None)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    get_job(job_id)
    return page(request, job_id)


@app.get("/studio", response_class=HTMLResponse)
def studio(request: Request):
    """Source code on the left, 3D and 2D on the right, one Build button — nothing else."""
    return templates.TemplateResponse(request, "studio.html", {"job_id": None, "version": __version__,
                                                               "default_rules": E.default_rules_yaml()})


@app.get("/studio/{job_id}", response_class=HTMLResponse)
def studio_job(request: Request, job_id: str):
    get_job(job_id)
    return templates.TemplateResponse(request, "studio.html", {"job_id": job_id, "version": __version__,
                                                               "default_rules": E.default_rules_yaml()})


@app.get("/api/rules", response_class=PlainTextResponse)
def rules():
    return E.default_rules_yaml()


@app.get("/api/design/example", response_class=PlainTextResponse)
def design_example():
    return E.example_design()


@app.get("/api/jobs")
def list_jobs():
    return [{"id": j.id, "project": j.project, "model_name": j.model_name, "status": j.status, "engine": j.engine,
             "created_at": j.created_at, "compliance": (j.summary or {}).get("compliance", {}).get("status")}
            for j in store.all()[:20]]


@app.post("/api/jobs")
async def create_job(file: UploadFile | None = File(None), sample: str | None = Form(None),
                     code: str | None = Form(None), project: str | None = Form(None),
                     instruction: str | None = Form(None), rules_yaml: str | None = Form(None),
                     engine: str = Form("local")):
    if engine not in engines:
        raise HTTPException(400, f"engine '{engine}' is not available on this server")
    if code is not None and code.strip():
        # the house as Python: the engine builds model.ifc from it before the pipeline runs
        name = (project or "").strip() or "House"
        job = store.create(Path(), f"{slug(name).lower()}.py", engine, project=name)
        job.source, job.code = "code", code
    elif sample:
        spec = SAMPLES.get(sample)
        if not spec or not spec["path"].exists():
            raise HTTPException(400, f"unknown sample '{sample}'")
        job = store.create(spec["path"], spec["path"].name, engine)
    elif file is not None and file.filename:
        if not file.filename.lower().endswith(".ifc"):
            raise HTTPException(400, "please upload an .ifc file")
        job = store.create(Path(), file.filename, engine)
        dest = Path(job.dir) / "model.ifc"
        size = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    out.close()
                    shutil.rmtree(job.dir, ignore_errors=True)
                    raise HTTPException(413, "file is larger than 100 MB")
                out.write(chunk)
        job.model_path = str(dest)
    else:
        raise HTTPException(400, "upload an .ifc file, pick a sample or write the house as code")
    rules_text = rules_yaml if rules_yaml and rules_yaml.strip() else None
    try:
        engine_for(job).start(job, Path(job.model_path), (instruction or "").strip() or None, rules_text)
    except E.EngineError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_json(job_id: str):
    job = get_job(job_id)
    engine_for(job).poll(job)
    return job.to_dict()


@app.get("/api/jobs/{job_id}/package")
def job_package(job_id: str):
    job = get_job(job_id)
    if not job.result_dir:
        raise HTTPException(409, "no package yet")
    return load_package(Path(job.result_dir))


class Message(BaseModel):
    text: str = ""
    rules_yaml: str | None = None
    code: str | None = None  # edited house script (code jobs): rebuild + re-run when it differs from job.code


@app.post("/api/jobs/{job_id}/message")
def job_message(job_id: str, msg: Message):
    job = get_job(job_id)
    text = msg.text.strip()
    eng = engine_for(job)
    try:
        if (job.engine == "local" and text and not E.rules_changed(job, msg.rules_yaml)
                and not E.code_changed(job, msg.code) and "devin" in engines):
            # a free-text request escalates the job to Devin: same model, same rules, a real engineer
            engines["devin"].start(job, Path(job.model_path), text, msg.rules_yaml)
        else:
            eng.message(job, text, msg.rules_yaml, msg.code)
    except E.EngineError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "engine": job.engine, "status": job.status}


class ChatIn(BaseModel):
    text: str


@app.post("/api/jobs/{job_id}/chat")
def job_chat(job_id: str, msg: ChatIn):
    """A request in words → the model rewrites house.py → rebuild (when something changed)."""
    job = get_job(job_id)
    text = msg.text.strip()
    if not text:
        raise HTTPException(400, "say what you want changed")
    if job.source != "code" or not job.code:
        raise HTTPException(400, "only a house written as code can be changed by chat")
    if job.status == "running":
        raise HTTPException(409, "a build is running — wait for it to finish")
    pkg = load_package(Path(job.result_dir)) if job.result_dir else {}
    job.chat.append({"role": "user", "text": text, "at": time.time()})
    try:
        reply, code, conv = C.propose(chat_client, text, job.code, pkg.get("summary"), pkg.get("results"), job.chat_conversation)
    except httpx.HTTPError as e:
        job.chat.append({"role": "assistant", "text": f"The model did not answer: {e}", "error": True, "at": time.time()})
        raise HTTPException(502, f"model unavailable: {e}")
    job.chat_conversation = conv or job.chat_conversation
    changed = False
    if code is not None:
        try:
            engine_for(job).message(job, "", None, code)
            changed = True
        except E.EngineError as e:
            reply = f"{reply} (not rebuilt: {e})"
    job.chat.append({"role": "assistant", "text": reply, "changed": changed, "at": time.time()})
    return {"reply": reply, "changed": changed, "status": job.status, "chat": job.chat}


@app.post("/api/jobs/{job_id}/approve")
def job_approve(job_id: str):
    job = get_job(job_id)
    try:
        engine_for(job).approve(job)
    except E.EngineError as e:
        raise HTTPException(400, str(e))
    return {"approved": job.approved, "pr_url": job.pr_url}


def _safe_path(job: Job, rel: str) -> Path:
    if not job.result_dir:
        raise HTTPException(409, "no package yet")
    root = Path(job.result_dir).resolve()
    target = (root / rel).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "no such file")
    return target


@app.get("/jobs/{job_id}/files/{path:path}")
def job_file(job_id: str, path: str, download: bool = False):
    job = get_job(job_id)
    target = _safe_path(job, path)
    media = MEDIA.get(target.suffix.lower(), "application/octet-stream")
    headers = {"Content-Disposition": f'attachment; filename="{target.name}"'} if download else {}
    return FileResponse(target, media_type=media, headers=headers)


BUNDLES = {"pdf": ("sheets", "*.pdf"), "dxf": ("sheets", "*.dxf"), "schedules": ("schedules", "*"), "all": ("", "**/*")}


@app.get("/jobs/{job_id}/bundle/{kind}")
def job_bundle(job_id: str, kind: str):
    job = get_job(job_id)
    if kind not in BUNDLES or not job.result_dir:
        raise HTTPException(404, "no such bundle")
    sub, pattern = BUNDLES[kind]
    root = Path(job.result_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((root / sub).glob(pattern)):
            if p.name == MESH_FILE or p.suffix == ".tmp":  # viewer cache, not a deliverable
                continue
            if p.is_file() and p.name != "rules.yaml" or p.name == "rules.yaml" and kind == "all":
                z.write(p, f"{job.project}/{p.relative_to(root)}")
    buf.seek(0)
    name = f"{job.project}-{kind}.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/jobs/{job_id}/mesh.json")
def job_mesh(job_id: str):
    """Meshes of the model behind the latest package (for code jobs that is the IFC built in that run)."""
    job = get_job(job_id)
    if not job.result_dir:
        raise HTTPException(409, "no package yet")
    out_dir = Path(job.result_dir).resolve()
    built = out_dir / "model.ifc"
    model_path = built if job.source == "code" and built.is_file() else Path(job.model_path)
    if not model_path.is_file():
        raise HTTPException(404, "model file is gone")
    try:
        target = mesh_json(model_path, out_dir)
    except Exception as e:  # a model ifcopenshell cannot triangulate is a 500 with a reason, not a traceback page
        raise HTTPException(500, f"could not mesh the model: {e}")
    return FileResponse(target, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.exception_handler(E.EngineError)
def engine_error(_, exc: E.EngineError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def main() -> None:
    import uvicorn
    host = os.environ.get("RECOGNITION_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("RECOGNITION_UI_PORT", "8000"))
    print(f"Recognition UI {__version__} — http://{host}:{port}  (engines: {', '.join(engines)})")
    uvicorn.run("ui.app:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
