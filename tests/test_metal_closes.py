import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import archive_store
import metal_closes as mc

D1 = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
D1_LATE = datetime(2026, 11, 18, 17, 0, tzinfo=timezone.utc)
D2 = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)


def rates(gram, azadi_sell):
    return [{"code": "gram", "kind": "gold", "price": gram, "buy": None, "sell": None},
            {"code": "azadi", "kind": "coin", "price": None, "buy": azadi_sell - 100, "sell": azadi_sell},
            {"code": "usd", "kind": "currency", "buy": 1, "sell": 2, "price": None}]


class Disk:
    def __init__(self, docs=None):
        self.docs = dict(docs or {})
        self.writes = []

    def load(self, logical):
        return self.docs.get(logical)

    def write(self, logical, obj):
        self.docs[logical] = obj
        self.writes.append(logical)


def run(tmp, disk, rows, now):
    return mc.run(str(tmp), rows, now, disk.load, disk.write, log=lambda *_: None)


def test_today_is_not_published_and_only_gold_and_coins_recorded(tmp_path):
    disk = Disk()
    assert run(tmp_path, disk, rates(1000.0, 5000.0), D1) == 0
    assert disk.writes == []
    rec = archive_store.load(str(tmp_path), mc.NAME)
    assert set(rec[0]["codes"]) == {"gram", "azadi"}


def test_close_is_last_value_of_day_then_frozen_and_idempotent(tmp_path):
    disk = Disk()
    run(tmp_path, disk, rates(1000.0, 5000.0), D1)
    run(tmp_path, disk, rates(1100.0, 5200.0), D1_LATE)
    assert run(tmp_path, disk, rates(1300.0, 5600.0), D2) == 2
    gram = disk.docs["v1/history/gram"]
    assert gram == {"code": "gram", "days": 1, "points": [{"date": "2026-11-18", "price": 1100.0}]}
    azadi = disk.docs["v1/history/azadi"]["points"][0]
    assert azadi == {"date": "2026-11-18", "price": 5200.0, "buy": 5100.0, "sell": 5200.0}
    before = list(disk.writes)
    assert run(tmp_path, disk, rates(1400.0, 5700.0), D2) == 0
    assert disk.writes == before
    assert [p["price"] for p in disk.docs["v1/history/gram"]["points"]] == [1100.0]


def test_next_day_appends_and_absent_codes_have_no_doc(tmp_path):
    disk = Disk()
    run(tmp_path, disk, rates(1000.0, 5000.0), D1)
    run(tmp_path, disk, rates(1300.0, 5600.0), D2)
    d3 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    run(tmp_path, disk, rates(1400.0, 5700.0), d3)
    assert [p["date"] for p in disk.docs["v1/history/gram"]["points"]] == ["2026-11-18", "2026-11-19"]
    assert "v1/history/mithqal" not in disk.docs and "v1/history/usd" not in disk.docs


def test_existing_history_points_win_and_are_kept(tmp_path):
    old = {"code": "gram", "days": 1, "points": [{"date": "2026-11-18", "price": 999.0}]}
    disk = Disk({"v1/history/gram": old})
    run(tmp_path, disk, rates(1000.0, 5000.0), D1)
    run(tmp_path, disk, rates(1300.0, 5600.0), D2)
    d3 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    run(tmp_path, disk, rates(1400.0, 5700.0), d3)
    pts = disk.docs["v1/history/gram"]["points"]
    assert pts[0]["price"] == 999.0 and [p["date"] for p in pts] == ["2026-11-18", "2026-11-19"]


def test_no_state_dir_does_nothing():
    disk = Disk()
    assert mc.run(None, rates(1.0, 2.0), D1, disk.load, disk.write) == 0


def test_coin_buy_sell_are_ints(tmp_path):
    disk = Disk()
    run(tmp_path, disk, rates(1000.0, 5000.0), D1)
    run(tmp_path, disk, rates(1300.0, 5600.0), D2)
    p = disk.docs["v1/history/azadi"]["points"][0]
    assert type(p["buy"]) is int and type(p["sell"]) is int and isinstance(p["price"], float)


def test_codes_in_daily_are_left_to_history_writer(tmp_path):
    disk = Disk()
    mc.run(str(tmp_path), rates(1000.0, 5000.0), D1, disk.load, disk.write, log=lambda *_: None, known={"azadi"})
    mc.run(str(tmp_path), rates(1300.0, 5600.0), D2, disk.load, disk.write, log=lambda *_: None, known={"azadi"})
    assert "v1/history/azadi" not in disk.docs and "v1/history/gram" in disk.docs


def test_currency_and_existing_coin_series_untouched(tmp_path):
    usd = {"code": "usd", "days": 1, "points": [{"date": "2026-11-17", "price": 5.0}]}
    azadi = {"code": "azadi", "days": 1, "points": [{"date": "2026-11-17", "price": 9.0, "buy": 8, "sell": 9}]}
    disk = Disk({"v1/history/usd": usd, "v1/history/azadi": azadi})
    run(tmp_path, disk, rates(1000.0, 5000.0), D1)
    run(tmp_path, disk, rates(1300.0, 5600.0), D2)
    assert disk.docs["v1/history/usd"] == usd and "v1/history/usd" not in disk.writes
    assert disk.docs["v1/history/azadi"]["points"][0] == azadi["points"][0]
