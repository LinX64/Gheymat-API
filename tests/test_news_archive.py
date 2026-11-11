import pathlib
import sys
from datetime import date, datetime, timezone

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gheymat_news as news  # noqa: E402
import news_archive as na  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.rows = []

    def load(self, root, name):
        return list(self.rows)

    def append(self, root, name, record):
        self.rows.append(record)


def item(i, at, effect=None, source="A"):
    return {"id": i, "publishedAt": at, "effect": effect, "source": source}


def test_counts_and_tehran_day():
    s = Store()
    items = [item("1", "2026-11-09T10:00:00Z", "usd_up"), item("2", "2026-11-09T09:00:00Z", "usd_down", "B"),
             item("3", "2026-11-09T21:00:00Z"), item("4", "2026-11-09T20:00:00Z", "neutral")]
    assert na.record_day("r", NOW, items, store=s) == 2
    by = na.latest_by_date(s.rows)
    assert by["2026-11-09"]["up"] == 1 and by["2026-11-09"]["down"] == 1 and by["2026-11-09"]["total"] == 3
    assert by["2026-11-09"]["sources"] == {"A": 2, "B": 1}
    assert by["2026-11-10"]["none"] == 1


def test_no_double_count_across_runs():
    s = Store()
    items = [item("1", "2026-11-09T10:00:00Z", "usd_up")]
    na.record_day("r", NOW, items, store=s)
    assert na.record_day("r", NOW, items, store=s) == 0
    na.record_day("r", NOW, items + [item("2", "2026-11-09T11:00:00Z", "usd_up")], store=s)
    rec = na.latest_by_date(s.rows)["2026-11-09"]
    assert rec["up"] == 2 and rec["total"] == 2 and len(s.rows) == 2


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
