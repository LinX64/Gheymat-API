const OFFSET_SECONDS = 3 * 3600 + 1800;
const WINDOW_START = 8;
const WINDOW_END = 17;
const THURSDAY_END = 13;
const OPEN_DAYS = [5, 6, 0, 1, 2, 3];
const THURSDAY = 3;
const NIGHT_SLOTS = [[20, 30], [23, 30]];
const NIGHT_SLOT_MINUTES = 5;
const REPORT_HOURS = [1, 2];
const ACTIVE_WITHIN = 600;
const BACKOFF_SECONDS = 600;
const QUIET_CONCLUSIONS = new Set(["success", "cancelled", "skipped"]);
const API = "https://api.github.com";

const seconds = (stamp) => Date.parse(stamp) / 1000;

const localOf = (epochSeconds) => new Date((epochSeconds + OFFSET_SECONDS) * 1000);

export function inDayWindow(epochSeconds) {
  const local = localOf(epochSeconds);
  const day = (local.getUTCDay() + 6) % 7;
  if (!OPEN_DAYS.includes(day)) return false;
  const end = day === THURSDAY ? THURSDAY_END : WINDOW_END;
  const hour = local.getUTCHours();
  return hour >= WINDOW_START && hour < end;
}

export function inNightSlot(epochSeconds) {
  const local = localOf(epochSeconds);
  const hour = local.getUTCHours();
  const minute = local.getUTCMinutes();
  return NIGHT_SLOTS.some(([h, m]) => hour === h && minute >= m && minute < m + NIGHT_SLOT_MINUTES);
}

export function inWindow(epochSeconds) {
  return inDayWindow(epochSeconds) || inNightSlot(epochSeconds);
}

export function isReportMinute(epochSeconds) {
  const local = localOf(epochSeconds);
  return local.getUTCMinutes() === 0 && REPORT_HOURS.includes(local.getUTCHours());
}

export function hasActiveRun(runs, nowSeconds) {
  return (runs || []).some(
    (run) => run.status !== "completed" && !(nowSeconds - seconds(run.created_at) >= ACTIVE_WITHIN),
  );
}

export function shouldBackOff(runs, nowSeconds) {
  const newest = (runs || [])[0];
  if (!newest || newest.status !== "completed") return false;
  if (QUIET_CONCLUSIONS.has(newest.conclusion)) return false;
  return nowSeconds - seconds(newest.updated_at) < BACKOFF_SECONDS;
}

const authHeaders = (env) => ({
  Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
  Accept: "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
  "User-Agent": "gheymat-scheduler",
});

async function dispatchReport(env, fetchFn) {
  const workflow = env.REPORT_WORKFLOW || "report.yml";
  const url = `${API}/repos/${env.REPO}/actions/workflows/${workflow}/dispatches`;
  try {
    const res = await fetchFn(url, {
      method: "POST",
      headers: { ...authHeaders(env), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: env.REF }),
    });
    return res.ok ? "report-dispatched" : `error:${res.status}`;
  } catch {
    return "error:network";
  }
}

export async function tick(env, nowSeconds, fetchFn) {
  if (isReportMinute(nowSeconds)) {
    if (!env.GH_DISPATCH_TOKEN) return "error:config";
    return dispatchReport(env, fetchFn);
  }
  if (env.HOURS !== "off" && !inWindow(nowSeconds)) return "closed";
  if (!env.GH_DISPATCH_TOKEN) return "error:config";
  const base = `${API}/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}`;
  const headers = authHeaders(env);
  let runs;
  try {
    const list = await fetchFn(`${base}/runs?per_page=5`, { method: "GET", headers });
    if (!list.ok) return `error:${list.status}`;
    runs = (await list.json()).workflow_runs;
  } catch {
    return "error:network";
  }
  if (!Array.isArray(runs)) return "error:shape";
  if (hasActiveRun(runs, nowSeconds)) return "active";
  if (shouldBackOff(runs, nowSeconds)) return "backoff";
  try {
    const res = await fetchFn(`${base}/dispatches`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: env.REF }),
    });
    return res.ok ? "dispatched" : `error:${res.status}`;
  } catch {
    return "error:network";
  }
}

export default {
  async scheduled(event, env) {
    const result = await tick(env, event.scheduledTime / 1000, fetch);
    console.log(result);
    if (result.startsWith("error:")) throw new Error(result);
  },
};
