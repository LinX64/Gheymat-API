import importlib.util
import pathlib

SPEC = importlib.util.spec_from_file_location(
    "gheymat_snapshot", pathlib.Path(__file__).resolve().parents[1] / "tools" / "gheymat_snapshot.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

INS = [{"code": "usd", "kind": "currency"}, {"code": "gram", "kind": "gold"},
       {"code": "emami", "kind": "coin"}, {"code": "btc", "kind": "crypto"}]


def rows(**over):
    base = {"usd": (1, 2, None), "gram": (None, None, 5), "emami": (3, 4, None), "btc": (None, None, 9)}
    base.update(over)
    return [{"code": c, "buy": b, "sell": s, "price": p} for c, (b, s, p) in base.items()]


def line(prev, cur):
    return mod.changed_rows_line(prev, cur, INS)


def test_unchanged_is_zeros():
    assert line({"rates": rows()}, rows()) == "Changed rows: currency 0, gold 0, coin 0, crypto 0 (of 4)"


def test_one_of_each_kind():
    cur = rows(usd=(1, 3, None), gram=(None, None, 6), emami=(3, 5, None), btc=(None, None, 10))
    assert line({"rates": rows()}, cur) == "Changed rows: currency 1, gold 1, coin 1, crypto 1 (of 4)"


def test_new_code_counts_as_changed():
    prev = [r for r in rows() if r["code"] != "btc"]
    assert "crypto 1" in line({"rates": prev}, rows())


def test_first_run():
    assert line(None, rows()) == "Changed rows: n/a (first run)"
    assert line({"rates": []}, rows()) == "Changed rows: n/a (first run)"


def test_unknown_code_is_other():
    cur = rows() + [{"code": "zzz", "buy": 1, "sell": 1, "price": None}]
    assert line({"rates": rows()}, cur).endswith("crypto 0, other 1 (of 5)")
