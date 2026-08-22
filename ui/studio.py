"""The Studio: the building as code on the left, 3D and 2D on the right, and a chat that edits the code.

Three things live here, all used only by the Studio page:

* meshes — every wall, room, door and window of a package's model, triangulated
  by ifcopenshell in world coordinates and tagged like the schedules, so the
  viewer can colour what the report names; cached next to the package;
* chat — a request in words → a new ``house.py`` → rebuild, through nakle
  (an OpenAI-style ``chat/completions`` service in front of Claude; ``NAKLE_URL``,
  ``NAKLE_MODEL``); the answer is structured JSON ``{"reply", "code"}``;
* the routes, registered on the app by :func:`register`.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import httpx
import ifcopenshell.geom
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from recognition import __version__
from recognition import model as M

from . import engine as E
from .jobs import Job, load_package


# --- meshes for the 3D view ------------------------------------------------------
MESH_FILE = "mesh.json"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _settings() -> ifcopenshell.geom.settings:
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def _triangles(settings, entity) -> tuple[list[float], list[int]] | None:
    try:
        shape = ifcopenshell.geom.create_shape(settings, entity)
    except Exception:
        return None
    verts = [round(v, 4) for v in shape.geometry.verts]
    faces = [int(i) for i in shape.geometry.faces]
    return (verts, faces) if verts and faces else None


def build_mesh(model_path: Path) -> dict:
    """Mesh every wall, space, door and window of the model, tags as in the schedules."""
    m = M.load(model_path)
    settings = _settings()
    elements: list[dict] = []
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    groups = (("IfcWall", m.walls, lambda e: e.name), ("IfcSpace", m.spaces, lambda e: e.label),
              ("IfcDoor", m.doors, lambda e: e.name), ("IfcWindow", m.windows, lambda e: e.name))
    for cls, items, name_of in groups:
        for el in items:
            tri = _triangles(settings, m.ifc.by_guid(el.guid))
            if tri is None:
                continue
            verts, faces = tri
            for i in range(0, len(verts), 3):
                for k in range(3):
                    v = verts[i + k]
                    lo[k] = v if v < lo[k] else lo[k]
                    hi[k] = v if v > hi[k] else hi[k]
            elements.append({"tag": el.tag, "name": name_of(el), "cls": cls, "storey": el.storey,
                             "verts": verts, "faces": faces})
    bounds = [*lo, *hi] if elements else [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return {"elements": elements, "bounds": bounds}


def mesh_json(model_path: Path, out_dir: Path) -> Path:
    """Path of <out_dir>/mesh.json, building it from the model on first call."""
    target = out_dir / MESH_FILE
    if target.is_file():
        return target
    with _locks_guard:
        lock = _locks.setdefault(str(target), threading.Lock())
    with lock:  # two viewers asking at once build once
        if target.is_file():
            return target
        data = build_mesh(model_path)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, target)
    return target


# --- chat: words in, a new house.py out -------------------------------------------
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


CLIENT = NakleClient()  # swapped for a fake in tests


# --- routes ------------------------------------------------------------------------

class ChatIn(BaseModel):
    text: str


def register(app, *, store, get_job, engine_for, templates) -> None:
    """Mount the Studio on the app: the page, the meshes, the chat, the example script."""

    def page(request: Request, job_id: str | None) -> HTMLResponse:
        return templates.TemplateResponse(request, "studio.html", {"job_id": job_id, "version": __version__})

    @app.get("/studio", response_class=HTMLResponse)
    def studio(request: Request):
        return page(request, None)

    @app.get("/studio/{job_id}", response_class=HTMLResponse)
    def studio_job(request: Request, job_id: str):
        get_job(job_id)
        return page(request, job_id)

    @app.get("/api/design/example", response_class=PlainTextResponse)
    def design_example():
        return E.example_design()

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
            reply, code, conv = propose(CLIENT, text, job.code, pkg.get("summary"), pkg.get("results"), job.chat_conversation)
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
