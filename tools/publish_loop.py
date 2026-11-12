import datetime
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import cadence

TOOLS_DIR = Path(__file__).resolve().parent
SNAPSHOT = "tools/gheymat_snapshot.py"
VERIFY = "tools/verify_sealed.py"
ASSEMBLE = "tools/assemble_site.py"
WRANGLER_VERSION = "4.159.0"
CLOUDFLARE_PROJECT = "gheymat-feed"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
LIVE_FIRST_FROM_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
DIGITS = re.compile(r"[0-9]+")
KEPT_IN_DIST = ("v1", "d", "archive")
POLL_SECONDS = 15
GITHUB_PUSH_SPACING = 400
SLOW_LANE_SPACING = 1800
SLOW_LANE_BACKOFF = 600
SLOW_LANE_ALARM = 5400
CHAIN_AFTER = 120
STATE_FILE = "loop-state.json"
STATE_MAX_AGE = 200
CHAIN_RESERVE = 35
ITERATION_MIN = 60
INSTALL_CAP = 60
FLUSH_MIN = 20
NEWS_MIN_SECONDS = 40
SLOW_MIN_SECONDS = 110
DEPLOY_CAP = 90
STAMP_FIELDS = ("last_publish", "last_gh", "last_slow", "slow_ok_at")
STATE_FIELDS = (
    "last_mark",
    "last_publish",
    "last_gh",
    "last_slow",
    "slow_ok_at",
    "slow_after",
    "failures",
    "cf_failures",
    "gh_failures",
    "store_failures",
    "nothing",
    "iteration",
    "fast_ok",
    "fast_retry",
    "grace",
    "force",
    "force_slow",
    "hot_until",
    "slow_alarm",
    "pages_tried",
    "want_fetch",
    "have_dist",
    "fresh_restore",
)
ALERT_PAGES = "Feed: Cloudflare deploy failing"
ALERT_STORE = "Feed: store failing"
STORE_SECRETS = ("FEED_STORE_KEY_ID", "FEED_STORE_SECRET", "FEED_STORE_BUCKET")
APP_SECRETS = (
    "GH_TOKEN",
    "GHEYMAT_PAYLOAD_KEY",
    "GHEYMAT_SIGNING_KEY",
    "ANTHROPIC_API_KEY",
    "GHEYMAT_AI_SOURCES",
    *STORE_SECRETS,
)
KIND_PATTERN = re.compile(r"[a-z]{1,16}")
CLOUDFLARE_SECRETS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")


class Env:
    def now(self):
        return int(time.time())

    def sleep(self, seconds):
        time.sleep(seconds)

    def rand(self, low, high):
        return random.randint(low, high)

    def emit(self, line):
        print(line, flush=True)

    def emit_err(self, line):
        print(line, file=sys.stderr, flush=True)

    def run(self, argv, env=None, timeout=None, cwd=None):
        try:
            process = subprocess.Popen(
                argv,
                env=env,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,
            )
        except OSError:
            return 127, ""
        try:
            output, _ = process.communicate(timeout=timeout)
            return process.returncode, output or ""
        except subprocess.TimeoutExpired:
            self.stop_group(process)
            return 124, ""

    def stop_group(self, process):
        for signal_number in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, signal_number)
            except OSError:
                return
            try:
                process.communicate(timeout=10)
                return
            except subprocess.TimeoutExpired:
                continue

    def rmtree(self, path):
        shutil.rmtree(path, ignore_errors=True)

    def mkdir(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)

    def move(self, source, target):
        shutil.move(source, target)

    def touch(self, path):
        Path(path).touch()

    def exists(self, path):
        return Path(path).exists()

    def remove(self, path):
        try:
            Path(path).unlink()
        except OSError:
            pass

    def clear_top(self, path, keep):
        for entry in Path(path).iterdir():
            if entry.name in keep:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink()

    def read_text(self, path):
        return Path(path).read_text()

    def write_text(self, path, text):
        target = Path(path)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(text)
        os.replace(temp, target)


