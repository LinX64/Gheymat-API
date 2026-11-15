import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import worker, { inWindow, hasActiveRun, shouldBackOff, tick } from "../index.js";

const tehran = (y, m, d, h, mi) => Date.UTC(y, m - 1, d, h, mi) / 1000 - 12600;

const fixture = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/window_cases.json", import.meta.url), "utf8"),
);

test("window matches fixture", () => {
  assert.ok(fixture.length > 0);
  for (const c of fixture) {
    assert.equal(inWindow(c.epoch), c.open, `epoch ${c.epoch}`);
  }
});

test("window edges", () => {
  assert.equal(inWindow(tehran(2026, 11, 19, 12, 59)), true);
  assert.equal(inWindow(tehran(2026, 11, 19, 13, 0)), false);
  for (let h = 0; h < 24; h++) {
    assert.equal(inWindow(tehran(2026, 11, 20, h, 30)), false);
  }
  assert.equal(inWindow(tehran(2026, 11, 14, 7, 59)), false);
  assert.equal(inWindow(tehran(2026, 11, 14, 8, 0)), true);
  assert.equal(inWindow(tehran(2026, 11, 18, 16, 59)), true);
  assert.equal(inWindow(tehran(2026, 11, 18, 17, 0)), false);
});

const iso = (epoch) => new Date(epoch * 1000).toISOString();

test("hasActiveRun", () => {
  const now = tehran(2026, 11, 15, 10, 0);
  const fresh = iso(now - 60);
  const stale = iso(now - 700);
  assert.equal(hasActiveRun([], now), false);
  assert.equal(hasActiveRun([{ status: "completed", created_at: fresh }], now), false);
  assert.equal(hasActiveRun([{ status: "completed", created_at: fresh }, { status: "pending", created_at: fresh }], now), true);
  assert.equal(hasActiveRun([{ status: "queued", created_at: fresh }], now), true);
  assert.equal(hasActiveRun([{ status: "in_progress", created_at: fresh }], now), true);
  assert.equal(hasActiveRun([{ status: "queued", created_at: stale }], now), false);
  assert.equal(hasActiveRun([{ status: "queued" }], now), true);
});

test("shouldBackOff", () => {
  const now = tehran(2026, 11, 15, 10, 0);
  const done = (conclusion, ago) => [{ status: "completed", conclusion, updated_at: iso(now - ago) }];
  assert.equal(shouldBackOff([], now), false);
  assert.equal(shouldBackOff(done("failure", 60), now), true);
  assert.equal(shouldBackOff(done("failure", 700), now), false);
  assert.equal(shouldBackOff(done("success", 60), now), false);
  assert.equal(shouldBackOff(done("cancelled", 60), now), false);
  assert.equal(shouldBackOff(done("timed_out", 60), now), true);
});

const OPEN_NOW = tehran(2026, 11, 15, 10, 0);
const CLOSED_NOW = tehran(2026, 11, 20, 10, 0);
const env = {
  REPO: "o/r",
  WORKFLOW: "w.yml",
  REF: "master",
  HOURS: "on",
  GH_DISPATCH_TOKEN: "tok",
};

const makeFetch = (responses) => {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    const r = responses[calls.length - 1];
    if (r instanceof Error) throw r;
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body || {} };
  };
  fn.calls = calls;
  return fn;
};

test("closed makes no calls", async () => {
  const f = makeFetch([]);
  assert.equal(await tick(env, CLOSED_NOW, f), "closed");
  assert.equal(f.calls.length, 0);
});

test("active only GETs", async () => {
  const f = makeFetch([{ status: 200, body: { workflow_runs: [{ status: "queued", created_at: iso(OPEN_NOW - 30) }] } }]);
  assert.equal(await tick(env, OPEN_NOW, f), "active");
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].init.method, "GET");
});

