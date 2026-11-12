import pathlib
import sys
from datetime import date, datetime, timezone

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gheymat_news as news
import news_archive as na

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.rows = []

    def load(self, root, name):
        return list(self.rows)

    def append(self, root, name, record):
        self.rows.append(record)

    def write(self, root, name, records, loaded):
        if len(records) < loaded:
            return False
        self.rows = list(records)
        return True


def item(i, at, effect=None, source="A"):
    return {"id": i, "publishedAt": at, "effect": effect, "source": source}


def test_counts_keyed_by_first_seen_tehran_day():
    s = Store()
    items = [item("1", "2026-11-09T10:00:00Z", "usd_up"), item("2", "2026-11-08T09:00:00Z", "usd_down", "B"),
             item("3", "2026-11-09T21:00:00Z"), item("4", "2026-11-09T20:00:00Z", "neutral")]
    assert na.record_day("r", NOW, items, store=s) == 1
    by = na.latest_by_date(s.rows)
    assert list(by) == ["2026-11-09"]
    rec = by["2026-11-09"]
    assert rec["up"] == 1 and rec["down"] == 1 and rec["none"] == 2 and rec["total"] == 4
    assert rec["sourceCount"] == 2
    assert na.record_day("r", NOW, [item("5", "bad")], store=s) == 0


def test_no_double_count_across_runs():
    s = Store()
    items = [item("1", "2026-11-09T10:00:00Z", "usd_up")]
    na.record_day("r", NOW, items, store=s)
    assert na.record_day("r", NOW, items, store=s) == 0
    na.record_day("r", NOW, items + [item("2", "2026-11-09T11:00:00Z", "usd_up")], store=s)
    rec = na.latest_by_date(s.rows)["2026-11-09"]
    assert rec["up"] == 2 and rec["total"] == 2 and len(s.rows) == 2


def day(n, hour=12):
    return datetime(2026, 11, n, hour, 0, tzinfo=timezone.utc)


def sh(i, shadow, source="A", topics=()):
    return {"id": i, "publishedAt": "2026-11-09T10:00:00Z", "effect": None, "source": source,
            "shadowEffect": shadow, "topics": list(topics)}


def test_late_arrival_does_not_change_tilt_at_basis():
    s = Store()
    na.record_day("r", day(5), [sh("a", "usd_up"), sh("b", "usd_up"), sh("c", "usd_up")], store=s, config_version="c1")
    before = na.news_tilt(s.rows, date(2026, 11, 6))
    na.record_day("r", day(6), [sh("late1", "usd_down"), sh("late2", "usd_down")], store=s, config_version="c1")
    assert na.news_tilt(s.rows, date(2026, 11, 6)) == before == 1.0
    assert na.news_tilt(s.rows, date(2026, 11, 7)) < 1.0


def test_same_id_on_consecutive_days_counted_once():
    s = Store()
    na.record_day("r", day(5), [sh("x", "usd_up")], store=s, config_version="c1")
    assert na.record_day("r", day(6), [sh("x", "usd_up")], store=s, config_version="c1") == 0
    assert na.record_day("r", day(8), [sh("x", "usd_up")], store=s, config_version="c1") == 0
    assert na.record_day("r", day(9), [sh("x", "usd_up")], store=s, config_version="c1") == 1


def test_shadow_counts_and_unknown():
    s = Store()
    items = [sh("1", "usd_up", topics=("fx", "oil")), sh("2", "usd_up", "B", ("fx",)), sh("3", "usd_down", "B"),
             sh("4", "unknown"), sh("5", None), sh("6", "other")]
    na.record_day("r", NOW, items, store=s, config_version="abc")
    rec = na.latest_by_date(s.rows)["2026-11-09"]
    assert rec["shadowUp"] == 2 and rec["shadowDown"] == 1 and rec["up"] == 0 and rec["down"] == 0
    assert rec["shadowUnknown"] == 1 and rec["shadowNone"] == 2 and rec["none"] == 6
    assert rec["topics"] == {"fx": 2, "gold": 0, "oil": 1, "sanctions": 0, "politics": 0}
    assert rec["cfg"] == "abc" and rec["recordedAt"] == "2026-11-09T12:00:00Z" and rec["sourceCount"] == 2


