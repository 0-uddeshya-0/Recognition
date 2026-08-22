/* Recognition Studio.
 *
 * A static page. It reads artifacts a run already committed under data/ and
 * renders them; it never runs the pipeline and never holds a secret. The 3D
 * view draws mesh.json (triangulated when the artifact was produced, not here),
 * which is what lets a real model load with no backend at all.
 *
 * Three parts: the interview, the viewer, and the result panes.
 */
import * as THREE from "three";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const State = { brief: null, run: null, project: null, candidate: null };

/* ══════════════════════════════════════════════════════════════════════
   1 · The interview
   Five questions. Only the ones a tier:law rule genuinely needs are
   blocking; everything else gets a default that is shown as an assumption
   rather than hidden. The `why` on each question names the rule that asks
   for it, so nobody is answering a form they don't understand.
   ══════════════════════════════════════════════════════════════════════ */

const ROOMS = [
  { key: "living",   label: "Living room", def: 1 },
  { key: "kitchen",  label: "Kitchen",     def: 1 },
  { key: "bedroom",  label: "Bedrooms",    def: 2 },
  { key: "bathroom", label: "Bathroom",    def: 1 },
  { key: "office",   label: "Study",       def: 0 },
  { key: "utility",  label: "Utility",     def: 0 },
];

const QUESTIONS = [
  {
    id: "building_class", type: "single", q: "What are you building?",
    why: "Selects which rules apply.",
    options: [
      ["detached_house", "A detached house"],
      ["semi_detached", "A semi-detached house"],
      ["apartment_block", "An apartment building"],
    ],
    def: "detached_house",
  },
  {
    id: "dwelling_count", type: "number", q: "How many homes are in it?",
    why: "Required by <b>BayBO Art. 48 (1)</b> — above two, one storey must be barrier-free.",
    def: 1, min: 1, max: 24, unit: "homes", blocking: true,
  },
  {
    id: "rooms", type: "rooms", q: "Which rooms, and how many?",
    why: "The programme. A dwelling needs a kitchen and a bathroom — <b>BayBO Art. 46</b>.",
  },
  {
    id: "plot", type: "plot", q: "How big is the plot?",
    why: "Bounds the envelope. Leave it if you're not sure.",
    def: [18, 24],
  },
  {
    id: "notes", type: "text", q: "Anything else we should know?",
    why: "Free text — orientation, a view to keep, how you live in it.",
    placeholder: "e.g. living room facing the garden, south",
  },
];

function renderInterview() {
  const list = $("qlist");
  list.innerHTML = "";
  for (const q of QUESTIONS) {
    const li = el("li", "q");
    const head = el("div", "qh");
    head.append(el("span", "num"), Object.assign(el("label", "qt", q.q), { htmlFor: `f-${q.id}` }));
    li.append(head);
    const why = el("p", "why");
    why.innerHTML = q.why;
    li.append(why);
    li.append(fieldFor(q));
    list.append(li);
  }
  refreshAssumptions();
}

