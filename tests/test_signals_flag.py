import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gheymat_ai as ai
import gheymat_blend as blend


class Boom:
    def get(self, *a, **k):
        raise AssertionError("signals must not be fetched while the flag is off")


def test_signals_are_off_by_default_and_never_fetched():
    assert ai.SIGNALS_ENABLED is False
    calls = []

    def writer(logical, doc):
        calls.append(logical)

    ai.run_step({"codes": {}}, writer, lambda _: None, None, signals_http=Boom(), archive_root=None)


def test_signal_keys_emitted_by_blend_are_documented_in_the_contract_enum_or_flagged():
    known = {"oil", "sanctions", "politics", "closure"}
    emitted = {spec["signal"] for spec in blend.VARIANTS if spec.get("signal")}
    assert emitted - known == {"usd", "news"}
