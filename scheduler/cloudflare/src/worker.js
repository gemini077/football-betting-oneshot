const TERMINAL = new Set(["captured", "historical_recovery", "late_live", "permanently_missing"]);
const DISPATCH_WINDOWS = [
  { attempt: "primary", startMinutes: 0, endMinutes: 1 },
  { attempt: "bounded_retry", startMinutes: 10, endMinutes: 11 },
];

function dispatchAttempt(latenessMinutes) {
  const window = DISPATCH_WINDOWS.find(
    ({ startMinutes, endMinutes }) =>
      latenessMinutes >= startMinutes && latenessMinutes < endMinutes,
  );
  return window?.attempt || null;
}

function dueEvents(tasks, now, dispatchableOnly = false) {
  const rows = [];
  for (const [matchId, task] of Object.entries(tasks || {})) {
    const kickoff = Date.parse(task.kickoff);
    if (!Number.isFinite(kickoff) || now > kickoff + 6 * 3600_000) continue;
    for (const [checkpoint, state] of Object.entries(task.checkpoints || {})) {
      if (TERMINAL.has(state.status)) continue;
      const planned = Date.parse(state.planned_at);
      if (!Number.isFinite(planned) || planned > now) continue;
      const latenessMinutes = Math.round((now - planned) / 6000) / 10;
      const attempt = dispatchAttempt(latenessMinutes);
      if (dispatchableOnly && !attempt) continue;
      rows.push({ matchId, checkpoint, planned, latenessMinutes, attempt });
    }
  }
  return rows.sort((a, b) => a.planned - b.planned).slice(0, 12);
}

async function dispatch(env, event) {
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "football-betting-oneshot-checkpoint-scheduler",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({
      event_type: "prematch_checkpoint_due",
      client_payload: {
        match_id: event.matchId,
        checkpoint: event.checkpoint,
        planned_at: new Date(event.planned).toISOString(),
        idempotency_key: `${event.matchId}:${event.checkpoint}`,
        dispatch_attempt: event.attempt,
        scheduler: "cloudflare-minute-cron",
      },
    }),
  });
  if (!response.ok) throw new Error(`GitHub dispatch ${response.status}: ${await response.text()}`);
}

async function run(env, shouldDispatch = true, now = Date.now()) {
  const branch = env.GITHUB_BRANCH || "main";
  const registryUrl = `https://raw.githubusercontent.com/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/${branch}/data/market_history/prematch_tasks.json?t=${Date.now()}`;
  const response = await fetch(registryUrl, { headers: { "Cache-Control": "no-cache" } });
  if (response.status === 404) return { status: "registry_not_published", due: 0, dispatched: 0 };
  if (!response.ok) throw new Error(`Registry fetch ${response.status}`);
  const registry = await response.json();
  const due = dueEvents(registry.tasks, now);
  const events = dueEvents(registry.tasks, now, true);
  if (!shouldDispatch) {
    return {
      status: "ok",
      due: due.length,
      dispatchable: events.length,
      dispatched: 0,
      results: due,
    };
  }
  const results = [];
  for (const event of events) {
    try {
      await dispatch(env, event);
      results.push({ ...event, status: "dispatched" });
    } catch (error) {
      results.push({ ...event, status: "error", error: String(error) });
    }
  }
  return {
    status: "ok",
    due: due.length,
    dispatchable: events.length,
    dispatched: results.filter(row => row.status === "dispatched").length,
    results,
  };
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(run(env, true, controller.scheduledTime));
  },
  async fetch(request, env) {
    if (new URL(request.url).pathname !== "/health") return new Response("Not found", { status: 404 });
    try {
      return Response.json(await run(env, false));
    } catch (error) {
      return Response.json({ status: "error", error: String(error) }, { status: 500 });
    }
  },
};

export { dispatchAttempt, dueEvents, run };
