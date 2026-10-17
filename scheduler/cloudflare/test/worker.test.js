import assert from "node:assert/strict";
import test from "node:test";

import { dispatchAttempt, dueEvents, run } from "../src/worker.js";

const planned = Date.parse("2026-07-25T00:00:00Z");
const task = {
  kickoff: "2026-07-25T08:00:00Z",
  checkpoints: {
    "T-8H": {
      planned_at: "2026-07-25T00:00:00Z",
      status: "pending",
    },
  },
};

test("dispatches once in the planned minute", () => {
  assert.equal(dispatchAttempt(0), "primary");
  assert.equal(dispatchAttempt(0.9), "primary");
  assert.equal(dispatchAttempt(1), null);
  const events = dueEvents({ match: task }, planned, true);
  assert.equal(events.length, 1);
  assert.equal(events[0].attempt, "primary");
});

test("allows only one bounded retry window ten minutes later", () => {
  assert.equal(dispatchAttempt(9.9), null);
  assert.equal(dispatchAttempt(10), "bounded_retry");
  assert.equal(dispatchAttempt(10.9), "bounded_retry");
  assert.equal(dispatchAttempt(11), null);
});

test("health still reports overdue events outside dispatch windows", () => {
  const twelveMinutesLate = planned + 12 * 60_000;
  assert.equal(dueEvents({ match: task }, twelveMinutesLate).length, 1);
  assert.equal(dueEvents({ match: task }, twelveMinutesLate, true).length, 0);
});

test("terminal checkpoints are never dispatched", () => {
  for (const status of [
    "report_updated",
    "report_failed",
    "source_unavailable",
    "captured",
    "historical_recovery",
    "late_live",
    "permanently_missing",
  ]) {
    const terminalTask = {
      ...task,
      checkpoints: {
        "T-8H": {
          ...task.checkpoints["T-8H"],
          status,
        },
      },
    };
    assert.equal(dueEvents({ match: terminalTask }, planned, true).length, 0);
  }
});

const env = { GITHUB_OWNER: "gemini077", GITHUB_REPO: "football-betting-oneshot", GITHUB_TOKEN: "dummy-test-token" };

test("seven simultaneous fixtures produce one global checkpoint sweep", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("raw.githubusercontent")) {
      return { ok: true, json: async () => ({ tasks: Object.fromEntries(Array.from({ length: 7 }, (_, i) => ["match-" + i, task])) }) };
    }
    if (String(url).includes("/actions/workflows/")) {
      return { ok: true, json: async () => ({ workflow_runs: [{ status: "in_progress" }, { status: "completed" }] }) };
    }
    if (String(url).endsWith("/dispatches")) return { ok: true, status: 204 };
    throw new Error("unexpected request: " + url);
  };
  try {
    const result = await run(env, true, planned);
    assert.equal(result.dispatched, 1);
    assert.equal(result.batched_checkpoints, 7);
    const sent = calls.filter(call => call.options.method === "POST");
    assert.equal(sent.length, 1);
    const payload = JSON.parse(sent[0].options.body).client_payload;
    assert.equal(payload.scan_scope, "all_due");
    assert.equal(payload.batch_count, 7);
    assert.equal(payload.batch_checkpoints.length, 7);
    assert.equal("match_id" in payload, false);
    assert.equal("checkpoint" in payload, false);
  } finally { globalThis.fetch = original; }
});

test("queued market workflow suppresses duplicate dispatcher enqueue", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    if (String(url).includes("raw.githubusercontent")) return { ok: true, json: async () => ({ tasks: { match: task } }) };
    return { ok: true, json: async () => ({ workflow_runs: [{ status: "pending" }] }) };
  };
  try {
    const result = await run(env, true, planned);
    assert.equal(result.status, "queued_runner_exists");
    assert.equal(result.dispatched, 0);
    assert.equal(calls.length, 2);
  } finally { globalThis.fetch = original; }
});

test("Actions status 403 degrades queue inspection without disabling capture", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("raw.githubusercontent")) return { ok: true, json: async () => ({ tasks: { match: task } }) };
    if (String(url).endsWith("/dispatches")) return { ok: true, status: 204 };
    return { ok: false, status: 403 };
  };
  try {
    const result = await run(env, true, planned);
    assert.equal(result.status, "queue_state_unverified");
    assert.equal(result.dispatched, 1);
    assert.equal(calls.length, 3);
    assert.equal(calls.filter(call => call.options.method === "POST").length, 1);
  } finally { globalThis.fetch = original; }
});

test("health endpoint does not inspect or mutate GitHub Actions queue", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return { ok: true, json: async () => ({ tasks: { match: task } }) };
  };
  try {
    const result = await run(env, false, planned);
    assert.equal(result.dispatchable, 1);
    assert.equal(result.dispatched, 0);
    assert.equal(calls.length, 1);
  } finally { globalThis.fetch = original; }
});
