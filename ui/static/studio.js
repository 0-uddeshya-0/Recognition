/* Recognition Studio — the building as code on the left, 3D and 2D on the right, one Build button, a chat that edits the code.
 * One ES module: the Three.js viewer (three 0.170 from the importmap, pinned CDN) and the page. */
import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/controls/OrbitControls.js";

const COLOR = { wall: 0x6B7480, door: 0xB5651D, window: 0x2F6FE4, space: 0xDCE6F5, fail: 0xC8352A,
                bg: 0xFFFFFF, grid: 0xE1E6EA, axis: 0xC7CED5, edge: 0x15191D, sky: 0xFFFFFF, ground: 0xD8DEE3 };
const OPACITY = { space: 0.35, spaceFail: 0.55 };
const EDGE_LIMIT = 600000;  // triangles; beyond this, skip the line work
const FOV = 32;

const kindOf = (cls) => cls === "IfcSpace" ? "space" : cls === "IfcDoor" ? "door" : cls === "IfcWindow" ? "window" : "wall";

let R = null;       // persistent renderer/camera/controls; lives across mounts until dispose()
let M = null;       // the current model: { json, root, items, bounds, center, radius, tris }
let V = null;       // the current mount: { container, label, ro, raf, hover, pinned, opts, listeners }
let POSE = null;    // { json, position, target } — camera pose remembered for the same mesh across remounts

// --- renderer ------------------------------------------------------------------
function ensureRenderer() {
  if (R) return R;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(COLOR.bg, 1);
  const canvas = renderer.domElement;
  canvas.className = "v3-canvas";
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.05, 2000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.12;
  controls.screenSpacePanning = false;            // pan along the ground, not the screen
  controls.zoomToCursor = true;
  controls.maxPolarAngle = Math.PI / 2 + 0.05;     // a whisker below the horizon, no further
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLOR.bg);
  const hemi = new THREE.HemisphereLight(COLOR.sky, COLOR.ground, 1.7);
  hemi.position.set(0, 0, 1);
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  scene.add(hemi, sun, sun.target, fill, new THREE.AmbientLight(0xffffff, 0.35));
  const raycaster = new THREE.Raycaster();
  R = { renderer, canvas, camera, controls, scene, sun, fill, raycaster, needsRender: true };
  controls.addEventListener("change", () => { R.needsRender = true; });
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); });
  canvas.addEventListener("webglcontextrestored", () => { R.needsRender = true; });
  return R;
}

// --- model ---------------------------------------------------------------------
function buildModel(json) {
  const root = new THREE.Group();
  const items = [];
  const total = (json.elements || []).reduce((n, e) => n + (e.faces ? e.faces.length / 3 : 0), 0);
  const edges = total <= EDGE_LIMIT;
  const edgeMat = new THREE.LineBasicMaterial({ color: COLOR.edge, transparent: true, opacity: 0.22, depthWrite: false });
  for (const el of json.elements || []) {
    if (!el.verts || !el.faces || el.faces.length < 3) continue;
    const kind = kindOf(el.cls);
    const indexed = new THREE.BufferGeometry();
    indexed.setAttribute("position", new THREE.Float32BufferAttribute(el.verts, 3));
    indexed.setIndex(el.verts.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(el.faces, 1) : new THREE.Uint16BufferAttribute(el.faces, 1));
    const geom = indexed.toNonIndexed();     // flat shading: crisp boxes, no smoothed corners
    geom.computeVertexNormals();
    geom.computeBoundingSphere();
    const mat = new THREE.MeshLambertMaterial({ color: COLOR[kind] });
    if (kind === "space") { mat.transparent = true; mat.opacity = OPACITY.space; mat.depthWrite = false; mat.side = THREE.DoubleSide; }
    const mesh = new THREE.Mesh(geom, mat);
    mesh.renderOrder = kind === "space" ? 2 : 0;
    mesh.userData = { tag: el.tag || "", name: el.name || "", cls: el.cls || "", storey: el.storey || "", kind };
    root.add(mesh);
    let line = null;
    if (edges && kind !== "space") {
      line = new THREE.LineSegments(new THREE.EdgesGeometry(indexed, 28), edgeMat);
      line.renderOrder = 1;
      root.add(line);
    }
    indexed.dispose();
    items.push({ mesh, line, kind, tag: el.tag || "", base: COLOR[kind] });
  }
  // bounds: trust the contract, fall back to the geometry
  let b = json.bounds;
  if (!b || b.length !== 6 || b.some((v) => !Number.isFinite(v))) {
    const box = new THREE.Box3().setFromObject(root);
    b = box.isEmpty() ? [0, 0, 0, 10, 10, 3] : [box.min.x, box.min.y, box.min.z, box.max.x, box.max.y, box.max.z];
  }
  const size = new THREE.Vector3(b[3] - b[0], b[4] - b[1], b[5] - b[2]);
  const center = new THREE.Vector3((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2);
  const radius = Math.max(size.length() / 2, 1);
  // ground grid, 1 m, just under the lowest point; major axis lines a touch darker
  const span = Math.ceil(Math.max(size.x, size.y)) + 6;
  const grid = new THREE.GridHelper(span, span, COLOR.axis, COLOR.grid);
  grid.material.transparent = true; grid.material.opacity = 0.75; grid.material.depthWrite = false;
  grid.rotation.x = Math.PI / 2;
  grid.position.set(Math.round(center.x), Math.round(center.y), b[2] - 0.01);
  grid.renderOrder = -1;
  root.add(grid);
  return { json, root, items, bounds: b, center, radius, tris: total, grid };
}

function disposeModel() {
  if (!M) return;
  R && R.scene.remove(M.root);
  M.root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material && o !== M.grid) { if (Array.isArray(o.material)) o.material.forEach((m) => m.dispose()); else o.material.dispose(); }
  });
  M.grid.material.dispose();
  M = null;
}