def make_poll():
    state = {}

    def poll():
        try:
            if "snap" not in state:
                sys.path.insert(0, str(TOOLS_DIR))
                import gheymat_snapshot
                import requests

                state["snap"] = gheymat_snapshot
                state["session"] = requests.Session()
            snap = state["snap"]
            mark = snap.hansha_mark(snap.fetch_hansha(state["session"]))
            return mark if isinstance(mark, str) else ""
        except Exception:
            return ""

    return poll


def build_sync(environ, log, include_v2):
    sys.path.insert(0, str(TOOLS_DIR))
    import feed_sync
    import r2_store
    import verify_sealed
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from gheymat_seal import DEFAULT_KID, KEY_LEN, unb64

    payload_key = unb64(environ["GHEYMAT_PAYLOAD_KEY"])
    if len(payload_key) != KEY_LEN:
        raise ValueError("bad key length")
    public_keys = {DEFAULT_KID: Ed25519PublicKey.from_public_bytes(unb64(verify_sealed.PUBLIC_KEY_B64))}
    store = r2_store.R2Store(
        environ["CLOUDFLARE_ACCOUNT_ID"],
        environ["FEED_STORE_BUCKET"],
        environ["FEED_STORE_KEY_ID"],
        environ["FEED_STORE_SECRET"],
    )
    return feed_sync.FeedSync(
        store, payload_key, public_keys, clock=time.time, log=log, workers=8, include_v2=include_v2
    )