def test_new_records_carry_no_outlet_names():
    s = Store()
    legacy = {"date": "2026-11-09", "up": 0, "down": 0, "none": 1, "total": 1, "sources": {"Named": 1}, "ids": ["old"]}
    s.rows.append(legacy)
    na.record_day("r", NOW, [sh("1", "usd_up", source="Named")], store=s, config_version="c")
    rec = na.latest_by_date(s.rows)["2026-11-09"]
    assert "sources" not in rec and "Named" not in repr(rec)
    assert rec["ids"] == ["old", "1"] and rec["none"] == 2


def legacy_rows():
    return [{"date": "2026-11-06", "up": 1, "down": 0, "none": 2, "total": 3, "sources": {"Named": 3}, "ids": ["a"]},
            {"date": "2026-11-07", "up": 0, "down": 2, "none": 0, "total": 2, "sources": {"Other": 2}, "ids": ["b"]}]


def test_ids_helper_tolerates_bad_shapes():
    for bad in (7, [{"x": 1}], None, "abc", {"a": 1}):
        s = Store()
        s.rows.append({"date": "2026-11-09", "ids": bad, "up": 0})
        s.rows.append({"date": "2026-11-08", "ids": bad})
        assert na.record_day("r", NOW, [sh("1", "usd_up")], store=s, config_version="c") == 1
        assert na.latest_by_date(s.rows)["2026-11-09"]["ids"] == ["1"]
    assert na._ids({"ids": ["a", 3, {"k": 1}]}) == ["a"]


def test_legacy_outlet_maps_stripped_with_new_items():
    s = Store()
    s.rows = legacy_rows()
    expect = [{k: v for k, v in r.items() if k != "sources"} for r in legacy_rows()]
    assert na.record_day("r", NOW, [sh("1", "usd_up", source="Named")], store=s, config_version="c") == 1
    assert all("sources" not in r and "Named" not in repr(r) for r in s.rows)
    assert s.rows[:2] == expect and len(s.rows) == 3


def test_pure_strip_needs_no_new_items_and_is_idempotent():
    s = Store()
    s.rows = legacy_rows()
    expect = [{k: v for k, v in r.items() if k != "sources"} for r in legacy_rows()]
    na.record_day("r", NOW, [], store=s)
    assert s.rows == expect and len(s.rows) == 2
    na.record_day("r", NOW, [], store=s)
    assert s.rows == expect


def test_strip_never_raises_without_write():
    class NoWrite(Store):
        write = None

    s = NoWrite()
    s.rows = legacy_rows()
    na.record_day("r", NOW, [], store=s)


def test_idempotent_double_run():
    s = Store()
    items = [sh("1", "usd_up"), sh("2", "usd_down")]
    na.record_day("r", NOW, items, store=s, config_version="c")
    snapshot = list(s.rows)
    assert na.record_day("r", NOW, items, store=s, config_version="c") == 0
    assert s.rows == snapshot


def test_cfg_stays_first_value_unless_missing():
    s = Store()
    na.record_day("r", NOW, [sh("1", "usd_up")], store=s, config_version="one")
    na.record_day("r", NOW, [sh("2", "usd_up")], store=s, config_version="two")
    assert na.latest_by_date(s.rows)["2026-11-09"]["cfg"] == "one"
    s2 = Store()
    s2.rows.append({"date": "2026-11-09", "up": 0, "down": 0, "none": 1, "total": 1, "ids": ["o"]})
    na.record_day("r", NOW, [sh("2", "usd_up")], store=s2, config_version="two")
    assert na.latest_by_date(s2.rows)["2026-11-09"]["cfg"] == "two"


def marked(d, up, down, cfg="c1"):
    return {"date": d, "up": 0, "down": 0, "none": up + down, "shadowUp": up, "shadowDown": down, "cfg": cfg}


