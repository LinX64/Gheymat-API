import datetime
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import cadence
import publish_loop as pl

T0 = 1_000_000
TOKEN = "tok-SECRET-123"
LIVE = "/state/live.json"
STORE_KEYS = ("FEED_STORE_KEY_ID", "FEED_STORE_SECRET", "FEED_STORE_BUCKET")


class FakeEnv:
    def __init__(self):
        self.t = T0
        self.calls = []
        self.lines = []
        self.errors = []
        self.sleeps = []
        self.files = {}
        self.removed = []
        self.rmtrees = []
        self.script = {}
        self.counts = {}
        self.durations = {}
        self.outputs = {}
        self.gh_commit_time = T0 - 100000
        self.jitter = 0
        self.rand_args = []
        self.missing = set()

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds

    def rand(self, low, high):
        self.rand_args.append((low, high))
        return max(low, min(high, self.jitter))

    def emit(self, line):
        self.lines.append(line)

    def emit_err(self, line):
        self.errors.append(line)

    def rmtree(self, path):
        self.rmtrees.append(path)

    def mkdir(self, path):
        pass

    def move(self, source, target):
        pass

    def touch(self, path):
        pass

    def exists(self, path):
        return path not in self.missing

    def write_text(self, path, text):
        self.files[path] = text

    def remove(self, path):
        self.removed.append(path)

    def clear_top(self, path, keep):
        pass

    def read_text(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def kind(self, argv):
        if argv[0] == "git":
            if "fetch" in argv:
                return "fetch"
            if "checkout" in argv and "--work-tree=restore" in argv:
                return "checkout"
            if "log" in argv:
                return "gitlog"
            if "push" in argv:
                return "push"
            return "git"
        if argv[0] == "wrangler":
            return "create" if "create" in argv else "deploy"
        if argv[0] == "npm":
            return "npm"
        if argv[0] == "gh":
            if "issue" in argv:
                return "issue_list" if "list" in argv else "issue_create"
            return "gh"
        script = argv[1]
        if script.endswith("assemble_site.py"):
            return "assemble"
        if script.endswith("verify_sealed.py"):
            return "verify_site" if "--site" in argv else "verify"
        if "--news-only" in argv:
            return "news"
        return "slow" if "--history" in argv else "prices"

    def run(self, argv, env=None, timeout=None, cwd=None):
        kind = self.kind(argv)
        self.counts[kind] = self.counts.get(kind, 0) + 1
        rule = self.script.get(kind, 0)
        code = rule(self.counts[kind]) if callable(rule) else rule
        self.calls.append((kind, list(argv), env, timeout, cwd, self.t, code))
        self.t += self.durations.get(kind, 0)
        output = self.outputs.get(kind, "")
        if kind == "gitlog":
            output = f"{self.gh_commit_time}\n"
        if callable(output):
            output = output(self.counts[kind])
        return code, output

    def times(self, kind):
        return [call[5] for call in self.calls if call[0] == kind]

    def gaps(self, kind):
        stamps = self.times(kind)
        return [b - a for a, b in zip(stamps, stamps[1:])]

    def kinds(self):
        return [call[0] for call in self.calls]

    def envs(self, kind):
        return [call[2] for call in self.calls if call[0] == kind]


def base_environ(**extra):
    environ = {
        "GH_TOKEN": TOKEN,
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_REF": "refs/heads/master",
        "FLOOR_SECONDS": "90",
        "GHEYMAT_LIVE_STATE": LIVE,
        "GHEYMAT_ORDER": "default",
        "GHEYMAT_LIVE_FIRST_FROM": "",
        "BACKFILL": "12",
        "PUBLISH_LOOP_MINUTES": "30",
        "ANTHROPIC_API_KEY": "ak",
        "GHEYMAT_AI_SOURCES": "src",
        "GHEYMAT_SIGNING_KEY": "sk",
        "GHEYMAT_PAYLOAD_KEY": "pk",
        "CLOUDFLARE_API_TOKEN": "cft",
        "CLOUDFLARE_ACCOUNT_ID": "cfa",
        "FEED_STORE_KEY_ID": "ksk-id",
        "FEED_STORE_SECRET": "ksk-secret",
        "FEED_STORE_BUCKET": "ksk-bucket",
    }
    environ.update(extra)
    return environ


def make(minutes=30, mirror=True, marks=None, **extra):
    env = FakeEnv()
    environ = base_environ(PUBLISH_LOOP_MINUTES=str(minutes), **extra)
    poll = (lambda: marks(env.t)) if marks else (lambda: "m")
    loop = pl.Loop(env, environ, poll, python="python", mirror=mirror)
    return loop, env


def serve(minutes=30, **kwargs):
    loop, env = make(minutes, **kwargs)
    return loop, env, loop.serve()


def test_default_cadence_and_mark_change():
    loop, env, code = serve(30, mirror=True)
    assert code == 0
    builds = env.times("prices") + env.times("slow")
    builds.sort()
    assert len(builds) >= 9
    assert all(180 <= gap <= 195 for gap in zip_gaps(builds))
    def marks(t):
        return "a" if t < T0 + 400 else "b"

    loop, env, _ = serve(10, mirror=True, marks=marks)
    stamps = sorted(env.times("prices") + env.times("slow"))
    assert any(45 <= gap < 180 for gap in zip_gaps(stamps))


def zip_gaps(values):
    return [b - a for a, b in zip(values, values[1:])]


def test_live_first_cadence_with_floor_and_jitter():
    loop, env = make(30, GHEYMAT_ORDER="live-first")
    env.jitter = 15
    loop.serve()
    stamps = sorted(env.times("prices") + env.times("slow"))
    gaps = zip_gaps(stamps)
    assert gaps and all(90 <= gap <= 120 for gap in gaps)
    assert set(env.rand_args) == {(-15, 15)}
    loop, env = make(30, GHEYMAT_ORDER="live-first")
    env.jitter = -15
    loop.serve()
    gaps = zip_gaps(sorted(env.times("prices") + env.times("slow")))
    assert gaps and all(75 <= gap <= 105 for gap in gaps)
    assert min(gaps) >= 75


def test_live_first_floor_clamped():
    loop, env = make(10, GHEYMAT_ORDER="live-first", FLOOR_SECONDS="5")
    loop.serve()
    assert loop.floor_seconds == 90
    loop, env = make(10, GHEYMAT_ORDER="live-first", FLOOR_SECONDS="5000")
    loop.serve()
    assert loop.floor_seconds == 900


def test_live_first_from_date_switches_on():
    when = "2001-09-09T01:50:00Z"
    loop, env = make(10, GHEYMAT_LIVE_FIRST_FROM=when)
    assert loop.live_first_start() == 1_000_000_200
    assert loop.is_live_first(loop.live_first_start()) is True
    assert loop.is_live_first(loop.live_first_start() - 1) is False


def test_quiet_state_falls_back_to_180():
    loop, env = make(30, GHEYMAT_ORDER="live-first")
    env.files[LIVE] = json.dumps({"quiet_until": T0 + 10**6})
    loop.serve()
    gaps = zip_gaps(sorted(env.times("prices") + env.times("slow")))
    assert gaps and all(180 <= gap <= 195 for gap in gaps)


def test_quiet_until_bad_state_is_zero():
    loop, env = make(1)
    for text in ("not json", json.dumps([1]), json.dumps({"quiet_until": None}), json.dumps({"quiet_until": -3}),
                 json.dumps({"quiet_until": "x"})):
        env.files[LIVE] = text
        assert loop.quiet_until() == 0
    env.files[LIVE] = json.dumps({"quiet_until": 12.9})
    assert loop.quiet_until() == 12
    del env.files[LIVE]
    assert loop.quiet_until() == 0


def test_live_state_removed_at_start():
    loop, env, _ = serve(1)
    assert env.removed == [LIVE]


def test_live_state_kept_on_warm_start_removed_on_cold_start():
    env = FakeEnv()
    run_loop(env, GHEYMAT_STATE_DIR=STATE).serve()
    assert env.removed == [LIVE]
    run_loop(env, GHEYMAT_STATE_DIR=STATE).serve()
    assert env.removed == [LIVE]
    env.t += pl.STATE_MAX_AGE + 1
    run_loop(env, GHEYMAT_STATE_DIR=STATE).serve()
    assert env.removed == [LIVE, LIVE]


def test_throttle_keeps_pushes_apart():
    loop, env, code = serve(60)
    assert code == 0
    gaps = env.gaps("push")
    assert gaps and all(gap >= 400 for gap in gaps)
    assert any("github push skipped (throttle)" in line for line in env.lines)


def test_throttle_seeds_from_gh_pages_commit_time():
    loop, env = make(10)
    env.gh_commit_time = T0 - 50
    loop.serve()
    assert env.times("push")[0] - 0 >= T0 + 350
    assert any("#1 github push skipped (throttle)" == line for line in env.lines)
    assert loop.last_gh >= T0 + 350


def test_no_mirror_waits_for_github_window():
    loop, env = make(30, mirror=False)
    env.gh_commit_time = T0 - 50
    loop.serve()
    assert sorted(env.times("prices") + env.times("slow"))[1] >= T0 + 350
    assert "assemble" not in env.kinds()


def test_first_build_is_slow_lane_then_prices_only():
    loop, env = make(30)
    loop.serve()
    builds = [c[0] for c in env.calls if c[0] in ("slow", "prices")]
    assert builds[0] == "slow"
    assert builds[1] == "prices"
    slow_argv = next(c[1] for c in env.calls if c[0] == "slow")
    assert "--defer-news" in slow_argv and slow_argv[slow_argv.index("--pace") + 1] == "3"
    assert slow_argv[slow_argv.index("--backfill") + 1] == "12"


def test_backfill_40():
    loop, env = make(5, BACKFILL="40")
    loop.serve()
    slow_argv = next(c[1] for c in env.calls if c[0] == "slow")
    assert slow_argv[slow_argv.index("--backfill") + 1] == "40"


def test_slow_lane_only_when_due():
    loop, env = make(100)
    loop.serve()
    slow = env.times("slow")
    assert slow[0] == T0
    assert all(gap >= 1800 for gap in zip_gaps(slow))
    assert len(slow) >= 3


def test_fresh_restore_forces_slow_lane():
    loop, env = make(60)
    env.script["push"] = lambda n: 1 if n <= 2 else 0
    loop.serve()
    assert env.counts["fetch"] >= 2
    slow = env.times("slow")
    assert len(slow) >= 2 and slow[1] - slow[0] < 1800


def test_failing_slow_lane_falls_back_and_backs_off():
    loop, env = make(30)
    env.script["slow"] = 5
    loop.serve()
    assert any("slow lane failed (code 5), publishing prices only" in line for line in env.lines)
    assert env.times("slow")[0] == T0
    assert env.counts["prices"] >= 2
    assert env.kinds()[env.kinds().index("slow") + 1] == "prices"
    assert all(gap >= 600 for gap in zip_gaps(env.times("slow")))


def test_slow_lane_retried_after_backoff():
    loop, env = make(40)
    env.script["slow"] = 5
    loop.serve()
    slow = env.times("slow")
    assert len(slow) >= 2 and slow[1] - slow[0] >= 600


def test_slow_lane_alarm_turns_red():
    loop, env = make(120)
    env.script["slow"] = 5
    code = loop.serve()
    assert code == 1
    assert loop.red and loop.slow_alarm
    assert sum("slow lane has not succeeded for 90 minutes" in line for line in env.lines) == 1


def test_push_failure_never_stops_deploys():
    loop, env = make(20)
    env.script["push"] = 1
    loop.serve()
    assert env.counts["deploy"] >= 5
    assert loop.nothing == 0
    assert any("GitHub push failed" in line for line in env.errors)


def test_deploy_failure_never_stops_legacy_push():
    loop, env = make(30)
    env.script["deploy"] = 1
    env.outputs["deploy"] = "##[error] boom\nline2"
    loop.serve()
    assert env.counts["push"] >= 2
    assert any("Cloudflare deploy failed (1 in a row)" in line for line in env.lines)
    assert "| ## [error] boom" in env.lines


def test_five_cloudflare_failures_red_but_run_continues():
    loop, env = make(60)
    env.script["deploy"] = 1
    code = loop.serve()
    assert code == 1
    assert any("Cloudflare deploy failed 5 times in a row" in line for line in env.lines)
    assert env.times("prices")[-1] > env.times("prices")[4]


def test_exit_three_ends_after_five():
    loop, env = make(120)
    env.script["prices"] = 3
    env.script["slow"] = 3
    code = loop.serve()
    assert code == 2
    assert loop.nothing == 0
    assert any("Nothing could be published 5 times in a row" in line for line in env.lines)
    assert env.counts["slow"] + env.counts.get("prices", 0) == 6


def test_exit_two_keeps_state_exit_three_drops_it():
    loop, env = make(4)
    env.script["slow"] = 2
    loop.serve()
    assert loop.have_dist is True
    assert env.counts["fetch"] == 1
    loop, env = make(4)
    env.script["slow"] = 3
    loop.serve()
    assert env.counts["fetch"] >= 2


def test_fetch_failure_keeps_last_verified_build():
    loop, env = make(40)
    env.script["push"] = 1
    env.script["fetch"] = lambda n: 0 if n == 1 else 1
    loop.serve()
    assert env.counts["fetch"] >= 2
    assert loop.have_dist is True
    assert env.counts["prices"] + env.counts["slow"] >= 5


def test_first_fetch_failure_means_no_build_code_91():
    loop, env = make(2)
    env.script["fetch"] = 1
    loop.serve()
    assert any("failed (code 91" in line for line in env.errors)
    assert "prices" not in env.kinds() and "slow" not in env.kinds()


def test_second_push_failure_forces_refetch():
    loop, env = make(30)
    env.script["push"] = lambda n: 1 if n <= 2 else 0
    loop.serve()
    assert env.counts["fetch"] == 2
    kinds = env.kinds()
    fetches = [i for i, k in enumerate(kinds) if k == "fetch"]
    pushes = [i for i, k in enumerate(kinds) if k == "push"]
    assert pushes[0] < pushes[1] < fetches[1]


def test_quick_retry_after_one_unpublished_iteration_and_limits():
    loop, env = make(60)
    env.script["prices"] = 3
    env.script["slow"] = 3
    loop.serve()
    stamps = sorted(env.times("prices") + env.times("slow"))
    assert 45 <= stamps[1] - stamps[0] < 60
    assert loop.nothing == 0
    assert len(stamps) == 6


def test_quick_retry_not_counted_towards_limit():
    loop, env = make(60)
    env.script["prices"] = lambda n: 0 if n % 2 else 3
    loop.serve()
    assert loop.failures < 5


def test_news_refresh_forces_next_build_and_slow_lane():
    loop, env = make(10)
    env.outputs["news"] = lambda n: "news: refreshed\n" if n == 1 else "news: unchanged\n"
    loop.serve()
    assert any(line == "#1 news refreshed" for line in env.lines)
    builds = [c for c in env.calls if c[0] in ("slow", "prices")]
    assert builds[1][0] == "slow"
    assert 45 <= builds[1][5] - builds[0][5] < 60


def test_news_failure_warns():
    loop, env = make(2)
    env.script["news"] = 124
    loop.serve()
    assert any("::warning::#1 news step exit 124" == line for line in env.lines)


def ready_to_flush(last_gh):
    loop, env = make(1)
    loop.clean = True
    loop.have_dist = True
    loop.last_publish = env.t
    loop.last_gh = last_gh
    return loop, env


def test_final_flush_verifies_first_and_pushes_once():
    loop, env = ready_to_flush(T0 - pl.GITHUB_PUSH_SPACING)
    loop.flush()
    kinds = env.kinds()
    commits_final = [c for c in env.calls if c[0] == "git" and "Publish final" in c[1]]
    assert len(commits_final) == 1
    assert kinds.index("verify") < kinds.index("push")
    assert loop.last_gh == T0


def test_final_flush_skipped_when_level():
    loop, env = make(1)
    loop.serve()
    assert not any("Publish final" in c[1] for c in env.calls if c[0] == "git")


def test_final_flush_failure_warns():
    loop, env = ready_to_flush(0)
    env.script["push"] = 1
    loop.flush()
    assert "::warning::Final GitHub push failed" in env.lines
    assert loop.last_gh == 0


def test_flush_respects_the_push_throttle():
    loop, env = ready_to_flush(T0 - pl.GITHUB_PUSH_SPACING + 1)
    loop.flush()
    assert env.calls == []
    env.t += 1
    loop.flush()
    assert env.counts["push"] == 1


def test_knob_warnings():
    loop, env = make(1, FLOOR_SECONDS="abc", GHEYMAT_ORDER="weird", GHEYMAT_LIVE_FIRST_FROM="yesterday")
    loop.serve()
    assert "::warning::FLOOR_SECONDS is not a number, using 90" in env.lines
    assert "::warning::unknown order, using default" in env.lines
    assert loop.environ["GHEYMAT_ORDER"] == "default"
    assert env.lines.count("::warning::GHEYMAT_LIVE_FIRST_FROM is not YYYY-MM-DDTHH:MM:SSZ, ignored") == 1


def test_bad_date_warned_once_over_many_iterations():
    loop, env = make(20, GHEYMAT_LIVE_FIRST_FROM="2026-13-45T00:00:00Z")
    loop.serve()
    assert not any("not YYYY" in line for line in env.lines)
    loop, env = make(20, GHEYMAT_LIVE_FIRST_FROM="bad")
    loop.serve()
    assert sum("not YYYY" in line for line in env.lines) == 1


def test_startup_key_check_exits_1():
    for missing in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY"):
        env = FakeEnv()
        environ = base_environ()
        environ[missing] = ""
        loop = pl.Loop(env, environ, lambda: "", python="python")
        assert loop.run() == 1
        assert env.errors == ["GHEYMAT_PAYLOAD_KEY / GHEYMAT_SIGNING_KEY secrets are not set"]
        assert env.calls == []


def test_wrangler_setup_success():
    env = FakeEnv()
    loop = pl.Loop(env, base_environ(PUBLISH_LOOP_MINUTES="0"), lambda: "", python="python")
    assert loop.start() is True
    assert loop.mirror is True
    npm = [c for c in env.calls if c[0] == "npm"]
    assert len(npm) == 1 and npm[0][1][-1] == "wrangler@4.159.0" and npm[0][3] == 300
    for key in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GH_TOKEN", "GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES", *STORE_KEYS):
        assert key not in npm[0][2]
    create = [c for c in env.calls if c[0] == "create"][0]
    assert create[1][-5:] == ["project", "create", "gheymat-feed", "--production-branch", "master"]
    assert create[2]["WRANGLER_SEND_METRICS"] == "false" and create[3] == 120
    for key in ("GH_TOKEN", "GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES", *STORE_KEYS):
        assert key not in create[2]
    assert create[2]["CLOUDFLARE_API_TOKEN"] == "cft" and create[2]["CLOUDFLARE_ACCOUNT_ID"] == "cfa"


def test_wrangler_retries_then_succeeds():
    env = FakeEnv()
    env.script["npm"] = lambda n: 1 if n < 3 else 0
    loop = pl.Loop(env, base_environ(), lambda: "", python="python")
    loop.start()
    assert env.counts["npm"] == 3
    assert env.sleeps == [10, 20]
    assert loop.mirror is True


def test_wrangler_off_after_three_failures():
    env = FakeEnv()
    env.script["npm"] = 1
    env.script["create"] = 1
    loop = pl.Loop(env, base_environ(), lambda: "", python="python")
    loop.start()
    assert env.counts["npm"] == 3 and "create" not in env.counts
    assert env.sleeps == [10, 20]
    assert loop.mirror is False
    assert "::error::Cloudflare deploy is off: Wrangler install failed 3 times" in env.lines


def test_wrangler_off_without_secrets():
    env = FakeEnv()
    environ = base_environ()
    del environ["CLOUDFLARE_API_TOKEN"]
    loop = pl.Loop(env, environ, lambda: "", python="python", mirror=True)
    loop.start()
    assert loop.mirror is False
    assert env.counts.get("npm", 0) == 0
    assert "::warning::Cloudflare deploy is off: repository secrets are missing" in env.lines


def test_failed_project_create_is_ignored():
    env = FakeEnv()
    env.script["create"] = 1
    loop = pl.Loop(env, base_environ(), lambda: "", python="python")
    loop.start()
    assert loop.mirror is True


def finish(ref, elapsed):
    env = FakeEnv()
    loop = pl.Loop(env, base_environ(GITHUB_REF=ref), lambda: "", python="python")
    loop.started = env.t - elapsed
    return loop, env, loop.chain()


def test_chain_on_master_after_the_threshold():
    loop, env, code = finish("refs/heads/master", pl.CHAIN_AFTER)
    assert code == 0
    call = env.calls[0]
    assert call[1] == ["gh", "workflow", "run", "gheymat-latest.yml", "--ref", "master"]
    assert call[2]["GH_TOKEN"] == TOKEN
    for key in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", *STORE_KEYS):
        assert key not in call[2]


def test_no_chain_under_the_threshold():
    loop, env, code = finish("refs/heads/master", pl.CHAIN_AFTER - 1)
    assert code == 0 and env.calls == []
    assert "Run ended early, not chaining another" in env.lines


def test_no_chain_off_master():
    loop, env, code = finish("refs/heads/develop", 99999)
    assert code == 0 and env.calls == []


def test_run_chains_but_returns_one_when_red():
    loop, env = make(120)
    env.script["slow"] = 5
    assert loop.run() == 1
    assert env.counts["gh"] == 1


def test_run_goes_red_but_still_chains_when_nothing_published():
    loop, env = make(120)
    env.script["prices"] = 3
    env.script["slow"] = 3
    assert loop.run() == 1
    assert env.counts["gh"] == 1


def test_run_chains_after_full_clean_run():
    loop, env = make(360, mirror=False)
    assert loop.run() == 0
    assert env.counts["gh"] == 1


def test_deploy_env_is_scrubbed():
    loop, env = make(3)
    loop.serve()
    deploy = env.envs("deploy")[0]
    for key in ("GH_TOKEN", "GHEYMAT_SIGNING_KEY", "GHEYMAT_PAYLOAD_KEY", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES", *STORE_KEYS):
        assert key not in deploy
    assert deploy["WRANGLER_SEND_METRICS"] == "false"
    assert deploy["CLOUDFLARE_API_TOKEN"] == "cft"
    assemble = env.envs("assemble")[0]
    for key in ("GH_TOKEN", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES"):
        assert key not in assemble
    assert assemble["GHEYMAT_SIGNING_KEY"] == "sk"
    verify_site = env.envs("verify_site")[0]
    assert "GHEYMAT_SIGNING_KEY" not in verify_site and "GH_TOKEN" not in verify_site
    assert env.envs("slow")[0]["GH_TOKEN"] == TOKEN
    for kind in ("slow", "assemble", "verify_site", "deploy"):
        for child in env.envs(kind):
            assert not any(key in child for key in STORE_KEYS)


def test_token_never_emitted():
    loop, env = make(40)
    env.script["push"] = lambda n: 1 if n % 2 else 0
    env.script["deploy"] = 1
    env.outputs["deploy"] = f"leak {TOKEN}"
    loop.serve()
    assert env.lines and env.errors
    assert not any(TOKEN in line for line in env.lines + env.errors)


def test_push_uses_bot_identity_and_token_url():
    loop, env = make(2)
    loop.serve()
    push = next(c for c in env.calls if c[0] == "push")
    assert push[1][-2] == f"https://x-access-token:{TOKEN}@github.com/o/r.git"
    assert push[4] == "dist" and push[3] == 120
    commit = next(c for c in env.calls if c[0] == "git" and "commit" in c[1])
    assert "user.name=github-actions[bot]" in commit[1]


def test_cloudflare_unavailable_counts_when_mirror_off():
    loop, env = make(5, mirror=False)
    env.gh_commit_time = T0 - 10000
    loop.serve()
    assert any("Cloudflare deploy unavailable (1 in a row)" in line for line in env.lines)


def test_message_formats():
    loop, env = make(2)
    env.durations["slow"] = 7
    loop.serve()
    assert any(line.startswith("#1 cloudflare ") and "(build 7s, live 7s after detection)" in line
               for line in env.lines)
    assert any(line.startswith("#1 published ") and line.endswith("Z") for line in env.lines)


def deploy_gaps(env):
    return zip_gaps([call[5] for call in env.calls if call[0] == "deploy" and call[6] == 0])


def assert_under_five_minutes(env, minimum=5):
    gaps = deploy_gaps(env)
    assert len(gaps) >= minimum
    assert max(gaps) <= 300


def test_source_to_live_under_5_minutes_default_heartbeat():
    loop, env = make(120)
    loop.serve()
    assert_under_five_minutes(env, 20)


def test_source_to_live_under_5_minutes_live_first():
    loop, env = make(120, GHEYMAT_ORDER="live-first")
    env.jitter = 15
    loop.serve()
    assert_under_five_minutes(env, 40)


def test_source_to_live_under_5_minutes_live_first_quiet_state():
    loop, env = make(120, GHEYMAT_ORDER="live-first")
    env.files[LIVE] = json.dumps({"quiet_until": T0 + 10**6})
    loop.serve()
    assert_under_five_minutes(env, 20)


def test_source_to_live_under_5_minutes_after_failed_build():
    loop, env = make(120, GHEYMAT_ORDER="live-first")
    env.script["prices"] = lambda n: 1 if n == 3 else 0
    loop.serve()
    assert_under_five_minutes(env, 40)
    assert env.counts["prices"] > 3


def test_source_to_live_under_5_minutes_after_failed_deploy():
    loop, env = make(120)
    env.script["deploy"] = lambda n: 1 if n == 4 else 0
    loop.serve()
    gaps = deploy_gaps(env)
    assert len(gaps) >= 20
    assert max(gaps) <= 300


def test_source_to_live_under_5_minutes_while_github_throttled_or_failing():
    loop, env = make(120)
    env.script["push"] = 1
    loop.serve()
    assert_under_five_minutes(env, 20)
    loop, env = make(120)
    env.gh_commit_time = T0
    loop.serve()
    assert_under_five_minutes(env, 20)


def test_source_to_live_after_new_mark_within_build_plus_deploy_plus_poll():
    build = 40
    deploy = 25

    def marks(t):
        return "old" if t < T0 + 1000 else "new"

    loop, env = make(30, marks=marks)
    env.durations["prices"] = build
    env.durations["slow"] = build
    env.durations["deploy"] = deploy
    loop.serve()
    changed = [c for c in env.calls if c[0] in ("prices", "slow") and c[5] >= T0 + 1000]
    first = changed[0]
    deploys = [c[5] + deploy for c in env.calls if c[0] == "deploy" and c[5] >= first[5]]
    noticed = T0 + 1000
    assert first[5] - noticed <= 15 + 45 + 15
    assert deploys[0] - first[5] <= build + deploy + 15


def test_news_waits_while_a_quick_retry_is_pending():
    loop, env = make(30)
    env.script["deploy"] = lambda n: 1 if n == 3 else 0
    loop.serve()
    kinds = env.kinds()
    failed_at = [i for i, call in enumerate(env.calls) if call[0] == "deploy" and call[6] == 1][0]
    after = kinds[failed_at + 1:]
    next_build = min(after.index(kind) for kind in ("prices", "slow") if kind in after)
    assert "news" not in after[:next_build]


def test_five_cloudflare_failures_open_one_issue():
    loop, env = make(60)
    env.script["deploy"] = 1
    loop.serve()
    assert env.counts["issue_list"] == 1
    assert env.counts["issue_create"] == 1
    created = [call for call in env.calls if call[0] == "issue_create"][0]
    assert pl.ALERT_PAGES in created[1]
    for name in (*pl.APP_SECRETS[1:], *pl.CLOUDFLARE_SECRETS):
        assert name not in created[2]
    assert created[2]["GH_REPO"] == "o/r"
    assert created[2]["GH_TOKEN"] == TOKEN


def test_an_open_issue_is_not_duplicated():
    loop, env = make(60)
    env.script["deploy"] = 1
    env.outputs["issue_list"] = pl.ALERT_PAGES + "\n"
    loop.serve()
    assert env.counts["issue_list"] == 1
    assert env.counts.get("issue_create", 0) == 0


def test_a_recovered_deploy_can_alert_again():
    loop, env = make(120)
    env.script["deploy"] = lambda n: 0 if n in (8, 9) else 1
    loop.serve()
    assert env.counts["issue_create"] == 2


def test_a_healthy_run_opens_no_issue():
    loop, env = make(30)
    loop.serve()
    assert env.counts.get("issue_list", 0) == 0
    assert env.counts.get("issue_create", 0) == 0


def test_a_failed_alert_warns_and_retries_later():
    loop, env = make(60)
    env.script["deploy"] = 1
    env.script["issue_create"] = lambda n: 1 if n == 1 else 0
    loop.serve()
    assert env.counts["issue_create"] == 2
    assert any("alert issue could not be opened (code 1)" in line for line in env.lines)
    assert env.counts["deploy"] > 10


STATE = "/state"


def run_loop(env, minutes=3, **extra):
    environ = base_environ(PUBLISH_LOOP_MINUTES=str(minutes), **extra)
    return pl.Loop(env, environ, lambda: "m", python="python", mirror=True)


def state_environ(**extra):
    return dict(GHEYMAT_STATE_DIR=STATE, **extra)


def saved(env):
    return json.loads(env.files[f"{STATE}/{pl.STATE_FILE}"])


def test_consecutive_runs_continue_one_loop():
    env = FakeEnv()
    first = run_loop(env, **state_environ())
    assert first.serve() == 0
    fetches = env.counts["fetch"]
    slows = env.counts["slow"]
    assert fetches == 1 and slows == 1
    last = first.iteration
    second = run_loop(env, **state_environ())
    assert second.serve() == 0
    assert env.counts["fetch"] == fetches
    assert env.counts.get("checkout", 0) == 1
    assert env.counts["slow"] == slows
    assert env.removed == [LIVE]
    assert second.iteration > last
    assert f"#{last + 1} cloudflare" in " ".join(env.lines)


def cold_start_cases():
    stale = {"saved_at": T0 - pl.STATE_MAX_AGE - 1}
    return {
        "stale": json.dumps(stale),
        "corrupt": "{not json",
        "list": "[1, 2]",
        "bad_saved_at": json.dumps({"saved_at": "now"}),
        "future": json.dumps({"saved_at": T0 + 50}),
    }


@pytest.mark.parametrize("case", ["stale", "corrupt", "list", "bad_saved_at", "future", "no_dist"])
def test_unusable_state_falls_back_to_cold_start(case):
    env = FakeEnv()
    if case == "no_dist":
        env.files[f"{STATE}/{pl.STATE_FILE}"] = json.dumps(
            {"saved_at": T0, "have_dist": True, "want_fetch": False, "iteration": 7}
        )
        env.missing = {"dist/d"}
    else:
        env.files[f"{STATE}/{pl.STATE_FILE}"] = cold_start_cases()[case]
    loop = run_loop(env, **state_environ())
    loop.serve()
    assert env.counts["fetch"] == 1
    assert env.removed == ([] if case == "no_dist" else [LIVE])
    assert (loop.iteration > 7) == (case == "no_dist")


def test_wrong_field_types_keep_defaults_but_state_is_used():
    env = FakeEnv()
    env.files[f"{STATE}/{pl.STATE_FILE}"] = json.dumps(
        {"saved_at": T0, "have_dist": True, "want_fetch": False, "iteration": "x", "cf_failures": True, "last_gh": T0 + 500, "alerted": [1], "failures": 2}
    )
    loop = run_loop(env, **state_environ())
    loop.apply_knobs()
    assert loop.load_state() is True
    assert loop.iteration == 0 and loop.cf_failures == 0 and loop.last_gh == 0
    assert loop.alerted == set() and loop.failures == 2
    assert loop.want_fetch is False and loop.have_dist is True


def test_cloudflare_failing_across_runs_alarms_once():
    env = FakeEnv()
    env.script["deploy"] = 1
    codes = []
    for _ in range(6):
        loop = run_loop(env, GITHUB_REF="refs/heads/master", **state_environ())
        codes.append(loop.run())
    errors = [line for line in env.lines if "Cloudflare deploy failed 5 times in a row" in line]
    assert len(errors) == 1
    assert codes.count(1) == 1
    assert env.counts["gh"] == 6


def test_four_runs_push_pages_no_more_often_than_the_spacing():
    env = FakeEnv()
    for _ in range(4):
        run_loop(env, **state_environ()).run()
    stamps = env.times("push")
    assert stamps
    assert all(gap >= pl.GITHUB_PUSH_SPACING for gap in zip_gaps(stamps))


def test_nothing_across_runs_goes_red_still_chains_and_saves_zero():
    env = FakeEnv()
    first = run_loop(env, GITHUB_REF="refs/heads/master", **state_environ())
    first.nothing = 4
    first.have_dist = True
    first.want_fetch = False
    first.save_state()
    env.script["prices"] = 3
    env.script["slow"] = 3
    loop = run_loop(env, GITHUB_REF="refs/heads/master", **state_environ())
    assert loop.run() == 1
    assert env.counts["gh"] == 1
    assert saved(env)["nothing"] == 0


def test_state_save_failure_warns_once_and_loop_continues():
    class Broken(FakeEnv):
        def write_text(self, path, text):
            raise OSError("disk")

    env = Broken()
    loop = run_loop(env, 10, **state_environ())
    assert loop.serve() == 0
    assert env.counts["prices"] + env.counts["slow"] >= 3
    assert env.lines.count("::warning::Loop state could not be saved") == 1


def test_no_state_dir_loads_and_saves_nothing():
    env = FakeEnv()
    run_loop(env).serve()
    assert env.files == {}


def test_three_minute_run_publishes_at_default_cadence():
    env = FakeEnv()
    run_loop(env, 3).serve()
    assert env.counts["deploy"] >= 1


def test_three_minute_run_publishes_twice_live_first():
    env = FakeEnv()
    run_loop(env, 3, GHEYMAT_ORDER="live-first").serve()
    assert env.counts["deploy"] >= 2


class TimedEnv(FakeEnv):
    def __init__(self):
        super().__init__()
        self.ends = []

    def run(self, argv, env=None, timeout=None, cwd=None):
        kind = self.kind(argv)
        wanted = self.durations.get(kind, 2)
        start = self.t
        code, output = super().run(argv, env=env, timeout=timeout, cwd=cwd)
        if timeout is not None and wanted > timeout:
            wanted = timeout
            code, output = 124, ""
        self.t = start + wanted
        self.ends.append(self.t)
        return code, output


HARD = {"PUBLISH_HARD_SECONDS": "230"}


@pytest.mark.parametrize(
    "durations",
    [
        {"deploy": 10},
        {"deploy": 10_000},
        {"slow": 60},
        {"slow": 60, "deploy": 10_000, "prices": 40, "push": 3},
        {"fetch": 10_000},
        {"news": 10_000, "prices": 30},
    ],
)
def test_hard_budget_bounds_the_run(durations):
    env = TimedEnv()
    env.durations = durations
    loop = run_loop(env, 3, **HARD)
    loop.serve()
    hard = T0 + 230
    assert max(env.ends) <= hard
    for call in env.calls:
        assert call[3] is not None
        assert call[3] <= max(1, hard - call[5])


def test_hanging_install_cannot_pass_the_hard_limit():
    env = TimedEnv()
    env.durations = {"npm": 10_000}
    env.script["npm"] = 1
    loop = run_loop(env, 3, **HARD)
    assert loop.start() is True
    assert loop.mirror is False
    hard = env.times("npm")[0] + 230
    assert max(env.ends) <= hard
    for call in env.calls:
        assert call[3] is not None and call[3] <= max(1, hard - call[5])


def test_install_retries_stop_when_the_budget_is_short():
    env = TimedEnv()
    env.script["npm"] = 1
    loop = run_loop(env, 3, PUBLISH_HARD_SECONDS="70")
    loop.start()
    assert env.counts["npm"] < 3
    assert loop.mirror is False


def test_chain_has_a_fixed_timeout_when_budgeted():
    loop, env = make(3, **HARD)
    loop.start()
    loop.started = env.t - pl.CHAIN_AFTER
    loop.chain()
    assert [c for c in env.calls if c[0] == "gh"][0][3] == 30


def test_news_and_slow_lane_respect_the_remaining_budget():
    env = TimedEnv()
    env.durations = {"prices": 60}
    loop = run_loop(env, 3, PUBLISH_HARD_SECONDS="140")
    loop.serve()
    assert env.counts.get("slow", 0) == 0 and env.counts["prices"] >= 1
    assert "news" not in env.kinds()
    assert loop.last_slow == 0


@pytest.mark.parametrize("hung", ["npm", "create", "slow", "prices", "deploy", "push", "news", "fetch", "verify"])
@pytest.mark.parametrize("fails_first", [False, True])
def test_run_ends_inside_the_hard_budget_whichever_command_hangs(hung, fails_first):
    env = TimedEnv()
    env.durations = {hung: 100_000}
    if fails_first and hung == "prices":
        env.script["slow"] = 1
    if hung == "npm":
        env.script["npm"] = 1
    loop = run_loop(env, 3, GITHUB_REF="refs/heads/master", **HARD)
    started = env.t
    loop.run()
    assert env.now() <= started + 230
    for call in env.calls:
        assert call[3] is not None
        assert call[5] + call[3] <= started + 230 + 1


def refetch_cases():
    return {
        "exit_three": lambda env: env.script.update(prices=3, slow=3),
        "verify_failed": lambda env: env.script.update(verify=90),
        "two_push_failures": lambda env: env.script.update(push=1, deploy=1),
    }


@pytest.mark.parametrize("case", ["exit_three", "verify_failed", "two_push_failures"])
def test_warm_start_never_reuses_a_tree_marked_for_refetch(case):
    env = FakeEnv()
    run_loop(env, **state_environ()).serve()
    fetches = env.counts["fetch"]
    refetch_cases()[case](env)
    key = f"{STATE}/{pl.STATE_FILE}"
    env.files[key] = json.dumps({**json.loads(env.files[key]), "last_gh": 0})
    run_loop(env, **state_environ()).serve()
    state = saved(env)
    assert state["want_fetch"] is True or state["have_dist"] is False
    before = env.counts["fetch"]
    env.script.clear()
    run_loop(env, **state_environ()).serve()
    assert env.counts["fetch"] == before + 1
    assert fetches == 1


def test_state_age_boundary():
    for age, warm in ((199, True), (200, True), (201, False)):
        env = FakeEnv()
        run_loop(env, 1, **state_environ()).serve()
        env.t += age - (env.t - saved(env)["saved_at"])
        loop = run_loop(env, **state_environ())
        loop.apply_knobs()
        assert loop.load_state() is warm


def test_a_lost_cache_save_cold_starts_the_next_run():
    env = FakeEnv()
    run_loop(env, **state_environ()).serve()
    first = dict(env.files)
    run_loop(env, **state_environ()).serve()
    env.t += 30
    env.files.update(first)
    fetches = env.counts["fetch"]
    run_loop(env, **state_environ()).serve()
    assert env.counts["fetch"] == fetches + 1


def test_a_push_timeout_keeps_the_throttle_clock():
    loop, env = make(1)
    loop.have_dist = True
    loop.last_gh = T0 - 500
    env.script["push"] = 124
    assert loop.publish_github(T0) == "failed"
    assert loop.last_gh == T0 - 500
    env.script["push"] = 1
    assert loop.publish_github(T0) == "failed"
    assert loop.last_gh == 0


def warm_state(env, age):
    env.files[f"{STATE}/{pl.STATE_FILE}"] = json.dumps(
        {"saved_at": env.t - age, "have_dist": True, "want_fetch": False, "fresh_restore": False}
    )


@pytest.mark.parametrize("age,warm", [(150, True), (201, False)])
def test_state_age_is_measured_at_process_start(age, warm):
    env = TimedEnv()
    env.durations = {"npm": 60}
    warm_state(env, age)
    run_loop(env, 3, GITHUB_REF="refs/heads/develop", **HARD, **state_environ()).run()
    assert env.counts.get("fetch", 0) == (0 if warm else 1)


def test_broken_build_across_runs_alarms_once_then_goes_red_and_chains():
    env = FakeEnv()
    env.script["prices"] = 3
    env.script["slow"] = 3
    codes = []
    for _ in range(8):
        before = env.counts.get("fetch", 0)
        loop = run_loop(env, GITHUB_REF="refs/heads/master", **state_environ())
        codes.append(loop.run())
        assert env.counts["fetch"] > before
        if codes[-1] == 1 and any("Nothing could be published" in line for line in env.lines):
            break
    errors = [line for line in env.lines if "failed 5 times in a row" in line]
    assert len(errors) == 1
    assert codes[-1] == 1 and set(codes[:-1]) == {0}
    assert env.counts["gh"] == len(codes)
    assert saved(env)["nothing"] == 0


def test_hung_deploy_never_blocks_the_github_push():
    env = TimedEnv()
    env.durations = {"deploy": 100_000}
    for _ in range(8):
        run_loop(env, 3, GITHUB_REF="refs/heads/master", **HARD, **state_environ()).run()
    stamps = env.times("push")
    assert len(stamps) >= 2
    assert all(gap >= pl.GITHUB_PUSH_SPACING for gap in zip_gaps(stamps))
    assert all(call[3] <= pl.DEPLOY_CAP for call in env.calls if call[0] == "deploy")
    errors = [line for line in env.lines if "Cloudflare deploy failed 5 times in a row" in line]
    assert len(errors) == 1


def test_hung_install_every_run_still_builds_pushes_and_alarms_once():
    env = TimedEnv()
    env.durations = {"npm": 100_000}
    env.script["npm"] = 1
    for _ in range(18):
        run_loop(env, 3, GITHUB_REF="refs/heads/master", **HARD, **state_environ()).run()
    assert env.counts.get("prices", 0) + env.counts.get("slow", 0) >= 5
    assert env.counts["push"] >= 2
    assert "deploy" not in env.kinds()
    errors = [line for line in env.lines if "Cloudflare deploy failed 5 times in a row" in line]
    assert len(errors) == 1


def test_a_due_slow_lane_runs_after_a_short_install():
    env = TimedEnv()
    env.durations = {"npm": 50}
    run_loop(env, 3, **HARD, **state_environ()).run()
    assert env.counts["slow"] == 1


def test_a_deferred_slow_lane_runs_first_in_the_next_run():
    env = TimedEnv()
    env.durations = {"npm": 55, "create": 45}
    first = run_loop(env, 3, **HARD, **state_environ())
    first.run()
    assert env.counts.get("slow", 0) == 0
    assert first.last_slow == 0
    env.durations = {}
    env.t += 150
    fetches = env.counts["fetch"]
    run_loop(env, 3, **HARD, **state_environ()).run()
    assert env.counts["fetch"] == fetches
    assert env.counts["slow"] == 1


def tehran(day, hour):
    local = datetime.datetime(2024, 1, day, hour, 0, 0)
    return int((local - datetime.timedelta(hours=3, minutes=30)).replace(tzinfo=datetime.timezone.utc).timestamp())


PEAK_AT, MID_AT, NIGHT_AT = tehran(6, 12), tehran(6, 20), tehran(6, 2)


def tier_loop(tiers="on", **extra):
    loop, env = make(1, GHEYMAT_CADENCE_TIERS=tiers, **extra)
    loop.apply_knobs()
    loop.last_mark = "m"
    return loop, env


def test_tier_epochs_are_what_the_tests_assume():
    assert [cadence.tier(t) for t in (PEAK_AT, MID_AT, NIGHT_AT)] == ["peak", "mid", "night"]


def test_night_gap_needs_300_seconds():
    loop, _ = tier_loop()
    assert loop.is_due(NIGHT_AT, 200, "m") is False
    assert loop.is_due(NIGHT_AT, 300, "m") is True


def test_mid_gap_is_180_and_peak_is_unchanged():
    loop, _ = tier_loop()
    assert loop.is_due(MID_AT, 179, "m") is False
    assert loop.is_due(MID_AT, 180, "m") is True
    assert loop.is_due(PEAK_AT, 179, "m") is False
    assert loop.is_due(PEAK_AT, 180, "m") is True
    assert loop.cadence == 180


def test_tiers_off_by_default_ignores_the_clock():
    loop, _ = tier_loop(tiers="")
    assert loop.tiers is False
    assert loop.is_due(NIGHT_AT, 180, "m") is True


def test_tiers_never_shorten_live_first_cadence():
    loop, _ = tier_loop(GHEYMAT_ORDER="live-first")
    assert loop.is_due(PEAK_AT, 70, "m") is False
    assert 75 <= loop.cadence <= 105
    loop.is_due(NIGHT_AT, 100, "m")
    assert loop.cadence == 300


def test_mark_change_at_night_is_due_after_45_and_sets_hot_window():
    loop, _ = tier_loop()
    assert loop.is_due(NIGHT_AT, 44, "x") is False
    assert loop.hot_until == 0
    assert loop.is_due(NIGHT_AT, 45, "x") is True
    assert loop.hot_until == NIGHT_AT + cadence.HOT_SECONDS


def test_mark_change_at_peak_does_not_set_hot_window():
    loop, _ = tier_loop()
    assert loop.is_due(PEAK_AT, 60, "x") is True
    assert loop.hot_until == 0


def test_hot_window_behaves_as_peak():
    loop, _ = tier_loop()
    loop.hot_until = NIGHT_AT + 100
    assert loop.is_due(NIGHT_AT, 180, "m") is True
    assert loop.is_due(NIGHT_AT + 99, 180, "m") is True
    assert loop.is_due(NIGHT_AT + 99, 179, "m") is False
    assert loop.is_due(NIGHT_AT + 100, 180, "m") is False
    loop.hot_until = NIGHT_AT
    assert loop.is_due(NIGHT_AT, 200, "m") is False


def test_quiet_until_wins_over_peak_tier():
    loop, env = tier_loop(GHEYMAT_ORDER="live-first")
    env.files[LIVE] = json.dumps({"quiet_until": PEAK_AT + 1000})
    assert loop.is_due(PEAK_AT, 100, "m") is False
    assert loop.cadence == 180
    assert loop.is_due(PEAK_AT, 180, "m") is True


def test_tier_logged_only_on_change():
    loop, env = tier_loop()
    for at in (NIGHT_AT, NIGHT_AT + 5, MID_AT, MID_AT + 5, NIGHT_AT):
        loop.is_due(at, 10, "m")
    assert [line for line in env.lines if line.startswith("Cadence:")] == [
        "Cadence: night", "Cadence: mid", "Cadence: night"]
    off, env_off = tier_loop(tiers="off")
    off.is_due(NIGHT_AT, 10, "m")
    assert not any(line.startswith("Cadence:") for line in env_off.lines)


def test_hot_until_survives_a_state_carry():
    env = FakeEnv()
    first = run_loop(env, 1, **state_environ(GHEYMAT_CADENCE_TIERS="on"))
    first.serve()
    first.hot_until = env.t + cadence.HOT_SECONDS - 20
    first.save_state()
    second = run_loop(env, 1, **state_environ(GHEYMAT_CADENCE_TIERS="on"))
    assert second.load_state() is True
    assert second.hot_until == first.hot_until


def test_missing_or_garbage_hot_until_defaults_to_zero():
    for bad in (None, "soon", True, 1.5):
        env = FakeEnv()
        run_loop(env, 1, **state_environ()).serve()
        state = saved(env)
        if bad is None:
            state.pop("hot_until")
        else:
            state["hot_until"] = bad
        env.files[f"{STATE}/{pl.STATE_FILE}"] = json.dumps(state)
        loop = run_loop(env, 1, **state_environ())
        assert loop.load_state() is True
        assert loop.hot_until == 0


def test_huge_hot_until_is_clamped():
    env = FakeEnv()
    run_loop(env, 1, **state_environ()).serve()
    state = saved(env)
    state["hot_until"] = 10 ** 12
    env.files[f"{STATE}/{pl.STATE_FILE}"] = json.dumps(state)
    loop = run_loop(env, 1, **state_environ())
    assert loop.load_state() is True
    assert loop.hot_until == state["saved_at"] + cadence.HOT_SECONDS


def test_poll_gap_by_tier_and_hot_window():
    loop, _ = tier_loop()
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 500) == 60
    assert loop.poll_gap(MID_AT, MID_AT + 500) == 30
    assert loop.poll_gap(PEAK_AT, PEAK_AT + 500) == 15
    loop.hot_until = NIGHT_AT + 50
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 500) == 15
    off, _ = tier_loop(tiers="off")
    assert off.poll_gap(NIGHT_AT, NIGHT_AT + 500) == 15


def test_night_sleep_stops_at_the_gap_so_publish_is_not_late():
    loop, _ = tier_loop()
    loop.is_due(NIGHT_AT, 280, "m")
    assert loop.cadence == 300
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 500, 280) == 20
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 500, 299) == 1
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 500, 100) == 60
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 500, 400) == 60


