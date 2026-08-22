/* Recognition Studio — the building as code on the left, 3D and 2D on the right, one Build button. */
(() => {
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
  const whenViewer = (fn) => { if (window.Viewer3D) fn(); else window.addEventListener("viewer3d-ready", fn, { once: true }); };

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
    whenViewer(() => {
      el.v3.querySelectorAll(".v3-wait, .stamp").forEach((x) => x.remove());
      Viewer3D.mount(el.v3, S.mesh, { failing: new Set(S.pkg.failing_tags), showRooms: true });
      el.v3.insertAdjacentHTML("beforeend", stamp(S.pkg.summary.compliance));
    });
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
})();
