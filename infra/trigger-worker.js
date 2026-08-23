/* The Studio's relay: it holds the GitHub token server-side so the public
 * page needs no credential at all.
 *
 * Two jobs, both narrow:
 *   POST /            {workflow, inputs}  → start one allow-listed workflow
 *   GET  /?runs=<wf>  |  ?run=<id>  |  ?jobs=<id>  |  ?file=<relay path>
 *                                         → the few reads the page needs
 *
 * Reads matter as much as the trigger: an anonymous browser gets 60 GitHub
 * API calls an hour, which a single run's progress polling would exhaust —
 * so the page would sit on "Sending the brief" looking stalled. Proxying
 * those reads through the relay's token keeps progress live and the bundle
 * instant (no CDN cache lag).
 *
 * This is deliberately NOT a general proxy: every parameter is validated
 * against a strict pattern, and only this one repository is reachable.
 *
 * Deploy:  export CLOUDFLARE_API_TOKEN=…  &&  ./deploy.sh <github_pat_…>
 */

const ALLOWED_WORKFLOWS = ["draft.yml", "interview.yml", "autopilot.yml"];
const ALLOWED_ORIGINS = ["https://0-uddeshya-0.github.io", "http://localhost:8123"];
const WORKFLOW_RE = /^[a-z][a-z-]{1,30}\.yml$/;
const ID_RE = /^\d{1,20}$/;
const FILE_RE = /^(drafts|interviews)\/[A-Za-z0-9-]{1,64}\/(round|reply)-\d{1,3}\.json$/;

const WINDOW_MS = 60_000;
const MAX_WRITES = 10;      // dispatches per IP per minute
const MAX_READS = 120;      // reads per IP per minute (polling is chatty)
const hits = new Map();

function cors(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Cache-Control": "no-store",
  };
}

function throttled(ip, kind, cap) {
  const now = Date.now();
  const key = `${kind}:${ip}`;
  const bucket = (hits.get(key) || []).filter((t) => now - t < WINDOW_MS);
  if (bucket.length >= cap) return true;
  bucket.push(now);
  hits.set(key, bucket);
  return false;
}

function gh(env, path, raw = false) {
  return fetch(`https://api.github.com/repos/${env.REPO}/${path}`, {
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: raw ? "application/vnd.github.raw+json" : "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "recognition-trigger-relay",
    },
  });
}

const json = (body, headers, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...headers, "Content-Type": "application/json" } });

async function handleRead(url, env, headers) {
  const runs = url.searchParams.get("runs");
  const run = url.searchParams.get("run");
  const jobs = url.searchParams.get("jobs");
  const file = url.searchParams.get("file");

  if (runs && WORKFLOW_RE.test(runs)) {
    const r = await gh(env, "actions/runs?per_page=12");
    if (!r.ok) return json({ error: r.status }, headers, 502);
    const d = await r.json();
    return json(
      (d.workflow_runs || [])
        .filter((x) => (x.path || "").endsWith(`/${runs}`))
        .map((x) => ({ id: x.id, created_at: x.created_at, html_url: x.html_url, status: x.status, conclusion: x.conclusion })),
      headers,
    );
  }

  if (run && ID_RE.test(run)) {
    const r = await gh(env, `actions/runs/${run}`);
    if (!r.ok) return json({ error: r.status }, headers, 502);
    const d = await r.json();
    return json({ id: d.id, status: d.status, conclusion: d.conclusion, html_url: d.html_url }, headers);
  }

  if (jobs && ID_RE.test(jobs)) {
    const r = await gh(env, `actions/runs/${jobs}/jobs`);
    if (!r.ok) return json({ error: r.status }, headers, 502);
    const d = await r.json();
    const steps = (d.jobs?.[0]?.steps || []).map((s) => ({ name: s.name, status: s.status, conclusion: s.conclusion }));
    return json({ steps }, headers);
  }

  if (file && FILE_RE.test(file)) {
    const r = await gh(env, `contents/${file}?ref=studio-interviews`, true);
    if (r.status === 404) return json({ pending: true }, headers, 404);
    if (!r.ok) return json({ error: r.status }, headers, 502);
    // pass the artifact through untouched
    return new Response(await r.text(), { headers: { ...headers, "Content-Type": "application/json" } });
  }

  return json({ error: "unknown read" }, headers, 400);
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get("Origin") || "";
    const headers = cors(origin);
    if (req.method === "OPTIONS") return new Response(null, { headers });

    const ip = req.headers.get("CF-Connecting-IP") || "unknown";
    const url = new URL(req.url);

    if (req.method === "GET") {
      if (throttled(ip, "r", MAX_READS)) return new Response("slow down", { status: 429, headers });
      return handleRead(url, env, headers);
    }
    if (req.method !== "POST") return new Response("POST or GET only", { status: 405, headers });
    if (throttled(ip, "w", MAX_WRITES)) return new Response("slow down", { status: 429, headers });

    const { workflow, inputs } = await req.json().catch(() => ({}));
    if (!ALLOWED_WORKFLOWS.includes(workflow)) {
      return new Response("unknown workflow", { status: 400, headers });
    }
    const r = await fetch(
      `https://api.github.com/repos/${env.REPO}/actions/workflows/${workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "recognition-trigger-relay",
        },
        body: JSON.stringify({ ref: "main", inputs: inputs || {} }),
      },
    );
    // GitHub answers a successful dispatch with 204 No Content, and a 204
    // Response MUST carry a null body — echoing that status with a body
    // throws inside the worker (the page saw a 1101). Answer a plain 200.
    if (r.ok) return new Response("ok", { status: 200, headers });
    return new Response(await r.text(), { status: r.status, headers });
  },
};