function fitCamera() {
  const { camera, controls, sun, fill } = R;
  const { center, radius } = M;
  const aspect = camera.aspect || 1;
  const vfov = THREE.MathUtils.degToRad(FOV);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
  const dist = (radius * 1.12) / Math.sin(Math.min(vfov, hfov) / 2);
  const dir = new THREE.Vector3(-1, -1, 0.85).normalize();     // from the south-west, above
  camera.position.copy(center).addScaledVector(dir, dist);
  camera.near = Math.max(0.02, dist / 500); camera.far = dist * 40;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.minDistance = radius * 0.05; controls.maxDistance = dist * 8;
  controls.update();
  sun.position.copy(center).add(new THREE.Vector3(-1, -0.55, 1.5).multiplyScalar(radius * 3));
  sun.target.position.copy(center);
  fill.position.copy(center).add(new THREE.Vector3(1.2, 0.8, 0.6).multiplyScalar(radius * 3));
  R.needsRender = true;
}

// --- styling (failing tags, rooms on/off, hover) --------------------------------
function applyStyle() {
  if (!M || !V) return;
  const failing = V.opts.failing instanceof Set ? V.opts.failing : new Set(V.opts.failing || []);
  const hovered = V.pinned || V.hover;
  for (const it of M.items) {
    const bad = it.tag !== "" && failing.has(it.tag);
    const color = bad ? COLOR.fail : it.base;
    it.failing = bad;
    it.mesh.material.color.setHex(color);
    if (it.kind === "space") {
      it.mesh.visible = !!V.opts.showRooms;
      it.mesh.material.opacity = bad ? OPACITY.spaceFail : OPACITY.space;
    }
    const hot = hovered === it;
    it.mesh.material.emissive.setHex(hot ? (bad ? 0x401008 : 0x1a2436) : 0x000000);
    if (hot && it.kind === "space") it.mesh.material.opacity = Math.min(1, it.mesh.material.opacity + 0.2);
    if (it.line) it.line.visible = true;
  }
  R.needsRender = true;
}

function describe(it) {
  const u = it.mesh.userData;
  return { tag: u.tag, name: u.name || u.cls.replace(/^Ifc/, ""), storey: u.storey, kind: u.kind, failing: it.failing };
}

function showLabel(it, x, y) {
  const { label, container } = V;
  if (!it) { label.hidden = true; return; }
  const d = describe(it);
  label.replaceChildren();
  const head = document.createElement("div"); head.className = "h";
  if (d.tag) { const t = document.createElement("b"); t.textContent = d.tag; t.className = d.failing ? "bad" : ""; head.appendChild(t); }
  const n = document.createElement("span"); n.textContent = d.name; head.appendChild(n);
  label.appendChild(head);
  const sub = document.createElement("div"); sub.className = "s";
  sub.textContent = [d.kind === "space" ? "Room" : d.kind[0].toUpperCase() + d.kind.slice(1), d.storey, d.failing ? "FAIL" : ""].filter(Boolean).join(" · ");
  if (d.failing) sub.classList.add("bad");
  label.appendChild(sub);
  label.hidden = false;
  const w = container.clientWidth, h = container.clientHeight;
  const lw = label.offsetWidth, lh = label.offsetHeight;
  label.style.left = Math.max(4, Math.min(x + 14, w - lw - 4)) + "px";
  label.style.top = Math.max(4, Math.min(y + 14, h - lh - 4)) + "px";
}