test("idle dispatches", async () => {
  const f = makeFetch([
    { status: 200, body: { workflow_runs: [{ status: "completed", conclusion: "success", updated_at: iso(OPEN_NOW - 30) }] } },
    { status: 204 },
  ]);
  assert.equal(await tick(env, OPEN_NOW, f), "dispatched");
  assert.equal(f.calls.length, 2);
  const base = "https://api.github.com/repos/o/r/actions/workflows/w.yml";
  assert.equal(f.calls[0].url, `${base}/runs?per_page=5`);
  assert.equal(f.calls[1].url, `${base}/dispatches`);
  assert.equal(f.calls[1].init.method, "POST");
  assert.deepEqual(JSON.parse(f.calls[1].init.body), { ref: "master" });
  for (const c of f.calls) {
    assert.equal(c.init.headers.Authorization, "Bearer tok");
    assert.equal(c.init.headers.Accept, "application/vnd.github+json");
    assert.equal(c.init.headers["X-GitHub-Api-Version"], "2022-11-28");
    assert.equal(c.init.headers["User-Agent"], "gheymat-scheduler");
  }
});

test("GET 403", async () => {
  const f = makeFetch([{ status: 403 }]);
  assert.equal(await tick(env, OPEN_NOW, f), "error:403");
  assert.equal(f.calls.length, 1);
});

test("POST 422", async () => {
  const f = makeFetch([{ status: 200, body: { workflow_runs: [] } }, { status: 422 }]);
  assert.equal(await tick(env, OPEN_NOW, f), "error:422");
});

test("network error", async () => {
  const f = makeFetch([new Error("boom")]);
  assert.equal(await tick(env, OPEN_NOW, f), "error:network");
});

test("HOURS off ignores window", async () => {
  const f = makeFetch([{ status: 200, body: { workflow_runs: [] } }, { status: 204 }]);
  assert.equal(await tick({ ...env, HOURS: "off" }, CLOSED_NOW, f), "dispatched");
});

test("missing token", async () => {
  const f = makeFetch([]);
  const { GH_DISPATCH_TOKEN, ...noToken } = env;
  assert.equal(await tick(noToken, OPEN_NOW, f), "error:config");
  assert.equal(f.calls.length, 0);
});

test("recent failure backs off without dispatching", async () => {
  const f = makeFetch([
    { status: 200, body: { workflow_runs: [{ status: "completed", conclusion: "failure", updated_at: iso(OPEN_NOW - 60) }] } },
  ]);
  assert.equal(await tick(env, OPEN_NOW, f), "backoff");
  assert.equal(f.calls.length, 1);
});

test("old failure does not back off", async () => {
  const f = makeFetch([
    { status: 200, body: { workflow_runs: [{ status: "completed", conclusion: "failure", updated_at: iso(OPEN_NOW - 3600) }] } },
    { status: 204 },
  ]);
  assert.equal(await tick(env, OPEN_NOW, f), "dispatched");
});

test("stale queued run does not block", async () => {
  const f = makeFetch([
    { status: 200, body: { workflow_runs: [{ status: "queued", created_at: iso(OPEN_NOW - 3600) }] } },
    { status: 204 },
  ]);
  assert.equal(await tick(env, OPEN_NOW, f), "dispatched");
});

test("response without a runs list is an error", async () => {
  const f = makeFetch([{ status: 200, body: {} }]);
  assert.equal(await tick(env, OPEN_NOW, f), "error:shape");
  assert.equal(f.calls.length, 1);
});

test("unreadable runs list is a network error", async () => {
  const f = async () => ({ ok: true, status: 200, json: async () => { throw new Error("bad"); } });
  assert.equal(await tick(env, OPEN_NOW, f), "error:network");
});

test("scheduled throws on an error result", async () => {
  const noToken = { REPO: "o/r", WORKFLOW: "w.yml", REF: "master", HOURS: "off" };
  await assert.rejects(worker.scheduled({ scheduledTime: OPEN_NOW * 1000 }, noToken), /error:config/);
});

test("scheduled stays quiet when closed", async () => {
  await worker.scheduled({ scheduledTime: CLOSED_NOW * 1000 }, { ...env });
});