function fieldFor(q) {
  if (q.type === "single") {
    const wrap = el("div", "opts");
    q.options.forEach(([val, label]) => {
      const b = el("button", "opt", label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(val === q.def));
      b.dataset.value = val;
      b.onclick = () => {
        [...wrap.children].forEach((c) => c.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        q.value = val;
        refreshAssumptions();
      };
      wrap.append(b);
    });
    q.value = q.def;
    return wrap;
  }

  if (q.type === "number") {
    const wrap = el("div", "pair");
    const i = el("input");
    Object.assign(i, { type: "number", id: `f-${q.id}`, value: q.def, min: q.min, max: q.max });
    i.oninput = () => { q.value = Number(i.value) || q.def; refreshAssumptions(); };
    q.value = q.def;
    wrap.append(i, el("span", null, q.unit || ""));
    return wrap;
  }

  if (q.type === "rooms") {
    const grid = el("div", "rooms-grid");
    q.value = {};
    ROOMS.forEach((r) => {
      q.value[r.key] = r.def;
      const row = el("div", "room-row" + (r.def ? " on" : ""));
      const n = el("span", "n", String(r.def));
      const dec = el("button", null, "−"); dec.type = "button";
      const inc = el("button", null, "+"); inc.type = "button";
      const set = (v) => {
        q.value[r.key] = Math.max(0, Math.min(6, v));
        n.textContent = String(q.value[r.key]);
        row.classList.toggle("on", q.value[r.key] > 0);
        refreshAssumptions();
      };
      dec.onclick = () => set(q.value[r.key] - 1);
      inc.onclick = () => set(q.value[r.key] + 1);
      const step = el("div", "stepper");
      step.append(dec, n, inc);
      row.append(el("span", "nm", r.label), step);
      grid.append(row);
    });
    return grid;
  }

  if (q.type === "plot") {
    const wrap = el("div", "pair");
    const w = el("input"), d = el("input");
    Object.assign(w, { type: "number", id: `f-${q.id}`, value: q.def[0], min: 5, max: 100 });
    Object.assign(d, { type: "number", value: q.def[1], min: 5, max: 100 });
    q.value = [...q.def];
    const upd = () => { q.value = [Number(w.value) || q.def[0], Number(d.value) || q.def[1]]; };
    w.oninput = upd; d.oninput = upd;
    wrap.append(w, el("span", null, "×"), d, el("span", null, "m"));
    return wrap;
  }

  const i = el("input");
  Object.assign(i, { type: "text", id: `f-${q.id}`, placeholder: q.placeholder || "" });
  i.oninput = () => { q.value = i.value; };
  q.value = "";
  return i;
}

/* Every value we infer is shown, with the reason. The silent default is the
   failure mode this whole product is designed against. */
function refreshAssumptions() {
  const dwellings = QUESTIONS.find((q) => q.id === "dwelling_count").value || 1;
  const chips = [
    ["ceiling height", "2.50 m", "BayBO Art. 45 (1) minimum 2.40 m + 100 mm build-up"],
    ["storeys", "1", "v1 designs a single storey"],
    ["glazing", "1/8 of floor area", "BayBO Art. 45 (2)"],
  ];
  if (dwellings > 2) {
    chips.push(["barrier-free", "DIN 18040-2", "BayBO Art. 48 (1): more than 2 homes"]);
  }
  const box = $("assumed-chips");
  box.innerHTML = "";
  chips.forEach(([k, v, basis]) => {
    const c = el("span", "chip");
    c.append(el("span", null, k + " "), el("b", null, v), el("span", "basis", "· " + basis));
    box.append(c);
  });
}

function briefFromInterview() {
  const get = (id) => QUESTIONS.find((q) => q.id === id).value;
  const rooms = Object.entries(get("rooms"))
    .filter(([, n]) => n > 0)
    .map(([category, count]) => ({ category, count }));
  const [w, d] = get("plot");
  return {
    project: "Neubau",
    building_class: get("building_class"),
    dwelling_count: get("dwelling_count"),
    plot_width_m: w, plot_depth_m: d,
    rooms, notes: get("notes"),
    storey_count: 1, storey_height_m: 2.5, bundesland: "BY",
  };
}

/* ══════════════════════════════════════════════════════════════════════
   2 · The 3D viewer
   ══════════════════════════════════════════════════════════════════════ */

const COLOR = {
  bg: 0xffffff, wall: 0x9aa5ae, space: 0xdfe6ec,
  door: 0xd07a2a, window: 0x2a62d8, edge: 0x15191d,
  sky: 0xffffff, ground: 0xc7ced5,
};
const kindOf = (cls) =>
  cls === "IfcSpace" ? "space" : cls === "IfcDoor" ? "door" : cls === "IfcWindow" ? "window" : "wall";

let V = null;

function viewer() {
  if (V) return V;
  const host = $("v3-host");
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.domElement.className = "v3-canvas";
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLOR.bg);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 2000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;

  scene.add(
    new THREE.HemisphereLight(COLOR.sky, COLOR.ground, 1.7),
    new THREE.AmbientLight(0xffffff, 0.35),
  );
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(1, 2, 1.4);
  scene.add(sun);

  V = { renderer, scene, camera, controls, host, root: null,
        raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(), spaces: [] };

  const resize = () => {
    const w = host.clientWidth || 1, h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(host);
  resize();

  host.addEventListener("pointermove", onHover);
  host.addEventListener("pointerleave", () => $("hoverchip").classList.add("hide"));

  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();
  return V;
}

function loadMesh(json) {
  const v = viewer();
  if (v.root) { v.scene.remove(v.root); disposeTree(v.root); }
  const root = new THREE.Group();
  v.spaces = [];

  const [x0, y0, z0, x1, y1, z1] = json.bounds;
  const mid = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);

  for (const e of json.elements || []) {
    const kind = kindOf(e.cls);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(e.verts, 3));
    g.setIndex(e.faces);
    const flat = g.toNonIndexed();     // flat shading keeps corners crisp
    flat.computeVertexNormals();
    g.dispose();
    flat.translate(-mid.x, -mid.y, -mid.z);

    const mat = new THREE.MeshLambertMaterial({
      color: COLOR[kind],
      transparent: kind === "space",
      opacity: kind === "space" ? 0.32 : 1,
      depthWrite: kind !== "space",
      side: kind === "space" ? THREE.DoubleSide : THREE.FrontSide,
    });
    const mesh = new THREE.Mesh(flat, mat);
    mesh.userData = { tag: e.tag, name: e.name, kind, area: e.area };
    if (kind === "space") v.spaces.push(mesh);
    root.add(mesh);
  }

  // IFC is Z-up; three.js is Y-up.
  root.rotation.x = -Math.PI / 2;
  v.scene.add(root);
  v.root = root;

  const span = Math.max(x1 - x0, y1 - y0, z1 - z0) || 10;
  v.camera.position.set(span * 0.95, span * 0.78, span * 1.05);
  v.controls.target.set(0, 0, 0);
  v.controls.update();
  applySpaceVisibility();
  $("v3-wait").classList.add("hide");
}