def test_mixed_archive_first_marked_day_and_count():
    legacy = [{"date": "2026-11-01", "up": 0, "down": 0, "none": 5}, {"date": "2026-11-02", "up": 0, "down": 0, "none": 4}]
    recs = legacy + [marked("2026-11-03", 2, 0), marked("2026-11-04", 2, 1), marked("2026-11-05", 1, 0)]
    assert na.first_marked_day(recs) == "2026-11-04"
    assert na.marked_days(recs) == 2
    assert na.first_marked_day(legacy) is None and na.marked_days(legacy) == 0
    assert na.first_marked_day([]) is None and na.marked_days([]) == 0
    assert na.first_marked_day([marked("2026-11-03", 1, 0)]) == "2026-11-04"
    assert na.marked_days([marked("2026-11-03", 1, 0)]) == 0


def test_cfg_change_restarts_series():
    recs = [marked("2026-11-03", 0, 4, "old"), marked("2026-11-04", 0, 4, "old"),
            marked("2026-11-05", 3, 0, "new"), marked("2026-11-06", 2, 0, "new")]
    assert na.first_marked_day(recs) == "2026-11-06"
    assert na.marked_days(recs) == 1
    assert na.news_tilt(recs, date(2026, 11, 7)) == 1.0


def test_tilt_reads_shadow_for_marked_and_legacy_unchanged():
    recs = [marked("2026-11-05", 3, 1)]
    assert na.news_tilt(recs, date(2026, 11, 9)) == 0.5
    assert na.news_tilt([{"date": "2026-11-05", "up": 3, "down": 1, "sources": {"X": 4}}], date(2026, 11, 9)) == 0.5


def test_malformed_records_never_raise():
    bad = [None, 5, {"date": 3}, {"date": "nope", "up": 1}, {"date": "2026-11-05", "up": "x", "down": None},
           {"date": "2026-11-06", "cfg": "c", "shadowUp": "z", "topics": 4, "ids": 7}, {"date": "2026-11-07", "cfg": 9}]
    assert na.news_tilt(bad, date(2026, 11, 9)) == 0.0
    na.first_marked_day(bad)
    na.marked_days(bad)
    assert na.news_tilt("junk", "junk") == 0.0
    s = Store()
    s.rows.append({"date": "2026-11-09", "topics": 4, "ids": [1, "a"], "up": "q"})
    na.record_day("r", NOW, [sh("1", "usd_up"), None, {"id": 3}], store=s, config_version=None)


def test_tilt_uses_only_prior_days():
    recs = [{"date": "2026-11-05", "up": 4, "down": 0}, {"date": "2026-11-09", "up": 0, "down": 50}]
    assert na.news_tilt(recs, date(2026, 11, 9)) == 1.0
    assert na.news_tilt(recs, "2026-11-05") == 0.0
    assert na.news_tilt([], date(2026, 11, 9)) == 0.0
    assert na.news_tilt([{"date": "2026-11-08", "up": 1, "down": 1}], date(2026, 11, 9)) == 0.0


def test_hook_never_raises(monkeypatch):
    logs = []

    class Boom:
        @staticmethod
        def record_day(*a, **k):
            raise RuntimeError("x")

    monkeypatch.setitem(sys.modules, "news_archive", Boom)
    news.archive_news("root", NOW, [], logs.append)
    assert logs and "archive skipped" in logs[0]
    news.archive_news(None, NOW, [], logs.append)


def test_strip_keeps_every_record_even_with_duplicate_dates():
    s = Store()
    s.rows = legacy_rows() + [{"date": "2026-11-07", "up": 5, "down": 0, "none": 0, "total": 5, "sources": {"Third": 5}, "ids": ["c"]}]
    before = len(s.rows)
    na.record_day("r", NOW, [], store=s)
    assert len(s.rows) == before
    assert all("sources" not in r for r in s.rows)
    assert [r["ids"] for r in s.rows] == [["a"], ["b"], ["c"]]


def test_strip_passes_the_real_loaded_count_to_the_guard():
    calls = []

    class Spy(Store):
        def write(self, root, name, records, loaded):
            calls.append((len(records), loaded))
            return super().write(root, name, records, loaded)

    s = Spy()
    s.rows = legacy_rows()
    na.record_day("r", NOW, [sh("1", "usd_up")], store=s, config_version="c")
    assert calls and calls[0][1] == 2 and calls[0][0] >= calls[0][1]
