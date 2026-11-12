import base64
import pathlib
import sys
from dataclasses import dataclass, field

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import publish_loop as pl
from test_publish_loop import FakeEnv, T0, TOKEN, STORE_KEYS, base_environ, zip_gaps

SECRETS = {
    "GH_TOKEN": TOKEN,
    "FEED_STORE_KEY_ID": "ksk-id",
    "FEED_STORE_SECRET": "ksk-secret",
    "FEED_STORE_BUCKET": "ksk-bucket",
}


@dataclass
class Result:
    hot_ok: bool = True
    uploaded: int = 1
    skipped: int = 0
    failed: int = 0
    over_budget: bool = False
    keys_failed_kinds: dict = field(default_factory=dict)


class FakeSync:
    def __init__(self, env, script=None, log=None, duration=0):
        self.env = env
        self.duration = duration
        self.script = script
        self.log = log
        self.calls = []

    def sync(self, site, slow_lane):
        number = len(self.calls) + 1
        self.calls.append((str(site), slow_lane, self.env.t))
        self.env.t += self.duration
        outcome = self.script(number) if callable(self.script) else True
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Result):
            return outcome
        if self.log:
            self.log(f"feed sync: uploaded 1, skipped 0, failed 0 {SECRETS['FEED_STORE_SECRET']}")
        return Result(hot_ok=bool(outcome))


class Factory:
    def __init__(self, env, script=None, broken=0, duration=0):
        self.env = env
        self.duration = duration
        self.script = script
        self.broken = broken
        self.built = []
        self.attempts = 0

    def __call__(self, environ, log, include_v2):
        self.attempts += 1
        if self.attempts <= self.broken:
            raise RuntimeError(SECRETS["FEED_STORE_SECRET"])
        sync = FakeSync(self.env, self.script, log, self.duration)
        sync.include_v2 = include_v2
        self.built.append(sync)
        return sync


def build(minutes=30, script=None, broken=0, mirror=True, sync_seconds=0, **extra):
    env = FakeEnv()
    environ = base_environ(PUBLISH_LOOP_MINUTES=str(minutes), **extra)
    factory = Factory(env, script, broken, sync_seconds)
    loop = pl.Loop(env, environ, lambda: "m", python="python", mirror=mirror, sync_factory=factory)
    return loop, env, factory


def realistic(env):
    env.durations.update({"assemble": 10, "verify_site": 5, "prices": 20, "slow": 45, "news": 60})


def sync_calls(factory):
    return [call for sync in factory.built for call in sync.calls]


def builds(env):
    return sorted(env.times("prices") + env.times("slow"))


def test_off_mode_makes_no_factory_call_and_no_extra_command():
    loop, env, factory = build(30)
    loop.serve()
    reference = FakeEnv()
    plain = base_environ(PUBLISH_LOOP_MINUTES="30")
    for key in STORE_KEYS:
        del plain[key]
    other = pl.Loop(reference, plain, lambda: "m", python="python", mirror=True)
    other.serve()
    assert factory.attempts == 0
    assert env.kinds() == reference.kinds()
    assert env.lines == reference.lines
    assert loop.store_mode == "off" and loop.pages_mode == "every"


def test_off_mode_explicit_value_is_off():
    loop, env, factory = build(10, GHEYMAT_STORE="off")
    loop.serve()
    assert factory.attempts == 0


def test_shadow_syncs_once_per_build_with_matching_lane():
    loop, env, factory = build(40, GHEYMAT_STORE="shadow")
    loop.serve()
    kinds = [kind for kind in env.kinds() if kind in ("slow", "prices")]
    calls = sync_calls(factory)
    assert factory.attempts == 1
    assert len(calls) == len(kinds)
    assert [call[1] for call in calls] == [kind == "slow" for kind in kinds]
    assert calls[0][1] is True and calls[0][0] == "site"


def test_shadow_after_verify_and_pages_deploy():
    loop, env, factory = build(5, GHEYMAT_STORE="shadow")
    loop.serve()
    kinds = env.kinds()
    first_sync = factory.built[0].calls[0][2]
    assert kinds.index("verify_site") < kinds.index("deploy")
    assert first_sync >= env.times("deploy")[0]


def test_shadow_failures_only_warn_and_change_nothing():
    reference_loop, reference, _ = build(60)
    reference_loop.serve()
    loop, env, factory = build(60, script=lambda n: n % 3 != 0, GHEYMAT_STORE="shadow")
    loop.serve()
    assert builds(env) == builds(reference)
    assert env.kinds() == [kind for kind in reference.kinds()]
    assert loop.store_failures == 0 and loop.nothing == reference_loop.nothing
    assert loop.failures == reference_loop.failures and loop.cf_failures == reference_loop.cf_failures
    assert any("::warning::#3 feed store hot documents not stored" == line for line in env.lines)
    assert not any("Feed store failed" in line for line in env.lines + env.errors)


