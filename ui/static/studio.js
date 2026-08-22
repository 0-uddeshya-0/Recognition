/* Recognition Studio — source on the left, 3D and 2D on the right, one Build button. */
(() => {
  const CFG = window.STUDIO;
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 2) => (v === null || v === undefined) ? "—" : (+v).toFixed(d).replace(/\.?0+$/, "");
  const S = { jobId: CFG.jobId, job: null, pkg: null, mesh: null, meshRun: null, sheet: 0, file: "code", timer: null,
              baseCode: "", baseRules: CFG.defaultRules, building: false, showRooms: true };
  const el = { code: $("#code"), rules: $("#rules"), build: $("#build"), status: $("#status"), verdict: $("#verdict"), problems: $("#problems"),
               v3: $("#v3"), v2: $("#v2"), info: $("#v3-info"), sheetno: $("#sheetno"), storey: $("#storey"), prev: $("#prev"), next: $("#next"),
               pdf: $("#pdf"), project: $("#project"), full: $("#full"), meta: $("#code-meta"), rooms: $("#rooms") };
  const files = (rel) => `/jobs/${S.jobId}/files/${rel}`;

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (_) { d = r.statusText; } throw new Error(d || r.statusText); }
    return r.json();
  }
  function status(html, busy) { el.status.innerHTML = (busy ? `<span class="glyph running"></span>` : "") + html; }
  function whenViewer(fn) { if (window.Viewer3D) fn(); else window.addEventListener("viewer3d-ready", fn, { once: true }); }

  // --- source tabs ----------------------------------------------------------------
  document.querySelector(".ftabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S.file = b.dataset.f;
    document.querySelectorAll(".ftabs button").forEach((x) => x.classList.toggle("on", x === b));
    el.code.hidden = S.file !== "code"; el.rules.hidden = S.file !== "rules";
    (S.file === "code" ? el.code : el.rules).focus();
  });
  function markEdited() {
    if (!S.jobId) return;   // nothing built yet — nothing to be "edited" against
    document.querySelector('.ftabs [data-f="code"]').classList.toggle("edited", el.code.value.trim() !== (S.baseCode || "").trim());
    document.querySelector('.ftabs [data-f="rules"]').classList.toggle("edited", el.rules.value.trim() !== (S.baseRules || "").trim());
  }
  el.code.addEventListener("input", markEdited); el.rules.addEventListener("input", markEdited);
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); build(); } });
  el.build.addEventListener("click", build);
  el.rooms.addEventListener("change", () => { S.showRooms = el.rooms.checked; if (window.Viewer3D) Viewer3D.update({ showRooms: S.showRooms }); });
  el.prev.addEventListener("click", () => { S.sheet--; renderSheet(); });
  el.next.addEventListener("click", () => { S.sheet++; renderSheet(); });

  // --- build ------------------------------------------------------------------------
  async function build() {
    if (S.building) return;
    const code = el.code.value, rules = el.rules.value;
    if (!code.trim()) { problems(`<pre>house.py is empty.</pre>`); return; }
    const rulesChanged = rules.trim() !== (S.baseRules || "").trim();
    const codeChanged = code.trim() !== (S.baseCode || "").trim();
    el.build.disabled = true; S.building = true; el.problems.classList.remove("show");
    try {
      if (!S.jobId) {
        const fd = new FormData();
        fd.append("code", code); fd.append("project", el.project.value.trim() || "House");
        if (rules.trim() !== CFG.defaultRules.trim()) fd.append("rules_yaml", rules);
        const { job_id } = await api("/api/jobs", { method: "POST", body: fd });
        S.jobId = job_id; history.pushState({}, "", `/studio/${job_id}`);
        el.full.hidden = false; el.full.href = `/jobs/${job_id}`;
      } else {
        if (!codeChanged && !rulesChanged) { status("nothing changed"); el.build.disabled = false; S.building = false; return; }
        await api(`/api/jobs/${S.jobId}/message`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                      body: JSON.stringify({ text: "", code: codeChanged ? code : null, rules_yaml: rulesChanged ? rules : null }) });
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
    if (j.status === "failed") {
      status(`build failed · run ${j.runs.length}`);
      problems(`<pre>${esc(j.error || "unknown error")}</pre>`);
      return;
    }
    await showResult();
  }

  async function showResult() {
    const j = S.job;
    S.baseCode = j.code || ""; S.baseRules = j.rules_yaml || CFG.defaultRules;
    if (document.activeElement !== el.code) el.code.value = S.baseCode;
    if (document.activeElement !== el.rules) el.rules.value = S.baseRules;
    markEdited();
    el.project.value = j.project; el.full.hidden = false; el.full.href = `/jobs/${S.jobId}`;
    el.meta.textContent = `run ${j.runs.length} · rev ${j.summary.revision || "—"}`;
    status(`built in ${j.elapsed.toFixed(1)} s · run ${j.runs.length}`);
    S.pkg = await api(`/api/jobs/${S.jobId}/package`);
    const run = j.runs.length;
    if (S.meshRun !== run) { S.mesh = await api(`/jobs/${S.jobId}/mesh.json?r=${run}`); S.meshRun = run; }
    if (!S.pkg.summary.sheets[S.sheet]) S.sheet = 0;
    renderVerdict(); renderSheet(); render3d();
  }

  // --- views --------------------------------------------------------------------------
  function stamp(c, cls = "") {
    const detail = c.status === "PASS" ? `${c.passed}/${c.checks} checks` :
      [c.errors ? `${c.errors} error${c.errors === 1 ? "" : "s"}` : "", c.warnings ? `${c.warnings} warning${c.warnings === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ");
    return `<span class="stamp ${c.status} ${cls}">${c.status}<small>${esc(detail)}</small></span>`;
  }
  function renderVerdict() {
    const c = S.pkg.summary.compliance;
    el.verdict.innerHTML = stamp(c, "sm");
    const fails = S.pkg.results.filter((r) => !r.passed);
    if (!fails.length) { el.problems.classList.remove("show"); el.problems.innerHTML = ""; return; }
    problems(fails.map((r) => `<div class="p"><span class="tag bad">${esc(r.element_tag)}</span><span>${esc(r.message)}</span><span class="vl">${r.value != null ? num(r.value, 3) : ""}${r.limit != null ? ` / ${num(r.limit, 3)}` : ""}</span></div>`).join(""));
  }
  function problems(html) { el.problems.innerHTML = html; el.problems.classList.add("show"); }
  function renderSheet() {
    const sheets = S.pkg.summary.sheets, sh = sheets[S.sheet];
    el.sheetno.textContent = sh.sheet; el.storey.textContent = sh.storey;
    el.prev.disabled = S.sheet === 0; el.next.disabled = S.sheet >= sheets.length - 1;
    el.pdf.hidden = false; el.pdf.href = files("sheets/" + sh.pdf);
    el.v2.innerHTML = `<a href="${files("sheets/" + sh.pdf)}" target="_blank" rel="noopener"><img src="${files("sheets/" + sh.png)}?r=${S.job.runs.length}" alt="${esc(sh.sheet)} ${esc(sh.storey)}"></a>${stamp(S.pkg.summary.compliance, "")}`;
  }
  function render3d() {
    whenViewer(() => {
      const wait = $("#v3-wait"); if (wait) wait.remove();
      el.v3.querySelectorAll(".stamp").forEach((s) => s.remove());
      const info = Viewer3D.mount(el.v3, S.mesh, { failing: new Set(S.pkg.failing_tags), showRooms: S.showRooms });
      el.v3.insertAdjacentHTML("beforeend", stamp(S.pkg.summary.compliance, ""));
      el.info.textContent = `${info.elements} elements`;
    });
  }

  // --- boot -----------------------------------------------------------------------------
  (async () => {
    if (S.jobId) {
      el.full.hidden = false; el.full.href = `/jobs/${S.jobId}`;
      try {
        S.job = await api(`/api/jobs/${S.jobId}`);
        if (S.job.source !== "code") { el.code.value = `# This job started from an IFC file (${S.job.model_name}); there is no source to edit.\n# Start a new house from /studio.`; el.code.readOnly = true; }
        el.rules.value = S.job.rules_yaml || CFG.defaultRules; S.baseRules = el.rules.value;
        S.baseCode = S.job.code || ""; if (S.job.source === "code") el.code.value = S.baseCode;
        el.project.value = S.job.project;
        if (S.job.status === "running" || S.job.status === "queued") { S.building = true; el.build.disabled = true; poll(); }
        else if (S.job.status === "done") await showResult();
        else { status("build failed"); problems(`<pre>${esc(S.job.error || "")}</pre>`); }
      } catch (e) { status(esc(e.message)); }
    } else {
      const t = await fetch("/api/design/example").then((r) => r.text());
      if (!el.code.value) el.code.value = t;
      S.baseCode = ""; markEdited();
      status("not built yet");
    }
  })();
})();
