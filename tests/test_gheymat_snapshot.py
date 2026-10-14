import importlib.util
import pathlib

SPEC = importlib.util.spec_from_file_location(
    "gheymat_snapshot", pathlib.Path(__file__).resolve().parents[1] / "tools" / "gheymat_snapshot.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

RAW = {
    "usd1": "265200", "usd2": "265000", "eur1": "294800", "eur2": "294600", "jpy1": "17750", "jpy2": "17700",
    "emami1": "268000000", "emami12": "265000000", "azadi1": "258000000", "azadi12": "253000000",
    "gol18": "26136940", "mithqal": "113220000", "ounce": "4094.2", "bitcoin": "81476.39",
    "last_modified": "October 14, 2026 19:06", "created": "x", "hour": "22", "minute": "36",
}


def test_build_snapshot_maps_currency_coin_gold_and_crypto():
    snap = mod.build_snapshot(RAW, mod.load_instruments())
    by = {r["code"]: r for r in snap["rates"]}
    assert by["usd"]["buy"] == 265000 and by["usd"]["sell"] == 265200
    assert by["jpy"]["unit"] == 10
    assert by["emami"]["buy"] == 265000000 and by["emami"]["sell"] == 268000000
    assert by["gram"]["price"] == 26136940 and by["gram"]["buy"] is None
    assert by["ounce"]["quote"] == "usd" and by["btc"]["price"] == 81476.39
    assert snap["sourceModified"] == "October 14, 2026 19:06"
    assert "gbp" not in by



def test_refuses_thin_payload():
    snap = mod.build_snapshot({"usd1": "1", "usd2": "1"}, mod.load_instruments())
    assert len(snap["rates"]) < 29


def test_intraday_appends_and_trims(tmp_path):
    snap = mod.build_snapshot(RAW, mod.load_instruments())
    old = {"code": "usd", "days": 7, "points": [
        {"ts": "2026-09-01T00:00:00Z", "buy": 1, "sell": 2, "price": None},
        {"ts": "2026-10-14T20:00:00Z", "buy": 264000, "sell": 264200, "price": None},
    ]}
    (tmp_path / "v1" / "intraday").mkdir(parents=True)
    (tmp_path / "v1" / "intraday" / "usd").write_text(__import__("json").dumps(old), encoding="utf-8")
    assert mod.append_intraday(tmp_path, snap) == len(snap["rates"])
    usd = __import__("json").loads((tmp_path / "v1" / "intraday" / "usd").read_text(encoding="utf-8"))
    assert [p["ts"] for p in usd["points"]][0] == "2026-10-14T20:00:00Z"
    assert usd["points"][-1]["sell"] == 265200
    assert mod.append_intraday(tmp_path, snap) == 0
