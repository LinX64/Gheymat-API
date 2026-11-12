import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import gheymat_signals as s

CSV = "observation_date,DCOILBRENTEU\n2026-10-01,80.0\n2026-10-02,.\n2026-10-05,\n2026-10-08,84.0\nbad,1\n2026-10-15,88.2\n"


class R:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class Http:
    def __init__(self, fail=()):
        self.fail, self.calls = fail, []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        sid = url.split("id=")[1]
        if sid in self.fail:
            raise TimeoutError()
        return R(CSV)


def test_parse_skips_missing():
    obs = s.parse_fred_csv(CSV)
    assert obs == [(date(2026, 10, 1), 80.0), (date(2026, 10, 8), 84.0), (date(2026, 10, 15), 88.2)]


def test_lag_and_join_no_lookahead():
    obs = s.parse_fred_csv(CSV)
    assert s.measured_lag_days(obs, date(2026, 10, 18)) == 3
    assert s.measured_lag_days([], date(2026, 10, 18)) is None
    assert s.value_known_at(obs, date(2026, 10, 15), 7) == (date(2026, 10, 8), 84.0)
    assert s.value_known_at(obs, date(2026, 10, 14), 7) == (date(2026, 10, 1), 80.0)
    assert s.value_known_at(obs, date(2026, 9, 30), 0) is None


def test_weekly_change():
    obs = s.parse_fred_csv(CSV)
    assert s.weekly_change(obs, date(2026, 10, 22), 7) == pytest.approx((88.2 / 84.0 - 1) * 100)
    assert s.weekly_change(obs, date(2026, 10, 10), 7) is None
    assert s.weekly_change(obs, date(2026, 9, 1), 7) is None


def test_effective_lag_uses_conservative_floor():
    obs = s.parse_fred_csv(CSV)
    assert s.effective_lag_days("oil", obs, date(2026, 10, 16)) == 7
    assert s.effective_lag_days("usd", obs, date(2026, 11, 15)) == 31


def test_fetch_and_load_never_raise():
    h = Http()
    got = s.load_signals(h, date(2026, 10, 16), lambda m: None)
    assert set(got) == {"oil", "usd"}
    assert all(t == s.FETCH_TIMEOUT for _, t in h.calls)
    logs = []
    got = s.load_signals(Http(fail={"DTWEXBGS"}), date(2026, 10, 16), logs.append)
    assert set(got) == {"oil"} and logs


def test_fetch_rejects_bad_status_and_empty():
    class Bad:
        def get(self, url, timeout=None):
            return R("observation_date,X\n", 200)
    with pytest.raises(RuntimeError):
        s.fetch_fred("X", Bad())

    class Err:
        def get(self, url, timeout=None):
            return R("", 503)
    assert s.load_signals(Err(), date(2026, 1, 1), lambda m: None) == {}
