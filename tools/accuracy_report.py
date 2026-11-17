#!/usr/bin/env python3
from __future__ import annotations

import base64
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadence

OUT_DIR = ".report-out"
FEED_DIR = ".feed-state"
REPORT_FILE = "report.bin"
REPORT_INFO = b"night-report"
KEY_LEN = 32
NONCE_LEN = 12
MIN_OPEN_GAP = 480
TOTAL_SECONDS = 300
CLONE_SECONDS = 60
GAP_DAYS = 7
JUMP = 0.25
RUN_LIMIT = 5
TOLERANCE_LOW = 0.01
TOLERANCE_HIGH = 0.03


def _hkdf(secret: bytes, info: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=info).derive(secret)


def encrypt_report(owner_public_b64: str, payload: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    owner = X25519PublicKey.from_public_bytes(base64.b64decode(owner_public_b64, validate=True))
    ephemeral = X25519PrivateKey.generate()
    key = _hkdf(ephemeral.exchange(owner), REPORT_INFO)
    nonce = os.urandom(NONCE_LEN)
    public = ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(public + nonce + AESGCM(key).encrypt(nonce, payload, None))


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".out-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def tehran_date(now: float) -> str:
    return cadence.local_time(now).date().isoformat()


def artifact_name(now: float) -> str:
    return f"report-{tehran_date(now)}"


def artifact_exists(env, name: str, runner=subprocess.run) -> bool | None:
    repo = env.get("GITHUB_REPOSITORY", "")
    if not repo:
        return None
    try:
        done = runner(
            ["gh", "api", f"repos/{repo}/actions/artifacts?name={name}&per_page=100",
             "--jq", "[.artifacts[] | select(.expired == false)] | length"],
            capture_output=True, text=True, timeout=30, check=False)
        if done.returncode != 0:
            return None
        return int(done.stdout.strip() or "0") > 0
    except Exception:
        return None


def window_too_close(now: float) -> bool:
    return cadence.in_window(now) or cadence.next_open(now) - now < MIN_OPEN_GAP


def check(env, now: float, log, runner=subprocess.run) -> bool:
    name = artifact_name(now)
    skip = False
    if window_too_close(now):
        skip = True
        log("report: skipped (window close)")
    elif str(env.get("REPORT_KEYED", "")).lower() == "false":
        skip = True
        log("report not exported (no key)")
    elif str(env.get("REPORT_FORCE", "")).lower() != "true":
        found = artifact_exists(env, name, runner)
        if found is None or found:
            skip = True
            log("report: skipped (already done or unknown)")
    _emit(env, skip=skip, name=name)
    return skip


def _close(entry):
    try:
        buy, sell = entry
    except (TypeError, ValueError):
        return None
    price = sell if sell is not None else buy
    return price if isinstance(price, (int, float)) and not isinstance(price, bool) else None


def quality(series: dict) -> dict:
    days = []
    bad_dates = 0
    for key in sorted(series):
        try:
            days.append((date.fromisoformat(key), _close(series[key])))
        except (ValueError, TypeError):
            bad_dates += 1
    gaps = bad_close = jumps = runs = 0
    previous_day = None
    previous_close = None
    run = 1
    for day, close in days:
        if previous_day is not None and (day - previous_day).days > GAP_DAYS:
            gaps += 1
        previous_day = day
        if close is None or not close > 0:
            bad_close += 1
            previous_close = None
            run = 1
            continue
        if previous_close is not None:
            if abs(close / previous_close - 1) > JUMP:
                jumps += 1
            if close == previous_close:
                run += 1
                if run == RUN_LIMIT + 1:
                    runs += 1
            else:
                run = 1
        previous_close = close
    out = {"days": len(days), "gaps": gaps, "badCloses": bad_close, "jumps": jumps, "flatRuns": runs,
           "badDates": bad_dates}
    out["issues"] = bool(gaps or bad_close or jumps or runs or bad_dates)
    return out


def cross_check(daily_codes: dict, live: dict) -> dict:
    per_code: dict = {}
    compared = over_low = over_high = 0
    for day in sorted(live or {}):
        prices = live[day]
        if not isinstance(prices, dict):
            continue
        for code, price in prices.items():
            series = daily_codes.get(code)
            archive = _close(series.get(day)) if isinstance(series, dict) and day in series else None
            if archive is None or not archive > 0:
                continue
            if not isinstance(price, (int, float)) or isinstance(price, bool) or not price > 0:
                continue
            diff = abs(archive / price - 1)
            compared += 1
            over_low += diff > TOLERANCE_LOW
            over_high += diff > TOLERANCE_HIGH
            per_code.setdefault(code, {})[day] = diff
    return {"compared": compared, "over1": over_low, "over3": over_high, "codes": per_code}


def track_stats(feed_dir, env) -> dict:
    out = {"scored": 0, "hits": 0, "rate": None, "codes": {}}
    try:
        import forecast_track
        import headline_log
        master = headline_log.master_key(env)
        path = Path(feed_dir) / forecast_track.FILE_NAME
        if master is None or not path.is_file():
            return out
        records = forecast_track._decrypt(forecast_track._derive(master), path.read_bytes())
    except Exception:
        return out
    for record in records:
        codes = record.get("codes")
        if not isinstance(codes, dict):
            continue
        for code, entry in codes.items():
            if not isinstance(entry, dict) or entry.get("actual") is None or not isinstance(entry.get("hit"), bool):
                continue
            slot = out["codes"].setdefault(code, {"scored": 0, "hits": 0})
            slot["scored"] += 1
            slot["hits"] += entry["hit"]
            out["scored"] += 1
            out["hits"] += entry["hit"]
    if out["scored"]:
        out["rate"] = out["hits"] / out["scored"]
    return out


def live_closes(feed_dir, env) -> dict:
    try:
        import live_close
        key = live_close.derive_key(env)
        if key is None:
            return {}
        found = live_close.read(feed_dir, key)
        return found if isinstance(found, dict) else {}
    except Exception:
        return {}


def evaluate_code(code: str, series: dict, today, generated_at: str) -> dict:
    import forecast_eval
    import forecast_report
    import gheymat_forecast as fc
    points = forecast_report.points_from_daily(series)
    diag = forecast_report.diagnose(points, today)
    doc, reason = fc.build_forecast(code, points, today, generated_at)
    compared = forecast_eval.compare(points)
    kwargs = {}
    if "n_perm" in inspect.signature(forecast_eval.regimes).parameters:
        kwargs["n_perm"] = 0
    analysis = forecast_eval.regimes({"codes": {code: series}}, [code], **kwargs).get("codes", {}).get(code)
    return {"diag": diag, "pass": doc is not None, "reason": reason, "compare": compared, "regime": analysis}


def fetch_daily(env, workdir: str, seconds: int = CLONE_SECONDS):
    import gheymat_seal
    repo = env.get("GITHUB_REPOSITORY", "")
    if not repo:
        return None
    target = os.path.join(workdir, "pages")
    done = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "gh-pages", f"https://github.com/{repo}.git", target],
        capture_output=True, timeout=seconds, check=False)
    if done.returncode != 0:
        return None
    return gheymat_seal.load_published(Path(target), "v1/daily.json", gheymat_seal.Sealer.from_env())