function pick() {
  if (!V || !M || !V.pointer) return null;
  const { raycaster, camera } = R;
  raycaster.setFromCamera(V.pointer, camera);
  const targets = M.items.filter((it) => it.mesh.visible).map((it) => it.mesh);
  const hit = raycaster.intersectObjects(targets, false)[0];
  return hit ? M.items.find((it) => it.mesh === hit.object) || null : null;
}

// --- frame loop ----------------------------------------------------------------
function frame() {
  if (!V) return;
  V.raf = requestAnimationFrame(frame);
  const { controls, renderer, scene, camera } = R;
  if (V.needsPick) {
    V.needsPick = false;
    const it = pick();
    if (it !== V.hover) { V.hover = it; applyStyle(); }
    if (!V.pinned) showLabel(V.hover, V.px, V.py);
    R.canvas.style.cursor = V.hover ? "pointer" : "";
  }
  const moved = controls.update();
  if (moved || R.needsRender) { renderer.render(scene, camera); R.needsRender = false; }
}

function resize() {
  if (!V) return;
  const w = V.container.clientWidth, h = V.container.clientHeight;
  if (!w || !h) return;
  R.renderer.setSize(w, h, false);
  R.camera.aspect = w / h;
  R.camera.updateProjectionMatrix();
  R.needsRender = true;
}

// --- public API ----------------------------------------------------------------
function mount(container, meshJson, opts = {}) {
  if (V) unmount();
  ensureRenderer();
  if (!M || M.json !== meshJson) { disposeModel(); M = buildModel(meshJson); R.scene.add(M.root); }
  container.classList.add("v3-host");
  container.appendChild(R.canvas);
  const label = document.createElement("div"); label.className = "v3-label"; label.hidden = true; container.appendChild(label);
  V = { container, label, opts: { failing: opts.failing || new Set(), showRooms: opts.showRooms !== false },
        hover: null, pinned: null, pointer: null, px: 0, py: 0, needsPick: false, raf: 0, ro: null, listeners: [] };
  resize();
  if (POSE && POSE.json === meshJson) {
    R.camera.position.copy(POSE.position); R.controls.target.copy(POSE.target);
    R.camera.near = Math.max(0.02, POSE.position.distanceTo(POSE.target) / 500); R.camera.far = POSE.position.distanceTo(POSE.target) * 40;
    R.camera.updateProjectionMatrix(); R.controls.update();
    R.needsRender = true;
  } else fitCamera();
  applyStyle();
  V.ro = new ResizeObserver(resize); V.ro.observe(container);
  const on = (ev, fn) => { R.canvas.addEventListener(ev, fn); V.listeners.push([ev, fn]); };
  let down = null;
  on("pointermove", (e) => {
    const r = R.canvas.getBoundingClientRect();
    V.px = e.clientX - r.left; V.py = e.clientY - r.top;
    V.pointer = new THREE.Vector2((V.px / r.width) * 2 - 1, -(V.py / r.height) * 2 + 1);
    V.needsPick = true;
  });
  on("pointerleave", () => { V.pointer = null; if (V.hover) { V.hover = null; applyStyle(); } if (!V.pinned) showLabel(null); R.canvas.style.cursor = ""; });
  on("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  on("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || e.button !== 0) { down = null; return; }
    down = null;
    const it = pick();
    V.pinned = it && V.pinned !== it ? it : null;
    applyStyle();
    showLabel(V.pinned || V.hover, V.px, V.py);
  });
  on("dblclick", () => { fitCamera(); });
  V.raf = requestAnimationFrame(frame);
  return { elements: M.items.length, triangles: M.tris, bounds: M.bounds };
}

function update(opts = {}) {
  if (!V) return;
  if ("failing" in opts) V.opts.failing = opts.failing || new Set();
  if ("showRooms" in opts) V.opts.showRooms = !!opts.showRooms;
  if (V.pinned && V.pinned.kind === "space" && !V.opts.showRooms) { V.pinned = null; showLabel(null); }
  applyStyle();
}

function fit() { if (V && M) fitCamera(); }

function unmount() {
  if (!V) return;
  cancelAnimationFrame(V.raf);
  V.ro && V.ro.disconnect();
  for (const [ev, fn] of V.listeners) R.canvas.removeEventListener(ev, fn);
  if (M) POSE = { json: M.json, position: R.camera.position.clone(), target: R.controls.target.clone() };
  R.canvas.remove();
  V.label.remove();
  V.container.classList.remove("v3-host");
  R.canvas.style.cursor = "";
  V = null;
}