class Loop:
    def __init__(self, env, environ, poll, python="python", mirror=False, sync_factory=None):
        self.env = env
        self.environ = environ
        self.poll = poll
        self.python = python
        self.mirror = mirror
        self.iteration = 0
        self.failures = 0
        self.cf_failures = 0
        self.gh_failures = 0
        self.nothing = 0
        self.red = False
        self.alerted = set()
        self.last_mark = ""
        self.hot_until = 0
        self.tiers = False
        self.tier_logged = ""
        self.last_publish = 0
        self.last_gh = 0
        self.seeded = False
        self.have_dist = False
        self.want_fetch = True
        self.clean = False
        self.fast_retry = True
        self.grace = False
        self.force = False
        self.fast_ok = True
        self.date_warned = False
        self.cadence = 180
        self.last_slow = 0
        self.slow_after = 0
        self.slow_ok_at = 0
        self.slow_alarm = False
        self.fresh_restore = True
        self.force_slow = False
        self.floor_seconds = 90
        self.order = "default"
        self.started = 0
        self.sync_factory = sync_factory or build_sync
        self.sync = None
        self.configured = False
        self.store_mode = "off"
        self.pages_mode = "every"
        self.include_v2 = True
        self.store_failures = 0
        self.pages_tried = False
        self.hard = None
        self.push_timed_out = False
        self.save_warned = False

    def bounded(self, timeout):
        if self.hard is None:
            return timeout
        left = max(1, self.usable_end() - self.env.now())
        return left if timeout is None else min(timeout, left)

    def usable_end(self):
        return self.hard - CHAIN_RESERVE

    def set_hard(self):
        hard = self.environ.get("PUBLISH_HARD_SECONDS", "")
        if self.hard is None and DIGITS.fullmatch(hard):
            self.hard = (self.started or self.env.now()) + int(hard)

    def time_left(self):
        return None if self.hard is None else self.usable_end() - self.env.now()

    def capped(self, timeout, cap=INSTALL_CAP):
        if self.hard is None:
            return timeout
        return self.bounded(min(timeout, cap))

    def mask(self, line):
        for name in ("GH_TOKEN", "CLOUDFLARE_ACCOUNT_ID", *STORE_SECRETS):
            value = self.environ.get(name)
            if value:
                line = line.replace(value, "***")
        return line

    def say(self, line):
        self.env.emit(self.mask(line))

    def say_err(self, line):
        self.env.emit_err(self.mask(line))

    def choice(self, name, options, default):
        value = self.environ.get(name, "")
        if not value:
            return default
        if value in options:
            return value
        self.say(f"::warning::{name} has an unknown value, using {default}")
        return default

    def configure(self):
        if self.configured:
            return
        self.configured = True
        self.store_mode = self.choice("GHEYMAT_STORE", ("off", "shadow", "on"), "off")
        self.pages_mode = self.choice("GHEYMAT_PAGES", ("every", "shell", "off"), "every")
        self.include_v2 = self.choice("FEED_STORE_V2", ("1", "0"), "1") == "1"
        self.tiers = self.choice("GHEYMAT_CADENCE_TIERS", ("on", "off"), "off") == "on"
        if self.store_mode != "off":
            needed = (*STORE_SECRETS, "CLOUDFLARE_ACCOUNT_ID")
            if not all(self.environ.get(name) for name in needed):
                self.say("::warning::feed store is off: repository secrets are missing")
                self.store_mode = "off"

    def store_active(self):
        return self.store_mode in ("shadow", "on")

    def app_channel(self):
        return (self.mirror and self.pages_mode == "every") or self.store_mode == "on"

    def alert(self, title, detail):
        if title in self.alerted:
            return
        env = self.child_env(*APP_SECRETS[1:], *CLOUDFLARE_SECRETS)
        repo = self.environ.get("GITHUB_REPOSITORY", "")
        if repo:
            env["GH_REPO"] = repo
        code, output = self.env.run(
            ["gh", "issue", "list", "--state", "open", "--search", f'"{title}" in:title', "--json", "title", "--jq", ".[].title"],
            env=env,
            timeout=self.bounded(30),
        )
        if code == 0 and title in output.splitlines():
            self.alerted.add(title)
            return
        owner = self.environ.get("GITHUB_REPOSITORY_OWNER", "")
        body = f"{detail} @{owner}" if owner else detail
        code, _ = self.env.run(["gh", "issue", "create", "--title", title, "--body", body], env=env, timeout=self.bounded(30))
        if code == 0:
            self.alerted.add(title)
        else:
            self.say(f"::warning::The alert issue could not be opened (code {code})")

    def child_env(self, *dropped, **extra):
        child = dict(self.environ)
        for key in (*STORE_SECRETS, *dropped):
            child.pop(key, None)
        child.update(extra)
        return child

    def run_visible(self, argv, timeout=None):
        code, output = self.env.run(argv, env=self.child_env(), timeout=self.bounded(timeout))
        for line in output.splitlines():
            self.say(line)
        return code

    def clock(self, moment):
        return time.strftime("%H:%M:%SZ", time.gmtime(moment))

    def start(self):
        self.started = self.env.now()
        self.set_hard()
        self.configure()
        payload = self.environ.get("GHEYMAT_PAYLOAD_KEY", "")
        signing = self.environ.get("GHEYMAT_SIGNING_KEY", "")
        if not payload or not signing:
            self.say_err("GHEYMAT_PAYLOAD_KEY / GHEYMAT_SIGNING_KEY secrets are not set")
            return False
        self.say(f"::add-mask::{payload}")
        self.say(f"::add-mask::{signing}")
        self.setup_cloudflare()
        return True

    def setup_cloudflare(self):
        if self.pages_mode == "off":
            self.mirror = False
            return
        if not self.environ.get("CLOUDFLARE_API_TOKEN") or not self.environ.get("CLOUDFLARE_ACCOUNT_ID"):
            self.mirror = False
            self.say("::warning::Cloudflare deploy is off: repository secrets are missing")
            return
        install = ["npm", "install", "--global", "--loglevel=error", f"wrangler@{WRANGLER_VERSION}"]
        installed = False
        tried = 0
        for attempt in (1, 2, 3):
            tried = attempt
            code, _ = self.env.run(
                install,
                env=self.child_env(*APP_SECRETS, *CLOUDFLARE_SECRETS),
                timeout=self.capped(300),
            )
            if code == 0:
                installed = True
                break
            if attempt < 3:
                left = self.time_left()
                if left is not None and left < INSTALL_CAP + attempt * 10 + ITERATION_MIN + 30:
                    break
                self.env.sleep(attempt * 10)
        if not installed:
            self.mirror = False
            self.say(f"::error::Cloudflare deploy is off: Wrangler install failed{' 3 times' if tried == 3 else ''}")
            return
        self.env.run(
            ["wrangler", "pages", "project", "create", CLOUDFLARE_PROJECT, "--production-branch", "master"],
            env=self.child_env(*APP_SECRETS, WRANGLER_SEND_METRICS="false"),
            timeout=self.capped(120),
        )
        self.mirror = True

    def apply_knobs(self):
        self.configure()
        floor = self.environ.get("FLOOR_SECONDS", "")
        if DIGITS.fullmatch(floor):
            self.floor_seconds = int(floor)
        else:
            self.say("::warning::FLOOR_SECONDS is not a number, using 90")
            self.floor_seconds = 90
        self.floor_seconds = max(90, min(900, self.floor_seconds))
        order = self.environ.get("GHEYMAT_ORDER", "default")
        if order not in ("default", "live-first", "primary-only"):
            self.say("::warning::unknown order, using default")
            order = "default"
        self.order = order
        self.environ["GHEYMAT_ORDER"] = order
        self.environ.setdefault("GHEYMAT_LIVE_FIRST_FROM", "")
        self.environ.setdefault("GHEYMAT_LIVE_STATE", "")

    def live_first_start(self):
        text = self.environ.get("GHEYMAT_LIVE_FIRST_FROM", "")
        if not LIVE_FIRST_FROM_PATTERN.fullmatch(text):
            if not self.date_warned:
                self.say("::warning::GHEYMAT_LIVE_FIRST_FROM is not YYYY-MM-DDTHH:MM:SSZ, ignored")
                self.date_warned = True
            return 0
        try:
            moment = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return 0
        return int(moment.replace(tzinfo=datetime.timezone.utc).timestamp())

    def is_live_first(self, now):
        if self.order == "live-first":
            return True
        if self.order == "default" and self.environ.get("GHEYMAT_LIVE_FIRST_FROM", ""):
            start = self.live_first_start()
            return start > 0 and now >= start
        return False

    def quiet_until(self):
        try:
            value = json.loads(self.env.read_text(self.environ["GHEYMAT_LIVE_STATE"])).get("quiet_until")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return 0
            return max(0, int(value // 1))
        except Exception:
            return 0

    def is_due(self, now, since, mark):
        live_first = self.is_live_first(now)
        self.cadence = 180
        if live_first and now >= self.quiet_until() and self.fast_ok:
            self.cadence = self.floor_seconds + self.env.rand(-15, 15)
        name = cadence.PEAK
        if self.tiers:
            name = cadence.PEAK if now < self.hot_until else cadence.tier(now)
            self.cadence = max(self.cadence, cadence.tier_seconds(name, self.cadence))
            if name != self.tier_logged:
                self.tier_logged = name
                self.say(f"Cadence: {name}")
        due = False
        moved = False
        if since >= self.cadence:
            due = True
        elif self.force and since >= 45:
            due = True
        elif since >= 45 and mark and mark != self.last_mark:
            due = True
            moved = True
        if due and not self.app_channel() and now - self.last_gh < GITHUB_PUSH_SPACING:
            due = False
        if due and moved and self.tiers and name != cadence.PEAK:
            self.hot_until = now + cadence.HOT_SECONDS
        return due

    def poll_gap(self, now, deadline, since=None):
        poll = POLL_SECONDS
        if self.tiers and now >= self.hot_until:
            poll = cadence.poll_seconds(cadence.tier(now))
        if self.tiers and since is not None and since < self.cadence:
            poll = min(poll, max(1, self.cadence - since))
        return min(poll, max(1, deadline - now))

    def push_pages(self, message):
        self.push_timed_out = False
        identity = ["-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}"]
        token = self.environ.get("GH_TOKEN", "")
        repository = self.environ.get("GITHUB_REPOSITORY", "")
        url = f"https://x-access-token:{token}@github.com/{repository}.git"
        steps = (
            (["git", "init", "-q"], None),
            (["git", "checkout", "-q", "-b", "gh-pages"], None),
            (["git", *identity, "add", "-A"], None),
            (["git", *identity, "commit", "-q", "-m", message], None),
            (["git", "push", "-q", "-f", url, "gh-pages"], 120),
        )
        for argv, timeout in steps:
            code, _ = self.env.run(argv, env=self.child_env(), timeout=self.bounded(timeout), cwd="dist")
            if code == 124 and argv[1] == "push":
                self.push_timed_out = True
            if code != 0:
                return False
        return True

    def restore(self):
        self.env.rmtree("restore")
        self.env.mkdir("restore")
        env = self.child_env()
        code, _ = self.env.run(["git", "fetch", "-q", "--depth", "1", "origin", "gh-pages"], env=env, timeout=self.bounded(120))
        if code == 0:
            code, _ = self.env.run(["git", "--work-tree=restore", "checkout", "-q", "FETCH_HEAD", "--", "."], env=env, timeout=self.bounded(None))
        if code == 0:
            self.env.run(["git", "reset", "-q"], env=env, timeout=self.bounded(None))
            self.env.rmtree("dist")
            self.env.move("restore", "dist")
            self.have_dist = True
            self.fresh_restore = True
            self.want_fetch = False
            if not self.seeded:
                code, output = self.env.run(["git", "log", "-1", "--format=%ct", "FETCH_HEAD"], env=env, timeout=self.bounded(None))
                text = output.strip()
                self.last_gh = int(text) if code == 0 and DIGITS.fullmatch(text) else 0
                self.seeded = True
        else:
            self.env.run(["git", "reset", "-q"], env=env, timeout=self.bounded(None))
        self.env.rmtree("restore")

    def snapshot_argv(self, *arguments):
        return [self.python, SNAPSHOT, "--out", "dist", *arguments]

    def build(self, now):
        if not self.have_dist:
            return 91, False
        self.env.clear_top("dist", KEPT_IN_DIST)
        self.env.touch("dist/.nojekyll")
        left = self.time_left()
        slow = now >= self.slow_after and (
            self.fresh_restore or self.force_slow or now - self.last_slow >= SLOW_LANE_SPACING
        )
        if slow and left is not None and left < SLOW_MIN_SECONDS:
            slow = False
        code = 0
        if slow:
            backfill = self.environ.get("BACKFILL") or "12"
            code = self.run_visible(
                self.snapshot_argv("--history", "--ai", "--defer-news", "--backfill", backfill, "--pace", "3"),
                timeout=None if left is None else max(1, left - ITERATION_MIN),
            )
            if code not in (0, 2, 3):
                self.say(f"::warning::#{self.iteration} slow lane failed (code {code}), publishing prices only")
                slow = False
                self.slow_after = now + SLOW_LANE_BACKOFF
                code = self.run_visible(self.snapshot_argv())
        else:
            code = self.run_visible(self.snapshot_argv())
        if code == 0:
            code = 0 if self.run_visible([self.python, VERIFY, "dist"]) == 0 else 90
        return code, slow

    def assemble_site(self):
        log = []
        self.env.rmtree("site")
        scrub_assemble = ("GH_TOKEN", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES")
        scrub_verify = scrub_assemble + ("GHEYMAT_SIGNING_KEY",)
        steps = (
            ([self.python, ASSEMBLE, "--src", "dist", "--out", "site"], self.child_env(*scrub_assemble)),
            ([self.python, VERIFY, "--site", "site"], self.child_env(*scrub_verify)),
        )
        for argv, env in steps:
            code, output = self.env.run(argv, env=env, timeout=self.bounded(None))
            log.extend(output.splitlines())
            if code != 0:
                return False, log
        return True, log

    def deploy_cloudflare(self, now, build_seconds, ready, log):
        deployed = ready
        if ready:
            scrub_deploy = (
                "GH_TOKEN",
                "ANTHROPIC_API_KEY",
                "GHEYMAT_AI_SOURCES",
                "GHEYMAT_SIGNING_KEY",
                "GHEYMAT_PAYLOAD_KEY",
            )
            code, output = self.env.run(
                ["wrangler", "pages", "deploy", "site", "--project-name", CLOUDFLARE_PROJECT, "--branch", "master"],
                env=self.child_env(*scrub_deploy, WRANGLER_SEND_METRICS="false"),
                timeout=self.capped(300, DEPLOY_CAP),
            )
            log.extend(output.splitlines())
            deployed = code == 0
        if deployed:
            self.cf_failures = 0
            self.say(
                f"#{self.iteration} cloudflare {self.clock(self.env.now())} "
                f"(build {build_seconds}s, live {self.env.now() - now}s after detection)"
            )
        else:
            self.cf_failures += 1
            self.say(f"::warning::#{self.iteration} Cloudflare deploy failed ({self.cf_failures} in a row)")
            for line in log[-8:]:
                self.say("| " + line.replace("##[", "## ["))
        return deployed

    def get_sync(self):
        if self.sync is None:
            try:
                self.sync = self.sync_factory(environ=self.environ, log=self.say, include_v2=self.include_v2)
            except Exception as error:
                self.sync = None
                kind = getattr(error, "kind", None)
                kind = kind if kind in ("config", "connection") else "unknown"
                self.say(f"::warning::#{self.iteration} feed store setup failed ({kind})")
        return self.sync

    def sync_store(self, now, slow, ready):
        result = None
        if ready:
            sync = self.get_sync()
            if sync is not None:
                try:
                    result = sync.sync(Path("site"), slow)
                except Exception:
                    result = None
        stored = bool(result is not None and getattr(result, "hot_ok", False))
        kinds = getattr(result, "keys_failed_kinds", None)
        if isinstance(kinds, dict) and kinds:
            parts = [
                f"{kind} {count}"
                for kind, count in sorted(kinds.items(), key=lambda item: str(item[0]))
                if isinstance(kind, str) and KIND_PATTERN.fullmatch(kind) and isinstance(count, int)
            ]
            if parts:
                self.say(f"#{self.iteration} feed store failed keys: " + ", ".join(parts))
        if stored:
            self.say(f"#{self.iteration} store ok (live {self.env.now() - now}s after detection)")
        else:
            self.say(f"::warning::#{self.iteration} feed store hot documents not stored")
        return stored

    def publish_github(self, now):
        if now - self.last_gh < GITHUB_PUSH_SPACING:
            self.say(f"#{self.iteration} github push skipped (throttle)")
            return "skipped"
        if self.push_pages(f"Publish {self.iteration}"):
            self.failures = 0
            self.gh_failures = 0
            self.last_gh = now
            self.say(f"#{self.iteration} published {self.clock(self.env.now())}")
            return "ok"
        self.failures += 1
        self.gh_failures += 1
        if not self.push_timed_out:
            self.last_gh = 0
        if self.gh_failures == 2:
            self.want_fetch = True
        self.say_err(f"#{self.iteration} GitHub push failed ({self.failures} in a row)")
        return "failed"

    def refresh_news(self):
        left = self.time_left()
        if left is not None and left < NEWS_MIN_SECONDS:
            return
        code, output = self.env.run(
            self.snapshot_argv("--news-only"), env=self.child_env(), timeout=self.bounded(150)
        )
        if code != 0:
            self.say(f"::warning::#{self.iteration} news step exit {code}")
        if "news: refreshed" in output.splitlines():
            self.force = True
            self.force_slow = True
            self.say(f"#{self.iteration} news refreshed")

    def run_iteration(self, now, mark):
        self.iteration += 1
        self.force = False
        cf_ok = False
        store_ok = False
        gh_ok = False
        gh_skip = False
        failures_before = self.failures
        nothing_before = self.nothing
        if self.want_fetch:
            self.restore()
        self.clean = False
        code, slow = self.build(now)
        build_seconds = self.env.now() - now
        if code == 0:
            self.clean = True
            if slow:
                self.last_slow = now
                self.slow_ok_at = now
                self.slow_alarm = False
                self.fresh_restore = False
                self.force_slow = False
            pages_wanted = self.pages_mode == "every" or (self.pages_mode == "shell" and not self.pages_tried)
            if pages_wanted:
                self.pages_tried = True
            pages_run = pages_wanted and self.mirror
            ready = False
            log = []
            if pages_run or self.store_active():
                ready, log = self.assemble_site()
            if pages_run:
                cf_ok = self.deploy_cloudflare(now, build_seconds, ready, log)
            elif (
                pages_wanted
                and self.environ.get("CLOUDFLARE_API_TOKEN")
                and self.environ.get("CLOUDFLARE_ACCOUNT_ID")
            ):
                self.cf_failures += 1
                self.say(f"::warning::#{self.iteration} Cloudflare deploy unavailable ({self.cf_failures} in a row)")
            if self.store_active():
                store_ok = self.sync_store(now, slow, ready)
                if self.store_mode == "on":
                    self.store_failures = 0 if store_ok else self.store_failures + 1
            if pages_run or self.store_active():
                self.env.rmtree("site")
            outcome = self.publish_github(now)
            gh_ok = outcome == "ok"
            gh_skip = outcome == "skipped"
            self.env.rmtree("dist/.git")
        else:
            self.failures += 1
            if code != 2:
                self.have_dist = False
                self.want_fetch = True
            self.say_err(f"#{self.iteration} failed (code {code}, {self.failures} in a row)")
        store_ok = store_ok and self.store_mode == "on"
        published = store_ok or cf_ok or gh_ok
        if self.store_mode == "on":
            app_published = store_ok
        elif self.mirror and self.pages_mode == "every":
            app_published = cf_ok
        else:
            app_published = gh_ok
        self.fast_ok = app_published
        if published:
            self.nothing = 0
        elif code != 0 or not gh_skip:
            self.nothing += 1
        if app_published:
            self.last_mark = mark
            self.fast_retry = True
            self.grace = False
        else:
            if self.grace and not published:
                self.failures = failures_before
                self.nothing = nothing_before
            self.last_mark = mark
            if self.fast_retry:
                self.force = True
                self.fast_retry = False
                self.grace = True
            else:
                self.grace = False
        self.last_publish = now
        if code == 0 and not self.force:
            self.refresh_news()
        if not self.slow_alarm and self.env.now() - self.slow_ok_at > SLOW_LANE_ALARM:
            self.say("::error::The slow lane has not succeeded for 90 minutes")
            self.red = True
            self.slow_alarm = True
        if self.cf_failures == 0:
            self.alerted.discard(ALERT_PAGES)
        if self.store_failures == 0:
            self.alerted.discard(ALERT_STORE)
        if self.cf_failures == 5:
            self.say("::error::Cloudflare deploy failed 5 times in a row")
            self.red = True
        if self.cf_failures and self.cf_failures % 5 == 0 and self.store_mode != "on":
            self.alert(ALERT_PAGES, "The Cloudflare deploy has failed 5 times in a row. The app host serves the last good feed until it recovers.")
        if self.store_failures == 5:
            self.say("::error::Feed store failed 5 times in a row")
            self.red = True
        if self.store_failures and self.store_failures % 5 == 0 and self.store_mode == "on":
            self.alert(ALERT_STORE, "The feed store has failed 5 times in a row. The app host serves the last good feed until it recovers.")
        if self.failures == 5:
            self.say("::error::Restore, build or GitHub publish failed 5 times in a row")
            self.red = True
        if self.nothing >= 5:
            self.say("::error::Nothing could be published 5 times in a row")
            return False
        return True

    def flush(self):
        if not (self.clean and self.have_dist and self.last_gh < self.last_publish):
            return
        if self.env.now() - self.last_gh < GITHUB_PUSH_SPACING:
            return
        left = self.time_left()
        if left is not None and left < FLUSH_MIN:
            return
        verified = (
            self.env.run([self.python, VERIFY, "dist"], env=self.child_env(), timeout=self.bounded(None))[0] == 0
        )
        if verified and self.push_pages("Publish final"):
            self.last_gh = self.env.now()
        else:
            self.say("::warning::Final GitHub push failed")
        self.env.rmtree("dist/.git")

    def state_path(self):
        directory = self.environ.get("GHEYMAT_STATE_DIR", "")
        return f"{directory}/{STATE_FILE}" if directory else ""

    def load_state(self):
        path = self.state_path()
        if not path:
            return False
        try:
            state = json.loads(self.env.read_text(path))
            if not isinstance(state, dict):
                return False
            saved_at = state.get("saved_at")
            if isinstance(saved_at, bool) or not isinstance(saved_at, (int, float)):
                return False
            if not 0 <= (self.started or self.env.now()) - saved_at <= STATE_MAX_AGE:
                return False
            intact = (
                state.get("want_fetch") is False
                and state.get("have_dist") is True
                and self.env.exists("dist/d")
            )
        except Exception:
            return False
        now = self.env.now()
        for name in STATE_FIELDS:
            value = state.get(name)
            if type(value) is not type(getattr(self, name)):
                continue
            if name in STAMP_FIELDS and value > now:
                continue
            setattr(self, name, value)
        self.hot_until = max(0, min(self.hot_until, int(saved_at) + cadence.HOT_SECONDS))
        alerted = state.get("alerted")
        if isinstance(alerted, list) and all(isinstance(item, str) for item in alerted):
            self.alerted = set(alerted)
        self.seeded = True
        if intact:
            self.have_dist = True
            self.want_fetch = False
        else:
            self.have_dist = False
            self.want_fetch = True
            self.fresh_restore = True
        return True

    def save_state(self):
        path = self.state_path()
        if not path:
            return
        state = {name: getattr(self, name) for name in STATE_FIELDS}
        state["alerted"] = sorted(self.alerted)
        state["saved_at"] = self.env.now()
        try:
            self.env.mkdir(self.environ["GHEYMAT_STATE_DIR"])
            self.env.write_text(path, json.dumps(state))
        except Exception:
            if not self.save_warned:
                self.save_warned = True
                self.say("::warning::Loop state could not be saved")

    def serve(self):
        self.apply_knobs()
        carried = self.load_state()
        if not carried:
            self.env.remove(self.environ["GHEYMAT_LIVE_STATE"])
        minutes = self.environ.get("PUBLISH_LOOP_MINUTES", "")
        deadline = self.env.now() + (int(minutes) if DIGITS.fullmatch(minutes) else 3) * 60
        self.set_hard()
        if self.hard is not None:
            deadline = min(deadline, self.usable_end() - ITERATION_MIN)
        if not carried or not self.slow_ok_at:
            self.slow_ok_at = self.env.now()
        while self.env.now() < deadline:
            mark = self.poll()
            now = self.env.now()
            if not self.is_due(now, now - self.last_publish, mark):
                self.env.sleep(self.poll_gap(now, deadline, now - self.last_publish))
                continue
            ok = self.run_iteration(now, mark)
            if not ok:
                self.nothing = 0
            self.save_state()
            if not ok:
                return 2
        self.flush()
        self.save_state()
        return 1 if self.red else 0

    def chain(self):
        if self.environ.get("GITHUB_REF") != "refs/heads/master":
            return 0
        if self.env.now() - self.started < CHAIN_AFTER:
            self.say("Run ended early, not chaining another")
            return 0
        code, _ = self.env.run(
            ["gh", "workflow", "run", "gheymat-latest.yml", "--ref", "master"],
            env=self.child_env(*APP_SECRETS[1:], *CLOUDFLARE_SECRETS),
            timeout=None if self.hard is None else min(30, max(5, self.hard - self.env.now())),
        )
        return 0 if code == 0 else 1

    def run(self):
        if not self.start():
            return 1
        code = self.serve()
        if code == 2:
            return 1
        chained = self.chain()
        return 1 if code or chained else 0


def main():
    loop = Loop(Env(), os.environ, make_poll(), python=sys.executable)
    return loop.run()


if __name__ == "__main__":
    sys.exit(main())