def _today(now: float, latest: str | None):
    try:
        import gheymat_ai
        return gheymat_ai.default_today(datetime.fromtimestamp(now, timezone.utc))
    except Exception:
        return date.fromisoformat(latest) if latest else date.today()


def _latest_date(daily: dict) -> str | None:
    latest = None
    for series in (daily.get("codes") or {}).values():
        if isinstance(series, dict) and series:
            last = max(series)
            if latest is None or last > latest:
                latest = last
    return latest


def _pooled(results: dict) -> float | None:
    hit = total = 0.0
    for r in results.values():
        d = r.get("diag") or {}
        if d.get("coverage") is not None and d.get("weeks"):
            hit += d["coverage"] * d["weeks"]
            total += d["weeks"]
    return hit / total if total else None


def _verdict(results: dict):
    import forecast_eval
    try:
        return forecast_eval.verdict({c: r.get("regime") for c, r in results.items()})
    except Exception:
        return None


def _round(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _emit(env, **values) -> None:
    path = env.get("GITHUB_OUTPUT", "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            for k, v in values.items():
                text = ("true" if v else "false") if isinstance(v, bool) else str(v)
                handle.write(f"{k}={text}\n")
    except OSError:
        pass


def build(env, daily: dict, now: float, log, clock, started: float, feed_dir) -> tuple[dict, dict]:
    codes = sorted(daily["codes"])
    latest = _latest_date(daily)
    today = _today(now, latest)
    generated_at = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results: dict = {}
    partial = False
    for code in codes:
        if clock() - started >= TOTAL_SECONDS:
            partial = True
            break
        try:
            results[code] = evaluate_code(code, daily["codes"][code], today, generated_at)
        except Exception as e:
            log(f"report: code evaluation failed ({type(e).__name__})")
    scan = {c: quality(daily["codes"][c]) for c in codes if isinstance(daily["codes"][c], dict)}
    track = track_stats(feed_dir, env)
    cross = cross_check(daily["codes"], live_closes(feed_dir, env))
    pooled = _pooled(results)
    body = {"generated": generated_at, "historyDate": latest, "partial": partial, "codes": results,
            "quality": scan, "regimeVerdict": _verdict(results), "pooledCoverage": pooled, "track": track,
            "archiveVsLive": cross}
    summary = {"codes": len(results), "passing": sum(1 for r in results.values() if r.get("pass")),
               "pooled": pooled, "issues": sum(1 for q in scan.values() if q["issues"]),
               "scored": track["scored"], "partial": partial}
    return body, summary


def run(env, now: float, log, clock) -> int:
    started = clock()
    if window_too_close(now):
        log("report: skipped (window close)")
        _emit(env, report=False)
        return 0
    feed_dir = env.get("REPORT_FEED_DIR", FEED_DIR)
    try:
        with tempfile.TemporaryDirectory() as work:
            daily = fetch_daily(env, work)
    except (Exception, SystemExit) as e:
        log(f"report: history failed ({type(e).__name__})")
        daily = None
    if not isinstance(daily, dict) or not isinstance(daily.get("codes"), dict) or not daily["codes"]:
        log("report: skipped (history unavailable)")
        _emit(env, report=False)
        return 0
    body, summary = build(env, daily, now, log, clock, started, feed_dir)
    pub = (env.get("GHEYMAT_OWNER_PUBKEY") or "").strip()
    exported = False
    if pub:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        _write_atomic(Path(env.get("REPORT_OUT_DIR", OUT_DIR)) / REPORT_FILE, encrypt_report(pub, payload))
        exported = True
    else:
        log("report not exported (no key)")
    log(f"report: codes={summary['codes']} passing={summary['passing']} coverage={_round(summary['pooled'])} "
        f"quality_issues={summary['issues']} live_scored={summary['scored']} "
        f"seconds={int(clock() - started)} partial={'yes' if summary['partial'] else 'no'}")
    _emit(env, report=exported)
    return 0


def main(argv=None, environ=None, now=None, log=print, clock=time.monotonic) -> int:
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    now = time.time() if now is None else now
    try:
        if "--check" in argv:
            check(environ, now, log)
            return 0
        return run(environ, now, log, clock)
    except (Exception, SystemExit) as e:
        log(f"report: failed ({type(e).__name__})")
        _emit(environ, report=False, **({"skip": True} if "--check" in argv else {}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
