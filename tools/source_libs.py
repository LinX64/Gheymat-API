from __future__ import annotations

import time

THIRD_MAP = {
    "usd": ("currency", "usd"),
    "eur": ("currency", "eur"),
    "gbp": ("currency", "gbp"),
    "try": ("currency", "try"),
    "aed": ("currency", "aed"),
    "cny": ("currency", "cny"),
    "inr": ("currency", "inr"),
    "sek": ("currency", "sek"),
    "omr": ("currency", "omr"),
    "gram": ("metal", "gold18"),
    "emami": ("metal", "seke_emam"),
    "azadi": ("metal", "seke_bahar"),
}
THIRD_CODES = frozenset(THIRD_MAP)


def _to_int(v) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n or None


def _row(ins: dict) -> dict:
    return {
        "code": ins["code"], "kind": ins["kind"], "unit": ins["unit"], "quote": ins["quote"],
        "buy": None, "sell": None, "price": None,
        "en": ins["en"], "fa": ins["fa"], "flag": ins["flag"], "computed": False,
        "buyRaw": None, "sellRaw": None,
    }


def snapshot_from_prices(prices, instruments: list[dict], now_iso: str, seq: int) -> dict:
    assets = {a.code.lower(): a for a in prices}
    rates = []
    for ins in instruments:
        if ins.get("computed"):
            continue
        key = ins.get("bonbast_key")
        if not key:
            continue
        asset = assets.get(key.lower())
        if asset is None:
            continue
        rate = _row(ins)
        if ins["kind"] in ("currency", "coin"):
            sell, buy = _to_int(getattr(asset, "sell", None)), _to_int(getattr(asset, "buy", None))
            if sell is None and buy is None:
                continue
            rate["sell"], rate["buy"] = sell, buy
        else:
            try:
                price = float(getattr(asset, "price", None))
            except (TypeError, ValueError):
                continue
            if not price:
                continue
            rate["price"] = price
        rates.append(rate)
    return {
        "seq": seq,
        "fetchedAt": now_iso,
        "sourceModified": prices.updated_at,
        "source": "bonbast",
        "flags": ["static"],
        "rates": rates,
    }


def fetch_bonbast_prices(ua: str, cookies: dict, *, source_error, blocked_error, timeout: float = 20):
    try:
        import bonbast
        import bonbast.errors
        import bonbast.token_cache
    except ImportError:
        raise source_error("live source failed") from None
    import requests
    import live_guard

    session = requests.Session()
    session.headers.update({"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
    session.cookies.update(cookies)
    client = bonbast.BonbastClient(
        session=session, token_cache=bonbast.token_cache.TokenCache(path=None), timeout=timeout)
    try:
        return client.prices()
    except bonbast.errors.ParseError as e:
        raise blocked_error("token" if "token" in str(e) else "format") from None
    except bonbast.errors.NetworkError as e:
        cause = e.__cause__
        if isinstance(cause, requests.HTTPError) and cause.response is not None:
            r = cause.response
            outcome, kind, retry_after = live_guard.classify_response(
                r.status_code, r.text[:2000], r.headers.get("Retry-After"))
            if outcome == "blocked":
                raise blocked_error(kind, retry_after) from None
            raise source_error("live source failed") from None
        if isinstance(cause, requests.RequestException):
            raise cause
        if cause is None and "token" in str(e):
            raise blocked_error("token") from None
        raise source_error("live source failed") from None
    except bonbast.errors.BonbastError:
        raise source_error("live source failed") from None
    finally:
        client.close()


def third_snapshot(instruments: list[dict], now_iso: str, seq: int, source_error,
                   budget_seconds: float = 25.0, max_calls: int = 14,
                   clock=time.monotonic, sleep_between: float = 0.0) -> dict:
    try:
        from gheymat import currency, metal
    except ImportError:
        raise source_error("no usable rows") from None
    modules = {"currency": currency, "metal": metal}
    by_code = {i["code"]: i for i in instruments}
    start = clock()
    calls = 0
    rates = []
    for code, (module, key) in THIRD_MAP.items():
        ins = by_code.get(code)
        if ins is None:
            continue
        if calls >= max_calls or clock() - start >= budget_seconds:
            break
        if calls and sleep_between > 0:
            time.sleep(sleep_between)
        calls += 1
        try:
            value = modules[module].get_price(key, toman=True)
            rate = _row(ins)
            if ins["kind"] == "gold":
                price = float(value)
                if not price > 0:
                    continue
                rate["price"] = price
            else:
                sell = _to_int(value)
                if sell is None:
                    continue
                rate["sell"] = sell
        except Exception:
            continue
        rates.append(rate)
    if not rates:
        raise source_error("no usable rows")
    return {
        "seq": seq,
        "fetchedAt": now_iso,
        "sourceModified": None,
        "source": "third",
        "flags": ["static"],
        "rates": rates,
    }
