const OFFSET_SECONDS = 3 * 3600 + 1800;
const WINDOW_START = 8;
const WINDOW_END = 17;
const THURSDAY_END = 13;
const OPEN_DAYS = [5, 6, 0, 1, 2, 3];
const THURSDAY = 3;
const ACTIVE_WITHIN = 600;
const BACKOFF_SECONDS = 600;
const QUIET_CONCLUSIONS = new Set(["success", "cancelled", "skipped"]);
const API = "https://api.github.com";

const seconds = (stamp) => Date.parse(stamp) / 1000;

export function inWindow(epochSeconds) {
  const local = new Date((epochSeconds + OFFSET_SECONDS) * 1000);
  const day = (local.getUTCDay() + 6) % 7;
  if (!OPEN_DAYS.includes(day)) return false;
  const end = day === THURSDAY ? THURSDAY_END : WINDOW_END;
  const hour = local.getUTCHours();
  return hour >= WINDOW_START && hour < end;
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

export async function tick(env, nowSeconds, fetchFn) {
  if (env.HOURS !== "off" && !inWindow(nowSeconds)) return "closed";
  if (!env.GH_DISPATCH_TOKEN) return "error:config";
  const base = `${API}/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}`;
  const headers = {
    Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "gheymat-scheduler",
  };
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
