# CurrencyCapPortal

Static API for [Gheymat](https://github.com/LinX64/Gheymat): a GitHub Actions workflow fetches its sources
every six minutes (`GHEYMAT_SOURCES`, default hansha.online first, bonbast.com filling what hansha lacks and
taking over when it fails or goes stale), combines them per instrument and publishes sealed JSON to GitHub
Pages. The app reads only that JSON. The old website lives outside the repo (`../CurrencyCapPortal-website-backup`).

| Path | Content |
|---|---|
| `/health` | status, last fetch time, mode `static` |
| `/v1/latest` | up to 51 instruments: 37 direct, up to 8 computed cross-rates (`computed: true`) and up to 6 hansha-only crypto rows (eth, xrp, bch, ltc, bnb, usdt, toman-quoted); buy/sell or price, toman unless `quote` is `usd`. Optional rows may be missing on a given publish (Gheymat's `CONTRACT.md`, "Computed cross-rates" and "Static publisher sources") |
| `/v1/instruments` | instrument table with English and Persian names |
| `/v1/history/<code>` | daily closes for currencies and coins from bonbast's archive, 12 days per publish (the job loops for 5.5 hours, checks hansha every 30 s and publishes within about a minute of a hansha update, at most every 2 minutes and at least every 6; a 15-minute cron queues the successor); the published series starts 2018-03-28 (verified 2026-10-19, backfill toward 2012-10-09 unfinished, so no pre-2018 claims until `health.archiveDays` proves it). Gold, crypto and computed cross-rates have none; the app itself charts daily history for the 28 direct currencies only |
| `/v1/longhistory/<code>` | coarse long series (USD back to 1978, ~84 points) from the old archive, for the "All" chart range, scaled to the instrument's unit |
| `/v1/intraday/<code>` | last 7 days of 6-minute samples for every instrument (ts, buy, sell, price); computed cross-rate codes are excluded |

Base URL: `https://linx64.github.io/CurrencyCapPortal`. Freshness is bounded by the Actions publish loop
(within about a minute of a hansha update, at least every 6 min); there is no real-time stream, the app polls.

```bash
pip install -r requirements.txt
python tools/gheymat_snapshot.py --out dist --history
pytest -q
```