function disposeTree(obj) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  });
}

function applySpaceVisibility() {
  if (!V) return;
  const on = $("show-spaces").checked;
  V.spaces.forEach((m) => { m.visible = on; });
}

function onHover(ev) {
  const v = viewer();
  if (!v.root) return;
  const r = v.host.getBoundingClientRect();
  v.pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  v.raycaster.setFromCamera(v.pointer, v.camera);
  const hit = v.raycaster.intersectObjects(v.root.children, false)
    .find((h) => h.object.visible && h.object.userData.kind === "space");
  const chip = $("hoverchip");
  if (!hit) { chip.classList.add("hide"); return; }
  const d = hit.object.userData;
  chip.textContent = `${d.tag ? d.tag + "  " : ""}${d.name}${d.area ? "  ·  " + d.area + " m²" : ""}`;
  chip.style.left = `${ev.clientX - r.left}px`;
  chip.style.top = `${ev.clientY - r.top}px`;
  chip.classList.remove("hide");
}

/* ══════════════════════════════════════════════════════════════════════
   3 · Results
   ══════════════════════════════════════════════════════════════════════ */

const base = (p, c) => `data/${p}/${c}`;

async function openProject(key, candidate) {
  const run = await fetch(`data/${key}/run.json`).then((r) => r.json());
  State.run = run; State.project = key;
  State.candidate = candidate || run.winner || (run.candidates[0] || {}).name;
  show("result");
  $("doc-title").textContent = run.project;
  $("restart").classList.remove("hide");
  await showCandidate(State.candidate);
}

async function showCandidate(name) {
  State.candidate = name;
  const p = State.project, dir = base(p, name);

  const verdict = await fetch(`${dir}/verdict.json`).then((r) => r.json()).catch(() => null);
  renderStamp(verdict);
  renderFindings(verdict);
  renderRooms(verdict);
  renderOptions();

  // Two very different failures used to report the same thing. "No model" when
  // the truth was "this browser has no WebGL" sends you looking in the wrong
  // place, so the fetch and the render are caught separately.
  const wait = $("v3-wait");
  wait.textContent = "loading model…";
  wait.classList.remove("hide");
  fetch(`${dir}/mesh.json`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`mesh.json ${r.status}`))))
    .then((json) => {
      try {
        loadMesh(json);
      } catch (e) {
        wait.textContent = "3D needs WebGL, which this browser did not provide";
        wait.classList.remove("hide");
        console.error("3D render failed:", e);
      }
    })
    .catch(() => { wait.textContent = "no 3D model was published for this candidate"; });

  fetch(`${dir}/sheet.svg`).then((r) => (r.ok ? r.text() : Promise.reject()))
    .then((svg) => { $("sheet-host").innerHTML = svg; })
    .catch(() => { $("sheet-host").innerHTML = '<p class="hint">no sheet for this candidate</p>'; });
  $("pdf-link").href = `${dir}/sheet.pdf`;

  fetch(`${dir}/design.py`).then((r) => r.text())
    .then((src) => { $("tab-code").innerHTML = ""; $("tab-code").append(el("pre", "code", src)); })
    .catch(() => {});
}

