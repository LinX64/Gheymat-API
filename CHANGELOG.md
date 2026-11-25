# Changelog

## 1.8.0 (2026-11-25)

Feed for the 1.8 wave. Clients: iOS 1.8.1 (build assigned by App Store Connect), Android 1.8.0 (build 8). Wire shapes only gain documents and optional fields that both clients already decode.

### Added
- Forecast track record filled from live results, and a `confidence` field on each forecast (`normal` or `low` with factual reasons) (#48, #50).
- Dated headline archive document `v1/ai/news-archive` (#57).
- Gold and coin daily closes, including gram, mithqal and ounce histories (#57).
- Daily accuracy report built from real history, encrypted to the owner, with the pre-registered method-switch verdict (#54, #56).
- Last live price per day kept encrypted in carried state (#52).
- Offline studies of range coverage by volatility state, a non-default volatility variant and a permutation test (#49, #53).
- Optional second news source list from a repository secret (#63).

### Changed
- News keeps the 40 most relevant items of the last 48 hours instead of the 40 newest; still published newest first. Summaries run in parallel, numbers are compared in normalised form, and failed stories are not retried for 6 hours. Wider keyword list (#63).
- Brief: forecast cards start with the dollar, news cards are the most relevant items, and a short sentence marks a record close or a sharp weekly move of the dollar (#63).
- The Cloudflare scheduler is the only trigger of the publish workflow. No idle runs, no run-to-run chaining, no GitHub watchdog. The daily report runs from its own scheduled workflow (#62).
- The news step's log lines are visible in the run log (#62).
- The lead parser accepts numbers with thousands separators (#55).

### Fixed
- The forecast track log is encrypted at rest (#51).

### Removed
- Idle job, run chaining and the watchdog workflow (#62).
