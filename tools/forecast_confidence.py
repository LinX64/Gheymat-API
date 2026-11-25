from __future__ import annotations

import math

REASONS = ("unusual", "band-broken", "moved-since-basis")
MOVE_FRACTION = 0.25
MAX_LIVE_RATIO = 2.0


def usable(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def prior_reasons(previous) -> set:
    if not isinstance(previous, dict) or not isinstance(previous.get("reasons"), list):
        return set()
    return {r for r in previous["reasons"] if r in REASONS}


def build_confidence(doc: dict, live, previous=None) -> dict:
    found = prior_reasons(previous)
    if doc.get("unusual") is True:
        found.add("unusual")
    low, high = doc.get("low"), doc.get("high")
    basis = doc.get("basis")
    basis_price = basis.get("price") if isinstance(basis, dict) else None
    if (usable(live) and usable(low) and usable(high) and high >= low and usable(basis_price)
            and 1 / MAX_LIVE_RATIO <= live / basis_price <= MAX_LIVE_RATIO):
        if live < low or live > high:
            found.add("band-broken")
        elif "band-broken" not in found and abs(math.log(live / basis_price)) > MOVE_FRACTION * math.log(high / low):
            found.add("moved-since-basis")
    if "band-broken" in found:
        found.discard("moved-since-basis")
    reasons = [r for r in REASONS if r in found]
    return {"level": "low" if reasons else "normal", "reasons": reasons}


def same_basis(a, b) -> bool:
    return isinstance(a, dict) and isinstance(b, dict) and a.get("basis") == b.get("basis")


def safe_confidence(doc: dict, live, previous_doc, log=print):
    try:
        carried = previous_doc.get("confidence") if same_basis(doc, previous_doc) else None
        return build_confidence(doc, live, carried)
    except Exception as e:
        log(f"ai: confidence skipped: {type(e).__name__}")
        return None