function dispose() {
  unmount();
  disposeModel();
  POSE = null;
  if (R) { R.controls.dispose(); R.renderer.dispose(); R = null; }
}

function stats() { return M ? { elements: M.items.length, triangles: M.tris, bounds: M.bounds } : null; }

// --- the page ----------------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 2) => (v === null || v === undefined) ? "—" : (+v).toFixed(d).replace(/\.?0+$/, "");
const S = { jobId: window.STUDIO.jobId, job: null, pkg: null, mesh: null, meshRun: null, sheet: 0, timer: null, baseCode: "", building: false };
const el = { code: $("#code"), build: $("#build"), status: $("#status"), verdict: $("#verdict"), problems: $("#problems"), v3: $("#v3"), v2: $("#v2"),
             sheetno: $("#sheetno"), storey: $("#storey"), nav: $("#nav"), prev: $("#prev"), next: $("#next"), pdf: $("#pdf"), project: $("#project"), meta: $("#code-meta"),
             chat: $("#chat"), chatForm: $("#chat-form"), chatText: $("#chat-text"), chatSend: $("#chat-send") };
const files = (rel) => `/jobs/${S.jobId}/files/${rel}`;
const projectName = (code) => (code.match(/House\(\s*["']([^"']+)["']/) || [])[1] || "House";

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; } throw new Error(d || r.statusText); }
  return r.json();
}
const status = (html, busy) => { el.status.innerHTML = (busy ? `<span class="glyph running"></span>` : "") + html; };
const problems = (html) => { el.problems.innerHTML = html; el.problems.classList.toggle("show", !!html); };

el.build.addEventListener("click", build);
document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); build(); } });
el.code.addEventListener("input", () => { el.project.textContent = projectName(el.code.value); });
el.prev.addEventListener("click", () => { S.sheet--; renderSheet(); });
el.next.addEventListener("click", () => { S.sheet++; renderSheet(); });
el.chatForm.addEventListener("submit", (e) => { e.preventDefault(); chat(); });

// --- chat: words in, new house.py out -------------------------------------------------------
function renderChat(items, pending) {
  const all = [...items]; if (pending) all.push({ role: "assistant", text: pending, pending: true });
  el.chat.hidden = all.length === 0;
  el.chat.innerHTML = all.map((m) => `<div class="m ${m.role}${m.changed ? " changed" : ""}${m.error ? " error" : ""}${m.pending ? " pending" : ""}">${esc(m.text)}</div>`).join("");
  el.chat.scrollTop = el.chat.scrollHeight;
}
function chatEnabled(on) { el.chatText.disabled = !on; el.chatSend.disabled = !on; }
async function chat() {
  const text = el.chatText.value.trim();
  if (!text || !S.jobId || S.building) return;
  const items = S.job.chat || [];
  renderChat([...items, { role: "user", text }], "thinking…");
  el.chatText.value = ""; chatEnabled(false);
  try {
    const r = await api(`/api/jobs/${S.jobId}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    S.job.chat = r.chat; renderChat(r.chat);
    if (r.changed) { S.building = true; el.build.disabled = true; status("rebuilding…", true); poll(); }
  } catch (e) {
    renderChat([...items, { role: "user", text }, { role: "assistant", text: e.message, error: true }]);
  }
  chatEnabled(true); el.chatText.focus();
}

// --- build: first time creates the job, afterwards rebuilds it with the edited code ----------
async function build() {
  if (S.building) return;
  const code = el.code.value;
  if (!code.trim()) { problems(`<pre>house.py is empty.</pre>`); return; }
  el.build.disabled = true; S.building = true; problems("");
  try {
    if (!S.jobId) {
      const fd = new FormData();
      fd.append("code", code); fd.append("project", projectName(code));
      const { job_id } = await api("/api/jobs", { method: "POST", body: fd });
      S.jobId = job_id; history.pushState({}, "", `/studio/${job_id}`);
    } else {
      if (code.trim() === S.baseCode.trim()) { status("nothing changed"); el.build.disabled = false; S.building = false; return; }
      await api(`/api/jobs/${S.jobId}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "", code }) });
    }
    status("starting…", true);
    poll();
  } catch (e) { problems(`<pre>${esc(e.message)}</pre>`); status("not built"); el.build.disabled = false; S.building = false; }
}

