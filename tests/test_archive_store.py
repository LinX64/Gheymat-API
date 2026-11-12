import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import archive_store as a


def test_roundtrip_and_dedupe(tmp_path):
    assert a.load(tmp_path, "news") == []
    assert a.append(tmp_path, "news", {"date": "2026-11-02", "up": 1})
    assert a.append(tmp_path, "news", {"date": "2026-11-01", "up": 2})
    assert a.append(tmp_path, "news", {"date": "2026-11-02", "up": 5})
    recs = a.load(tmp_path, "news")
    assert [r["date"] for r in recs] == ["2026-11-01", "2026-11-02"]
    assert recs[1]["up"] == 5
    assert list((tmp_path / "archive").glob(".tmp-*")) == []


def test_corrupt_file_starts_empty_and_logs(tmp_path):
    p = tmp_path / "archive" / "news.json"
    p.parent.mkdir()
    p.write_text("{not json")
    logs = []
    assert a.load(tmp_path, "news", logs.append) == []
    assert logs
    assert a.append(tmp_path, "news", {"date": "2026-11-01"}, logs.append)
    assert len(a.load(tmp_path, "news")) == 1
    assert (tmp_path / "archive" / "news.json.corrupt").read_text() == "{not json"


def test_never_shrinks(tmp_path):
    for d in ("2026-11-01", "2026-11-02"):
        a.append(tmp_path, "news", {"date": d})
    before = (tmp_path / "archive" / "news.json").read_bytes()
    assert not a.write(tmp_path, "news", [{"date": "2026-11-01"}], 2, lambda m: None)
    assert (tmp_path / "archive" / "news.json").read_bytes() == before
    assert a.write(tmp_path, "news", [{"date": "2026-11-01"}, {"date": "2026-11-02"}], 2)


def test_bad_inputs(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        a.append(tmp_path, "news", {"up": 1})
    with pytest.raises(ValueError):
        a.load(tmp_path, "../x")


def test_ignored_by_assemble_site():
    import assemble_site
    assert "archive" in assemble_site.DROP
