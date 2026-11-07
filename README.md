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
| `/v1/history/<code>` | every daily close since 2012-10-09 (currencies + coins), filled from bonbast's archive page 12 days per publish (the job loops for 5.5 hours and publishes every 6 minutes, an hourly cron queues the successor; about 2 days to reach 2012) |
| `/v1/longhistory/<code>` | coarse pre-2012 series (USD back to 1978, ~84 points) from the old archive, for the "All" chart range |
| `/v1/intraday/<code>` | last 7 days of 6-minute samples for every instrument (ts, buy, sell, price); computed cross-rate codes are excluded |

Base URL: `https://linx64.github.io/CurrencyCapPortal`. Freshness is bounded by the Actions publish loop
(~6 min nominal, often longer under GitHub Pages' build queue); the real-time stream lives in the Gheymat
server.

```bash
pip install -r requirements.txt
python tools/gheymat_snapshot.py --out dist --history
pytest -q
```
