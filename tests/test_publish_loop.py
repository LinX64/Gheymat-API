import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

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
        return True

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


def test_throttle_keeps_pushes_apart():
    loop, env, code = serve(60)
    assert code == 0
    gaps = env.gaps("push")[:-1]
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
    assert code == 1
    assert loop.nothing == 5
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
    assert loop.nothing == 5
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


def test_final_flush_verifies_first_and_pushes_once():
    loop, env = make(8)
    env.script["push"] = lambda n: 1 if n == 1 else 0
    env.gh_commit_time = T0 - 1000
    loop.serve()
    kinds = env.kinds()
    commits_final = [c for c in env.calls if c[0] == "git" and "Publish final" in c[1]]
    assert len(commits_final) == 1
    last_verify = max(i for i, k in enumerate(kinds) if k == "verify")
    last_push = max(i for i, k in enumerate(kinds) if k == "push")
    assert last_verify < last_push


def test_final_flush_skipped_when_level():
    loop, env = make(1)
    loop.serve()
    assert not any("Publish final" in c[1] for c in env.calls if c[0] == "git")


def test_final_flush_failure_warns():
    loop, env = make(4)
    env.script["push"] = lambda n: 1 if n >= 1 else 0
    loop.serve()
    assert "::warning::Final GitHub push failed" in env.lines


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


def test_chain_on_master_after_an_hour():
    loop, env, code = finish("refs/heads/master", 3600)
    assert code == 0
    call = env.calls[0]
    assert call[1] == ["gh", "workflow", "run", "gheymat-latest.yml", "--ref", "master"]
    assert call[2]["GH_TOKEN"] == TOKEN
    for key in ("GHEYMAT_PAYLOAD_KEY", "GHEYMAT_SIGNING_KEY", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", *STORE_KEYS):
        assert key not in call[2]


def test_no_chain_under_an_hour():
    loop, env, code = finish("refs/heads/master", 3599)
    assert code == 0 and env.calls == []
    assert "Run lasted under an hour, not chaining another" in env.lines


def test_no_chain_off_master():
    loop, env, code = finish("refs/heads/develop", 99999)
    assert code == 0 and env.calls == []


def test_run_does_not_chain_when_red_or_nothing_published():
    loop, env = make(120)
    env.script["prices"] = 3
    env.script["slow"] = 3
    assert loop.run() == 1
    assert "gh" not in env.kinds()
    loop, env = make(60)
    env.script["slow"] = 5
    loop.environ["PUBLISH_LOOP_MINUTES"] = "120"
    assert loop.run() == 1
    assert "gh" not in env.kinds()


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
