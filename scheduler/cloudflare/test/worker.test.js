import assert from "node:assert/strict";
import test from "node:test";

import { dispatchAttempt, dueEvents } from "../src/worker.js";

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