function renderStamp(v) {
  const host = $("top-stamp");
  host.classList.remove("hide");
  host.innerHTML = "";
  if (!v) return;
  const s = el("span", `stamp ${v.ok ? "pass" : "fail"}`);
  s.append(el("span", null, v.ok ? "PASS" : "FAIL"));
  // Never a bare PASS: what we could not check is part of the answer.
  s.append(el("span", "cov",
    `${v.checked} checked · ${v.not_evaluated} not evaluated · ${v.failed} failed`));
  host.append(s);
}

const TIERS = [
  ["law", "Statute", "may block"],
  ["standard", "Standard", "blocks once triggered"],
  ["guidance", "Guidance", "advisory only"],
  ["house", "Practice", "advisory only"],
];

function renderFindings(v) {
  const box = $("tab-findings");
  box.innerHTML = "";
  if (!v) { box.append(el("p", "hint", "No compliance result.")); return; }

  const notable = (v.findings || []).filter((f) => f.status !== "passed");
  if (!notable.length) {
    box.append(el("p", "hint", "Every rule that could be evaluated passed."));
  }
  for (const [tier, label, note] of TIERS) {
    const items = notable.filter((f) => f.tier === tier);
    if (!items.length) continue;
    const g = el("div", "tier-group");
    const h = el("div", "tier-h");
    h.append(el("span", `tl ${tier}`, label), el("span", "tn", note));
    g.append(h);
    items.forEach((f) => {
      const d = el("div", `finding ${f.status}`);
      const r = el("div", "fr");
      r.append(el("span", "rid", f.rule_id));
      if (f.status === "not_evaluated") r.append(el("span", "hint", "not evaluated"));
      else if (f.blocking) r.append(el("span", "hint", "blocking"));
      d.append(r, el("div", "fm", f.message));
      const cite = el("div", "cite");
      if (f.url) {
        const a = el("a", null, f.citation);
        a.href = f.url; a.target = "_blank"; a.rel = "noopener";
        cite.append(a);
      } else cite.append(el("span", null, f.citation));
      d.append(cite);
      g.append(d);
    });
    box.append(g);
  }
}

function renderRooms(v) {
  const box = $("tab-rooms");
  box.innerHTML = "";
  const m = (v && v.metrics) || {};
  const t = el("table", "rooms");
  t.innerHTML = "<thead><tr><th>Metric</th><th>Value</th></tr></thead>";
  const body = el("tbody");
  const rows = [
    ["Rooms", m.rooms], ["Envelope", m.envelope_m2 && m.envelope_m2 + " m²"],
    ["Room area", m.room_area_m2 && m.room_area_m2 + " m²"],
    ["Circulation", m.circulation_m2 && m.circulation_m2 + " m²"],
    ["Usable ratio", m.usable_ratio && (m.usable_ratio * 100).toFixed(1) + " %"],
    ["Doors + windows", m.openings],
  ];
  rows.forEach(([k, val]) => {
    if (val == null) return;
    const tr = el("tr");
    tr.append(el("td", null, k), el("td", "n", String(val)));
    body.append(tr);
  });
  t.append(body);
  box.append(t);
}

function renderOptions() {
  const box = $("tab-options");
  box.innerHTML = "";
  const run = State.run;
  (run.candidates || []).forEach((c) => {
    const card = el("div", "opt-card" + (c.name === State.candidate ? " on" : ""));
    const h = el("div", "oh");
    h.append(el("span", "on-name", c.label || c.name));
    if (c.name === run.winner) h.append(el("span", "badge", "winner"));
    card.append(h);
    if (c.error) card.append(el("div", "od", c.error));
    const m = el("div", "om");
    m.append(el("span", null, `${c.checked} checked`),
             el("span", null, `${c.failed} failed`),
             el("span", null, `${c.not_evaluated} not evaluated`));
    card.append(m);
    card.onclick = () => showCandidate(c.name);
    box.append(card);
  });
  box.append(el("p", "chosen-note",
    "The winner was chosen by the scorer from the compliance result — not by a person and not by a model. Picking another here is a new view, not an approval."));
}

