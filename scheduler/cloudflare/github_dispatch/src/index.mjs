const API = "https://api.github.com/repos/gemini077/football-betting-oneshot/actions/workflows/deploy-pages.yml";
const ACTIVE = new Set(["queued", "in_progress", "requested", "waiting", "pending"]);
const WINDOW_MS = 25 * 60 * 1000;

export function createWorker({ fetchImpl = fetch, now = Date.now, logger = console } = {}) {
  return {
    async fetch() {
      return new Response("Not Found", { status: 404 });
    },

    async scheduled(_event, env) {
      const log = (status, extra = {}) => logger.log(JSON.stringify({ component: "github_dispatch", status, ...extra }));
      const token = env?.GITHUB_DISPATCH_TOKEN;
      if (!token) {
        log("missing_secret");
        return;
      }

      const headers = {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "fbos-cloudflare-scheduler",
      };
      let response;
      try {
        response = await fetchImpl(`${API}/runs?branch=main&per_page=5`, { headers });
        if (!response.ok) {
          log("runs_http_error", { http_status: response.status });
          return;
        }
        const data = await response.json();
        if (!data || !Array.isArray(data.workflow_runs)) throw new Error("invalid runs payload");
        const runs = data.workflow_runs;
        if (runs.some(run => !run || typeof run.status !== "string" || typeof run.created_at !== "string")) {
          throw new Error("invalid run entry");
        }
        if (runs.some(run => ACTIVE.has(run.status))) {
          log("active_run");
          return;
        }
        const latest = runs[0];
        if (latest) {
          const created = Date.parse(latest.created_at);
          if (!Number.isFinite(created)) throw new Error("invalid created_at");
          if (now() - created < WINDOW_MS) {
            log("recent_run");
            return;
          }
        }
      } catch {
        log("runs_request_or_data_error");
        return;
      }

      try {
        response = await fetchImpl(`${API}/dispatches`, {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ ref: "main" }),
        });
        if (response.status === 204) {
          log("dispatched");
          return;
        }
        log("dispatch_http_error", { http_status: response.status });
      } catch {
        log("dispatch_request_error");
      }
    },
  };
}

export default createWorker();
