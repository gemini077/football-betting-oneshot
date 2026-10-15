import test from "node:test";
import assert from "node:assert/strict";
import { createWorker } from "../src/index.mjs";

const now = Date.parse("2026-10-14T12:42:00Z");
const old = "2026-10-14T12:00:00Z";
const recent = "2026-10-14T12:20:00Z";
const env = { GITHUB_DISPATCH_TOKEN: "TEST_TOKEN" };

function setup(getResponse, postResponse = new Response(null, { status: 204 })) {
  const calls = [];
  const logs = [];
  const worker = createWorker({
    now: () => now,
    logger: { log: line => logs.push(JSON.parse(line)) },
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      return calls.length === 1 ? getResponse : postResponse;
    },
  });
  return { worker, calls, logs };
}

const runs = items => new Response(JSON.stringify({ workflow_runs: items }), { status: 200 });
const run = (status, created_at = old) => ({ status, created_at });

test("dispatches stale/no-active workflow and accepts only GitHub 204", async () => {
  const s = setup(runs([run("completed")]));
  await s.worker.scheduled({}, env);
  assert.equal(s.calls.length, 2);
  assert.match(s.calls[0].url, /runs\?branch=main&per_page=5$/);
  assert.equal(s.calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(s.calls[1].options.body), { ref: "main" });
  assert.equal(s.calls[1].options.headers.Authorization, "Bearer TEST_TOKEN");
  assert.equal(s.logs.at(-1).status, "dispatched");
});

test("does not dispatch when an active run exists", async () => {
  const s = setup(runs([run("completed", old), run("in_progress", old)]));
  await s.worker.scheduled({}, env);
  assert.equal(s.calls.length, 1);
  assert.equal(s.logs.at(-1).status, "active_run");
});

test("does not dispatch when latest run is under 25 minutes old", async () => {
  const s = setup(runs([run("completed", recent)]));
  await s.worker.scheduled({}, env);
  assert.equal(s.calls.length, 1);
});

test("fails closed for missing secret, HTTP errors, and malformed runs data", async t => {
  await t.test("missing secret", async () => {
    const s = setup(runs([]));
    await s.worker.scheduled({}, {});
    assert.equal(s.calls.length, 0);
    assert.equal(s.logs[0].status, "missing_secret");
  });
  await t.test("GET failure", async () => {
    const s = setup(new Response("secret body", { status: 500 }));
    await s.worker.scheduled({}, env);
    assert.equal(s.calls.length, 1);
  });
  await t.test("bad JSON shape", async () => {
    const s = setup(new Response(JSON.stringify({ nope: [] }), { status: 200 }));
    await s.worker.scheduled({}, env);
    assert.equal(s.calls.length, 1);
  });
  await t.test("POST failure", async () => {
    const s = setup(runs([]), new Response("secret body", { status: 403 }));
    await s.worker.scheduled({}, env);
    assert.equal(s.calls.length, 2);
    assert.equal(s.logs.at(-1).status, "dispatch_http_error");
  });
});

test("public fetch route is read-only 404", async () => {
  const { worker, calls } = setup(runs([]));
  const response = await worker.fetch(new Request("https://worker.example/dispatch"), env);
  assert.equal(response.status, 404);
  assert.equal(calls.length, 0);
});
