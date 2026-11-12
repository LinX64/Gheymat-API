from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_versions
import verify_sealed
from gheymat_seal import MAX_ENVELOPE_BYTES, opaque_path, open_envelope

DIGEST_CONTEXT = b"feed-sync-digest"
CACHE_CONTROL = "public, max-age=0, must-revalidate"
CONTENT_TYPE = "application/json"
EXCLUDED_RELATIVE = ("daily.json",)
HEALTH_LOGICAL = "health"
HOT_LOGICALS = ("v1/latest", HEALTH_LOGICAL)
KNOWN_KINDS = ("status", "timeout", "connection", "config")
WARMUP_SECONDS = 1800
HOURS_PER_MONTH = 730
SPACING_CAP = 1800
GUARD_PAUSE_SECONDS = 1800
TIER_ORDER = {"hot": 0, "warm": 1, "cold": 2}


@dataclass
class Upload:
    key: str = field(repr=False)
    body: bytes = field(repr=False)
    logical: str = field(repr=False)
    tier: str
    digest: str = field(default="", repr=False)
    issued: int = field(default=0, repr=False)


@dataclass
class SyncResult:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    hot_ok: bool = False
    over_budget: bool = False
    keys_failed_kinds: dict = field(default_factory=dict)


@dataclass
class Candidate:
    key: str = field(repr=False)
    path: Path = field(repr=False)
    logical: str = field(repr=False)
    tier: str


def tier_of(version_id: str, relative: str) -> str:
    if version_id != "v1":
        return "cold"
    if relative == "latest":
        return "hot"
    if relative == "instruments" or relative.startswith("intraday/"):
        return "warm"
    return "cold"


def failure_kind(error: BaseException) -> str:
    kind = getattr(error, "kind", None)
    return kind if kind in KNOWN_KINDS else "unknown"