async function poll() {
  clearTimeout(S.timer);
  try { S.job = await api(`/api/jobs/${S.jobId}`); } catch (e) { status(esc(e.message)); S.building = false; el.build.disabled = false; return; }
  const j = S.job;
  if (j.status === "running" || j.status === "queued") {
    const cur = j.steps.find((s) => s.status === "running") || j.steps.find((s) => s.status === "pending");
    status(`${esc(cur ? cur.name : "working")} · ${j.elapsed.toFixed(1)} s`, true);
    S.timer = setTimeout(poll, 700);
    return;
  }
  S.building = false; el.build.disabled = false;
  if (j.status === "failed") { status(`build failed · run ${j.runs.length}`); problems(`<pre>${esc(j.error || "unknown error")}</pre>`); return; }
  await showResult();
}

async function showResult() {
  const j = S.job;
  S.baseCode = j.code || "";
  if (document.activeElement !== el.code) el.code.value = S.baseCode;
  el.project.textContent = j.project;
  el.meta.textContent = `run ${j.runs.length}`;
  status(`built in ${j.elapsed.toFixed(1)} s`);
  renderChat(j.chat || []); chatEnabled(true);
  S.pkg = await api(`/api/jobs/${S.jobId}/package`);
  const run = j.runs.length;
  if (S.meshRun !== run) { S.mesh = await api(`/jobs/${S.jobId}/mesh.json?r=${run}`); S.meshRun = run; }
  if (!S.pkg.summary.sheets[S.sheet]) S.sheet = 0;
  renderVerdict(); renderSheet(); render3d();
}

// --- views ----------------------------------------------------------------------------------
function stamp(c, cls = "") {
  const detail = c.status === "PASS" ? `${c.passed}/${c.checks} checks` :
    [c.errors ? `${c.errors} error${c.errors === 1 ? "" : "s"}` : "", c.warnings ? `${c.warnings} warning${c.warnings === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ");
  return `<span class="stamp ${c.status} ${cls}">${c.status}<small>${esc(detail)}</small></span>`;
}
function renderVerdict() {
  el.verdict.innerHTML = stamp(S.pkg.summary.compliance, "sm");
  const fails = S.pkg.results.filter((r) => !r.passed);
  problems(fails.map((r) => `<div class="p"><span class="tag bad">${esc(r.element_tag)}</span><span>${esc(r.message)}</span><span class="vl">${r.value != null ? num(r.value, 3) : ""}${r.limit != null ? ` / ${num(r.limit, 3)}` : ""}</span></div>`).join(""));
}
function renderSheet() {
  const sheets = S.pkg.summary.sheets, sh = sheets[S.sheet];
  el.sheetno.textContent = sh.sheet; el.storey.textContent = sh.storey;
  el.nav.hidden = sheets.length < 2; el.prev.disabled = S.sheet === 0; el.next.disabled = S.sheet >= sheets.length - 1;
  el.pdf.hidden = false; el.pdf.href = files("sheets/" + sh.pdf);
  el.v2.innerHTML = `<a href="${files("sheets/" + sh.pdf)}" target="_blank" rel="noopener"><img src="${files("sheets/" + sh.png)}?r=${S.job.runs.length}" alt="${esc(sh.sheet)} ${esc(sh.storey)}"></a>${stamp(S.pkg.summary.compliance)}`;
}
function render3d() {
  el.v3.querySelectorAll(".v3-wait, .stamp").forEach((x) => x.remove());
  mount(el.v3, S.mesh, { failing: new Set(S.pkg.failing_tags), showRooms: true });
  el.v3.insertAdjacentHTML("beforeend", stamp(S.pkg.summary.compliance));
}

// --- boot -----------------------------------------------------------------------------------
(async () => {
  if (S.jobId) {
    try {
      S.job = await api(`/api/jobs/${S.jobId}`);
      if (S.job.source !== "code") { el.code.value = `# This job started from an IFC file (${S.job.model_name}); there is no source to edit.\n# Start a new house from /studio.`; el.code.readOnly = true; }
      S.baseCode = S.job.code || ""; if (S.job.source === "code") el.code.value = S.baseCode;
      el.project.textContent = S.job.project;
      if (S.job.status === "running" || S.job.status === "queued") { S.building = true; el.build.disabled = true; poll(); }
      else if (S.job.status === "done") await showResult();
      else { status("build failed"); problems(`<pre>${esc(S.job.error || "")}</pre>`); }
    } catch (e) { status(esc(e.message)); }
  } else {
    el.code.value = await fetch("/api/design/example").then((r) => r.text());
    el.project.textContent = projectName(el.code.value);
    status("not built yet");
  }
})();