def test_shadow_exception_and_broken_factory_only_warn():
    loop, env, factory = build(20, script=lambda n: RuntimeError("x"), GHEYMAT_STORE="shadow")
    assert loop.serve() == 0
    assert sum("hot documents not stored" in line for line in env.lines) >= 3
    loop, env, factory = build(20, broken=10**6, GHEYMAT_STORE="shadow")
    assert loop.serve() == 0
    assert factory.attempts >= 3
    assert sum("hot documents not stored" in line for line in env.lines) >= 3


def test_on_with_pages_off_never_deploys_or_installs():
    loop, env, factory = build(30, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    assert loop.start() is True
    code = loop.serve()
    assert code == 0
    for kind in ("deploy", "npm", "create"):
        assert kind not in env.kinds()
    assert env.counts["assemble"] == env.counts["verify_site"] == len(sync_calls(factory))
    assert not any("Cloudflare" in line for line in env.lines)


def test_store_only_assembles_and_verifies_site():
    loop, env, factory = build(5, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    loop.serve()
    kinds = env.kinds()
    assert "assemble" in kinds and "verify_site" in kinds
    assert kinds.index("assemble") < kinds.index("verify_site")
    assert env.rmtrees.count("site") >= 2 * len(sync_calls(factory))


def test_on_store_failure_quick_retry_and_resets():
    loop, env, factory = build(60, script=lambda n: n != 1, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    code = loop.serve()
    stamps = builds(env)
    assert 45 <= stamps[1] - stamps[0] < 60
    assert code == 0
    assert loop.store_failures == 0 and loop.nothing == 0


def test_on_five_store_failures_red_and_nonzero_exit():
    loop, env, factory = build(60, script=lambda n: False, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    code = loop.serve()
    assert code == 1
    assert sum(line == "::error::Feed store failed 5 times in a row" for line in env.lines) == 1
    assert loop.red and loop.nothing == 0
    assert builds(env)[-1] > builds(env)[5]


def test_on_nothing_counter_when_store_and_github_fail():
    loop, env, factory = build(120, script=lambda n: False, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    env.script["push"] = 1
    assert loop.serve() == 1
    assert loop.nothing == 5
    assert any("Nothing could be published 5 times in a row" in line for line in env.lines)


def test_on_store_ok_counts_as_published_even_when_github_fails():
    loop, env, factory = build(60, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    env.script["push"] = 1
    loop.serve()
    assert loop.nothing == 0


def test_on_site_assembly_failure_counts_as_store_failure():
    loop, env, factory = build(60, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    env.script["verify_site"] = 1
    code = loop.serve()
    assert code == 1
    assert factory.attempts == 0
    assert loop.store_failures >= 5


def test_on_with_pages_every_does_both():
    loop, env, factory = build(30, GHEYMAT_STORE="on")
    loop.serve()
    assert env.counts["deploy"] == len(sync_calls(factory)) >= 5
    assert env.counts["assemble"] == env.counts["verify_site"] == env.counts["deploy"]


def test_on_store_failure_with_pages_ok_still_quick_retries():
    loop, env, factory = build(60, script=lambda n: n != 1, GHEYMAT_STORE="on")
    loop.serve()
    stamps = builds(env)
    assert 45 <= stamps[1] - stamps[0] < 60


@pytest.mark.parametrize("store", ["on", "shadow"])
def test_pages_shell_deploys_exactly_once_on_first_build(store):
    loop, env, factory = build(40, GHEYMAT_STORE=store, GHEYMAT_PAGES="shell")
    assert loop.start() is True
    loop.serve()
    assert env.counts["deploy"] == 1
    kinds = env.kinds()
    first_build = min(kinds.index("slow"), kinds.index("prices") if "prices" in kinds else 10**6)
    assert kinds.index("deploy") > first_build
    assert kinds.count("slow") + kinds.count("prices") > 3
    assert kinds.index("deploy") < [i for i, k in enumerate(kinds) if k in ("slow", "prices")][1]


def test_pages_shell_installs_wrangler_pages_off_does_not():
    loop, env, factory = build(1, GHEYMAT_STORE="on", GHEYMAT_PAGES="shell")
    loop.start()
    assert env.counts["npm"] == 1 and env.counts["create"] == 1
    loop, env, factory = build(1, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    loop.start()
    assert "npm" not in env.kinds() and "create" not in env.kinds()
    assert not any("Cloudflare deploy is off" in line for line in env.lines)


def test_missing_cloudflare_token_does_not_disable_store():
    loop, env, factory = build(20, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    del loop.environ["CLOUDFLARE_API_TOKEN"]
    loop.start()
    loop.serve()
    assert len(sync_calls(factory)) >= 5
    assert loop.store_mode == "on"


def test_github_only_wait_does_not_apply_when_store_is_the_app_channel():
    loop, env, factory = build(30, mirror=False, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    env.gh_commit_time = T0 - 50
    loop.serve()
    assert builds(env)[1] < T0 + 350
    loop, env, factory = build(30, mirror=False, GHEYMAT_STORE="shadow", GHEYMAT_PAGES="off")
    env.gh_commit_time = T0 - 50
    loop.serve()
    assert builds(env)[1] >= T0 + 350


@pytest.mark.parametrize("missing", ["FEED_STORE_KEY_ID", "FEED_STORE_SECRET", "FEED_STORE_BUCKET", "CLOUDFLARE_ACCOUNT_ID"])
@pytest.mark.parametrize("mode", ["shadow", "on"])
def test_missing_store_secret_warns_and_runs_as_off(mode, missing):
    loop, env, factory = build(10, GHEYMAT_STORE=mode)
    del loop.environ[missing]
    loop.serve()
    assert env.lines.count("::warning::feed store is off: repository secrets are missing") == 1
    assert factory.attempts == 0 and loop.store_mode == "off"


def test_unknown_values_warn_and_use_defaults():
    loop, env, factory = build(2, GHEYMAT_STORE="maybe", GHEYMAT_PAGES="sometimes", FEED_STORE_V2="yes")
    loop.serve()
    assert loop.store_mode == "off" and loop.pages_mode == "every" and loop.include_v2 is True
    warnings = [line for line in env.lines if line.startswith("::warning::") and "unknown value" in line]
    assert len(warnings) == 3
    assert factory.attempts == 0


def test_v2_flag_is_passed_to_the_factory():
    loop, env, factory = build(3, GHEYMAT_STORE="shadow", FEED_STORE_V2="0")
    loop.serve()
    assert factory.built[0].include_v2 is False
    loop, env, factory = build(3, GHEYMAT_STORE="shadow")
    loop.serve()
    assert factory.built[0].include_v2 is True


def test_modes_are_read_once():
    loop, env, factory = build(5, GHEYMAT_STORE="shadow")
    loop.start()
    loop.environ["GHEYMAT_STORE"] = "off"
    loop.serve()
    assert loop.store_mode == "shadow" and factory.attempts == 1


def test_factory_built_once_and_reused():
    loop, env, factory = build(40, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    loop.serve()
    assert factory.attempts == 1 and len(factory.built) == 1
    assert len(factory.built[0].calls) >= 8


def test_factory_rebuilt_only_after_construction_failure():
    loop, env, factory = build(40, broken=2, GHEYMAT_STORE="shadow")
    loop.serve()
    assert factory.attempts == 3 and len(factory.built) == 1
    assert len(factory.built[0].calls) >= 3


def worst_gap(factory, failed):
    stamps = [call[2] for index, call in enumerate(sync_calls(factory), start=1) if index not in failed]
    return zip_gaps(stamps)


def test_acceptance_gap_between_successful_store_syncs_with_failure_injected():
    loop, env, factory = build(120, script=lambda n: n != 4, sync_seconds=8, GHEYMAT_STORE="on",
                               GHEYMAT_PAGES="off")
    realistic(env)
    assert loop.serve() == 0
    gaps = worst_gap(factory, {4})
    print("worst default gap", max(gaps))
    assert len(gaps) >= 20 and max(gaps) <= 300


def test_acceptance_gap_live_first_with_injected_failure():
    loop, env, factory = build(120, script=lambda n: n != 6, sync_seconds=8, GHEYMAT_STORE="on",
                               GHEYMAT_PAGES="off", GHEYMAT_ORDER="live-first")
    realistic(env)
    env.jitter = 15
    loop.serve()
    gaps = worst_gap(factory, {6})
    print("worst live-first gap", max(gaps))
    assert len(gaps) >= 40 and max(gaps) <= 300


def test_setup_failure_warns_with_a_closed_kind_only():
    class Boom(Exception):
        def __init__(self, kind):
            self.kind = kind
            super().__init__("ksk-secret detail")

    kinds = iter(["config", "connection", "other"])

    def factory(environ, log, include_v2):
        raise Boom(next(kinds))

    env = FakeEnv()
    loop = pl.Loop(env, base_environ(PUBLISH_LOOP_MINUTES="30", GHEYMAT_STORE="shadow"), lambda: "m",
                   python="python", mirror=True, sync_factory=factory)
    loop.serve()
    lines = [line for line in env.lines if "feed store setup failed" in line]
    assert lines[:3] == [
        "::warning::#1 feed store setup failed (config)",
        "::warning::#2 feed store setup failed (connection)",
        "::warning::#3 feed store setup failed (unknown)",
    ]
    assert not any("ksk-secret" in line for line in env.lines + env.errors)


def test_account_id_is_masked_in_emitted_lines():
    loop, env, factory = build(3, GHEYMAT_STORE="shadow")
    loop.say("https://cfa.example/x")
    assert env.lines[-1] == "https://***.example/x"


@pytest.mark.parametrize("mode,pages", [("off", "every"), ("shadow", "every"), ("on", "every"), ("on", "off"),
                                         ("on", "shell"), ("shadow", "off")])
def test_store_secrets_never_reach_a_child_environment(mode, pages):
    loop, env, factory = build(30, GHEYMAT_STORE=mode, GHEYMAT_PAGES=pages, GHEYMAT_ORDER="live-first")
    env.outputs["news"] = "news: refreshed\n"
    loop.run()
    assert env.calls
    for call in env.calls:
        child = call[2]
        for key in STORE_KEYS:
            assert key not in child
        assert not any(value in (SECRETS["FEED_STORE_KEY_ID"], SECRETS["FEED_STORE_SECRET"],
                                 SECRETS["FEED_STORE_BUCKET"]) for value in child.values())
    gh = [call for call in env.calls if call[0] == "gh"]
    for call in gh:
        assert "ANTHROPIC_API_KEY" not in call[2] and "GHEYMAT_PAYLOAD_KEY" not in call[2]


def test_children_get_no_more_secrets_than_before():
    loop, env, factory = build(10, GHEYMAT_STORE="on", GHEYMAT_PAGES="every")
    loop.start()
    loop.serve()
    sensitive = ("GH_TOKEN", "GHEYMAT_SIGNING_KEY", "GHEYMAT_PAYLOAD_KEY", "ANTHROPIC_API_KEY", "GHEYMAT_AI_SOURCES")
    for call in env.calls:
        if call[0] == "deploy":
            assert not any(key in call[2] for key in sensitive)
        if call[0] == "assemble":
            assert "GH_TOKEN" not in call[2] and "ANTHROPIC_API_KEY" not in call[2]
        if call[0] == "verify_site":
            assert "GHEYMAT_SIGNING_KEY" not in call[2]
        if call[0] in ("npm", "create"):
            assert not any(key in call[2] for key in sensitive)


def test_no_emitted_line_contains_a_secret():
    def script(number):
        if number % 3 == 0:
            return Result(hot_ok=False, keys_failed_kinds={"status": 2, "timeout": 1, "ksk-secret": 4})
        return True

    loop, env, factory = build(40, script=script, broken=1, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    env.outputs["push"] = SECRETS["FEED_STORE_SECRET"]
    loop.serve()
    lines = env.lines + env.errors
    assert any("feed sync: uploaded" in line for line in lines)
    assert any("feed store failed keys: status 2, timeout 1" in line for line in lines)
    for secret in SECRETS.values():
        assert not any(secret in line for line in lines)
    for secret in (SECRETS["FEED_STORE_KEY_ID"], SECRETS["FEED_STORE_BUCKET"]):
        assert not any(secret in line for line in lines)


def test_store_ok_line_format():
    loop, env, factory = build(3, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    env.durations["slow"] = 7
    loop.serve()
    assert "#1 store ok (live 7s after detection)" in env.lines
    assert any(line.startswith("feed sync:") for line in env.lines)


def test_sync_runs_in_the_loop_process_not_a_child():
    loop, env, factory = build(5, GHEYMAT_STORE="on", GHEYMAT_PAGES="off")
    loop.serve()
    for call in env.calls:
        assert not any("feed_sync" in part or "r2_store" in part for part in call[1])


def test_real_factory_builds_from_environment():
    pytest.importorskip("cryptography")
    pytest.importorskip("requests")
    key = base64.b64encode(bytes(range(32))).decode()
    environ = {
        "GHEYMAT_PAYLOAD_KEY": key,
        "CLOUDFLARE_ACCOUNT_ID": "acct1",
        "FEED_STORE_BUCKET": "bucket1",
        "FEED_STORE_KEY_ID": "keyid1",
        "FEED_STORE_SECRET": "secret1",
    }
    lines = []
    sync = pl.build_sync(environ, lines.append, False)
    assert type(sync).__name__ == "FeedSync"
    assert sync._include_v2 is False and sync._workers == 8
    assert repr(sync) == "FeedSync()"