class FeedSync:
    def __init__(self, store, payload_key: bytes, public_key, clock=time.time, log=print,
                 intraday_spacing: int = 300, instruments_max_age: int = 1500, slow_max_age: int = 1500,
                 monthly_put_budget: int = 800000, hot_deadline: float = 20.0,
                 rest_deadline: float = 100.0, workers: int = 8, include_v2: bool = True):
        self._store = store
        self._payload_key = payload_key
        self._public_key = public_key
        self._digest_key = hmac.new(payload_key, DIGEST_CONTEXT, hashlib.sha256).digest()
        self._clock = clock
        self._log = log
        self._spacing = intraday_spacing
        self._instruments_max_age = instruments_max_age
        self._slow_max_age = slow_max_age
        self._budget = monthly_put_budget
        self._hot_deadline = hot_deadline
        self._rest_deadline = rest_deadline
        self._workers = max(1, workers)
        self._include_v2 = include_v2
        self._manifest: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._first_sync_at: float | None = None
        self._cold_sync_done = False
        self._burst_end_at: float | None = None
        self._burst_end_puts = 0
        self._puts_issued = 0
        self._guard_paused_until: float | None = None
        self._guard_logged = False

    def __repr__(self) -> str:
        return "FeedSync()"

    def candidates(self) -> list[Candidate]:
        codes = verify_sealed.all_codes()
        found: list[Candidate] = []
        for version in site_versions.VERSIONS:
            vid = version["id"]
            derived = version.get("derivesFrom") is not None
            if derived and not self._include_v2:
                continue
            prefix = f"{vid}/" if derived else ""
            for relative in verify_sealed.relative_logicals(version["docs"], codes):
                if relative in EXCLUDED_RELATIVE:
                    continue
                logical = f"{vid}/{relative}"
                name = opaque_path(self._payload_key, logical)
                found.append(Candidate(prefix + name, Path(prefix + name), logical, tier_of(vid, relative)))
        name = opaque_path(self._payload_key, HEALTH_LOGICAL)
        found.append(Candidate(name, Path(name), HEALTH_LOGICAL, "hot"))
        hot_rank = {logical: i for i, logical in enumerate(HOT_LOGICALS)}
        found.sort(key=lambda c: (TIER_ORDER[c.tier], hot_rank.get(c.logical, 0)))
        return found

    def digest_of(self, plaintext) -> str:
        canonical = json.dumps(plaintext, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hmac.new(self._digest_key, canonical, hashlib.sha256).hexdigest()

    def read_candidate(self, site: Path, candidate: Candidate):
        target = site / candidate.path
        if target.parent.is_symlink():
            return "missing"
        try:
            info = os.lstat(target)
        except OSError:
            return "missing"
        if not stat.S_ISREG(info.st_mode):
            return "missing"
        if info.st_size > MAX_ENVELOPE_BYTES:
            return "failed"
        try:
            with open(target, "rb") as handle:
                body = handle.read(MAX_ENVELOPE_BYTES + 1)
        except OSError:
            return "failed"
        if len(body) > MAX_ENVELOPE_BYTES:
            return "failed"
        return body

    def wanted(self, candidate: Candidate, digest: str, issued: int, slow_lane: bool, now: float) -> bool:
        known = self._manifest.get(candidate.key)
        if candidate.tier == "hot":
            return True
        if known is None:
            return True
        changed = known["digest"] != digest
        age = now - known["issued"]
        if candidate.tier == "cold":
            stale = age >= self._slow_max_age
            if slow_lane:
                return changed or stale
            return stale and issued > known["issued"]
        if candidate.logical == "v1/instruments":
            return changed or age >= self._instruments_max_age
        return changed and now - known["uploaded_at"] >= self._spacing

    def evaluate(self, site: Path, slow_lane: bool):
        now = self._clock()
        uploads: list[Upload] = []
        skipped = failed = 0
        for candidate in self.candidates():
            body = self.read_candidate(site, candidate)
            if body == "missing":
                skipped += 1
                continue
            if body == "failed":
                failed += 1
                continue
            try:
                envelope = json.loads(body)
                plaintext = open_envelope(envelope, self._payload_key, self._public_key, candidate.logical,
                                          max_age=None, max_future=None)
                digest = self.digest_of(plaintext)
                issued = int(envelope["issued"])
            except Exception:
                failed += 1
                continue
            if self.wanted(candidate, digest, issued, slow_lane, now):
                uploads.append(Upload(candidate.key, body, candidate.logical, candidate.tier, digest, issued))
            else:
                skipped += 1
        return uploads, skipped, failed

    def plan(self, site: Path, slow_lane: bool) -> list[Upload]:
        try:
            return self.evaluate(Path(site), slow_lane)[0]
        except Exception:
            return []

    def put_one(self, upload: Upload, result: SyncResult, start: float, deadline: float) -> bool:
        remaining = deadline - (self._clock() - start)
        if remaining <= 0:
            with self._lock:
                result.skipped += 1
                result.over_budget = True
            return False
        with self._lock:
            self._puts_issued += 1
        try:
            self._store.put(upload.key, upload.body, CONTENT_TYPE, CACHE_CONTROL,
                            timeout=(5, max(1, min(30, remaining))))
        except Exception as error:
            kind = failure_kind(error)
            with self._lock:
                result.failed += 1
                result.keys_failed_kinds[kind] = result.keys_failed_kinds.get(kind, 0) + 1
            return False
        stamp = self._clock()
        with self._lock:
            self._manifest[upload.key] = {"digest": upload.digest, "issued": upload.issued, "uploaded_at": stamp}
            result.uploaded += 1
        return True

    def run_hot(self, hot: list[Upload], start: float, result: SyncResult) -> None:
        stored = 0
        for index, upload in enumerate(hot):
            if self._clock() - start >= self._hot_deadline:
                result.skipped += len(hot) - index
                result.over_budget = True
                break
            if self.put_one(upload, result, start, self._hot_deadline):
                stored += 1
        result.hot_ok = stored == len(HOT_LOGICALS)

    def run_rest(self, rest: list[Upload], start: float, result: SyncResult) -> None:
        def task(upload: Upload) -> None:
            self.put_one(upload, result, start, self._rest_deadline)

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for future in [pool.submit(task, u) for u in rest]:
                future.result()

    def sync(self, site: Path, slow_lane: bool) -> SyncResult:
        result = SyncResult()
        try:
            start = self._clock()
            if self._first_sync_at is None:
                self._first_sync_at = start
            uploads, skipped, failed = self.evaluate(Path(site), slow_lane)
            result.skipped += skipped
            result.failed += failed
            hot = [u for u in uploads if u.tier == "hot"]
            rest = [u for u in uploads if u.tier != "hot"]
            self.run_hot(hot, start, result)
            self.run_rest(rest, start, result)
            if slow_lane:
                self._cold_sync_done = True
                if self._burst_end_at is None:
                    self._burst_end_at = self._clock()
                    self._burst_end_puts = self._puts_issued
            self.guard()
        except Exception:
            result.failed += 1
        try:
            self._log(f"feed sync: uploaded {result.uploaded}, skipped {result.skipped}, failed {result.failed}")
        except Exception:
            pass
        return result

    def projected_monthly_puts(self) -> int | None:
        if self._first_sync_at is None or not self._cold_sync_done or self._burst_end_at is None:
            return None
        now = self._clock()
        if now - self._first_sync_at < WARMUP_SECONDS:
            return None
        hours = (now - self._burst_end_at) / 3600
        if hours <= 0:
            return None
        return int((self._puts_issued - self._burst_end_puts) / hours * HOURS_PER_MONTH)

    def guard(self) -> None:
        now = self._clock()
        if self._guard_paused_until is not None and now < self._guard_paused_until:
            return
        projected = self.projected_monthly_puts()
        if projected is None or projected <= self._budget or self._spacing >= SPACING_CAP:
            return
        self._spacing = min(self._spacing * 2, SPACING_CAP)
        self._guard_paused_until = now + GUARD_PAUSE_SECONDS
        if not self._guard_logged:
            self._guard_logged = True
            self._log(f"feed sync: projected writes high, intraday spacing {self._spacing} s")