def test_force_and_new_mark_still_fire_at_night():
    loop, _ = tier_loop()
    loop.force = True
    assert loop.is_due(NIGHT_AT, 45, "m") is True
    assert loop.is_due(NIGHT_AT, 44, "m") is False


def test_hot_window_not_started_when_github_spacing_blocks_the_publish():
    loop, _ = tier_loop()
    loop.last_mark = "old"
    loop.last_gh = NIGHT_AT - 10
    loop.app_channel = lambda: False
    assert loop.is_due(NIGHT_AT, 50, "new") is False
    assert loop.hot_until == 0


def test_poll_sleep_never_passes_the_deadline():
    loop, _ = tier_loop()
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 10) == 10
    assert loop.poll_gap(NIGHT_AT, NIGHT_AT + 0) == 1
    env = FakeEnv()
    env.t = NIGHT_AT
    loop = pl.Loop(env, base_environ(PUBLISH_LOOP_MINUTES="1", GHEYMAT_CADENCE_TIERS="on"),
                   lambda: "m", python="python", mirror=True)
    assert loop.serve() == 0
    assert max(env.sleeps) <= 60
    assert env.t <= NIGHT_AT + 60 + 1


def test_unknown_tiers_value_warns_and_stays_off():
    loop, env = tier_loop(tiers="maybe")
    assert loop.tiers is False
    assert "::warning::GHEYMAT_CADENCE_TIERS has an unknown value, using off" in env.lines


