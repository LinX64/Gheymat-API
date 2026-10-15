# CurrencyCapPortal

Static fallback API for [Gheymat](https://github.com/LinX64/Gheymat): a GitHub Actions workflow fetches
bonbast.com every six minutes and publishes JSON to GitHub Pages. The old website lives outside the repo
(`../CurrencyCapPortal-website-backup`).

| Path | Content |
|---|---|
| `/health` | status, last fetch time, mode `static` |
| `/v1/latest` | 37 instruments: buy/sell or price, toman unless `quote` is `usd` |
| `/v1/instruments` | instrument table with English and Persian names |
| `/v1/history/<code>` | every daily close since 2012-10-09 (currencies + coins), filled from bonbast's archive page 12 days per 6-minute run (the job loops for 5.5 hours and publishes every 6.5 minutes, an hourly cron queues the successor; about two days to reach 2012) |
| `/v1/longhistory/<code>` | coarse pre-2012 series (USD back to 1978, ~84 points) from the old archive, for the "All" chart range |
| `/v1/intraday/<code>` | last 7 days of 6-minute samples for every instrument (ts, buy, sell, price) |

Base URL: `https://linx64.github.io/CurrencyCapPortal`. Freshness is bounded by GitHub's cron (5 min nominal,
often longer); the real-time stream lives in the Gheymat server.

```bash
pip install -r requirements.txt
python tools/gheymat_snapshot.py --out dist --history
pytest -q
```