/* ══════════════════════════════════════════════════════════════════════
   Shell
   ══════════════════════════════════════════════════════════════════════ */

function show(which) {
  ["brief", "working", "result"].forEach((v) =>
    $(`view-${v}`).classList.toggle("hide", v !== which));
}

function toast(msg, ms = 4200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hide");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hide"), ms);
}

const STEPS = [
  ["Brief sealed", "the last moment a person is involved"],
  ["Plan", "rooms, areas and adjacencies — no coordinates"],
  ["Translate", "plan → building code, zero model tokens"],
  ["Build", "IFC4, sheets, 3D mesh"],
  ["Verify", "every rule, with its citation"],
  ["Rank", "the scorer picks a winner"],
];

function renderSteps(activeIdx) {
  const list = $("steps");
  list.innerHTML = "";
  STEPS.forEach(([lb, rt], i) => {
    const li = el("li", "step " + (i < activeIdx ? "done" : i === activeIdx ? "run" : "pend"));
    li.append(el("span", "dot"), el("span", "lb", lb), el("span", "rt", rt));
    list.append(li);
  });
}

/* A static page cannot run the pipeline. Rather than fake it, the Studio says
   plainly what to run, hands over the brief, and shows what already exists. */
async function submitBrief(ev) {
  ev.preventDefault();
  State.brief = briefFromInterview();
  show("working");
  $("working-title").textContent = "Ready to run";
  let i = 0;
  renderSteps(0);
  const tick = setInterval(() => {
    i += 1;
    renderSteps(Math.min(i, 1));
    if (i >= 1) {
      clearInterval(tick);
      $("working-sub").textContent =
        "This page is static, so it cannot run the pipeline itself. Your brief is ready — run it, or open a design that already exists.";
      $("working-note").innerHTML =
        `uv run recognition autopilot &lt;your-brief.json&gt;`;
      const blob = new Blob([JSON.stringify(State.brief, null, 2)], { type: "application/json" });
      const a = el("a", "primary", "Download the brief");
      a.href = URL.createObjectURL(blob);
      a.download = "brief.json";
      a.style.display = "inline-block";
      a.style.textDecoration = "none";
      const back = el("button", "ghost", "Look at a finished design");
      back.type = "button";
      back.onclick = () => { show("brief"); document.getElementById("existing").scrollIntoView({ behavior: "smooth" }); };
      const row = el("div", "brief-actions");
      row.append(a, back);
      $("steps").after(row);
    }
  }, 420);
}

async function boot() {
  renderInterview();
  $("interview").addEventListener("submit", submitBrief);
  $("show-spaces").addEventListener("change", applySpaceVisibility);
  $("restart").addEventListener("click", () => {
    show("brief");
    $("top-stamp").classList.add("hide");
    $("restart").classList.add("hide");
    $("doc-title").textContent = "A house, described";
  });
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      ["findings", "rooms", "options", "code"].forEach((t) =>
        $(`tab-${t}`).classList.toggle("hide", t !== b.dataset.tab));
    };
  });

  let index = { projects: [] };
  try {
    index = await fetch("data/index.json").then((r) => r.json());
  } catch {
    $("existing").classList.add("hide");
  }

  const grid = $("proj-grid");
  grid.innerHTML = "";
  if (!index.projects.length) $("existing").classList.add("hide");
  index.projects.forEach((p) => {
    const b = el("button", "proj");
    b.type = "button";
    b.append(el("div", "pn", p.project));
    b.append(el("div", "pm",
      `${p.candidates} layouts · ${p.checked} checked · ${p.not_evaluated} not evaluated · ${p.failed} failed`));
    b.onclick = () => openProject(p.key);
    grid.append(b);
  });

  // Deep link: ?p=familienhaus&c=open
  const q = new URLSearchParams(location.search);
  if (q.get("p")) openProject(q.get("p"), q.get("c"));
}

boot().catch((e) => toast("Could not start the Studio: " + e.message));