WINDOW_OPEN = int(datetime.datetime(2026, 11, 14, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=3, minutes=30))).timestamp())
WINDOW_SHUT = int(datetime.datetime(2026, 11, 13, 19, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=3, minutes=30))).timestamp())


def hours_loop(at, hours="on"):
    env = FakeEnv()
    env.t = at
    loop = pl.Loop(env, base_environ(GITHUB_REF="refs/heads/master", GHEYMAT_HOURS=hours), lambda: "", python="python")
    loop.configure()
    return loop, env


def test_run_does_nothing_outside_hours():
    loop, env = hours_loop(WINDOW_SHUT)
    assert loop.run() == 0
    assert env.calls[0][1] == ["gh", "workflow", "run", "gheymat-latest.yml", "--ref", "master"]
    assert "Outside publishing hours, handing over to the idle run" in env.lines


def test_chain_continues_outside_hours_into_the_idle_run():
    loop, env = hours_loop(WINDOW_SHUT)
    loop.started = env.t - 999
    assert loop.chain() == 0
    assert env.calls[0][1] == ["gh", "workflow", "run", "gheymat-latest.yml", "--ref", "master"]


def test_chain_continues_inside_hours():
    loop, env = hours_loop(WINDOW_OPEN)
    loop.started = env.t - 999
    assert loop.chain() == 0
    assert env.calls[0][1] == ["gh", "workflow", "run", "gheymat-latest.yml", "--ref", "master"]


def test_hours_off_by_default_ignores_the_clock():
    loop, env = hours_loop(WINDOW_SHUT, hours="")
    loop.started = env.t - 999
    assert loop.hours is False
    assert loop.chain() == 0
    assert env.calls and env.calls[0][1][0] == "gh"
