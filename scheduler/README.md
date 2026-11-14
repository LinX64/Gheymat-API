# Publish scheduler

A Cloudflare Worker that starts the publish workflow on a one-minute cron. Each minute it checks whether a publish run is already active and whether the publishing window is open. If no run is active and the window is open, it dispatches the publish workflow. Otherwise it does nothing.

The workflow's own gate job stays authoritative. It still decides whether to publish, so the Worker only starts runs; it never publishes on its own.

## Why

GitHub's scheduler fires rarely, so the publish chain could go quiet for long stretches. The Worker's cron runs every minute and keeps the chain started inside the window.

## Shape

- Scheduled handler only. There is no public URL: `workers_dev` is off.
- Files: `index.js` (the handler), `wrangler.toml` (cron trigger and settings), `package.json` (module type only, no dependencies), `test/scheduler.test.js` (node tests), and this README.
- The window logic is kept in sync with `tools/cadence.py`. `tests/make_window_cases.py` generates `tests/fixtures/window_cases.json` from `cadence.in_window`, and both `pytest` (`tests/test_window_fixture.py`) and `node --test scheduler/test/*.test.js` check the Worker against that same fixture. Regenerate the fixture after any change to the window rules.

## Behaviour

- Inside the window, each minute: if any run of the publish workflow is active (created in the last 10 minutes and not completed), do nothing (`active`).
- If the newest run ended red or timed out in the last 10 minutes, wait (`backoff`), so a persistent failure does not become one red run a minute.
- Otherwise dispatch the workflow on `master` (`dispatched`). Outside the window it makes no calls (`closed`).
- Any `error:*` result makes the cron invocation fail, so it shows as a failure in the Worker's Cron Events. `error:401` or `error:403` usually means the token expired.
- `HOURS` in `wrangler.toml` mirrors the repository variable `GHEYMAT_HOURS`. Change both together.

## Owner steps

The agent cannot do these steps. Run them yourself.

1. Confirm the Cloudflare account has a free cron trigger slot. The free plan allows 5 cron triggers per account.
2. Create a fine-grained GitHub token: resource owner `LinX64`, only the repository `Gheymat-API`, repository permission Actions read and write (Metadata read is added automatically), and an expiry date. Put the expiry in your calendar.
3. From `scheduler/`, run `npx wrangler login`, then `npx wrangler deploy`.
4. Copy the token, then run `pbpaste | npx wrangler secret put GH_DISPATCH_TOKEN`, then clear the clipboard. Never type the token on a command line and never commit it.
5. In the GitHub Actions tab, check that runs with the event `workflow_dispatch` appear when the chain is idle. In the Cloudflare dashboard, open the Worker's logs or Cron Events and check for `active`, `dispatched` or `backoff` each minute inside the window.
6. Renewal: when the token expires the Worker reports `error:401`. Create a new token and repeat step 4.
7. Rollback: run `npx wrangler delete`. The old chain and the watchdog stay in place and keep working.

## Stage note

The old chain, the idle runs and the watchdog are intentionally unchanged in this stage. They are removed in a later change, after the Worker has run cleanly inside the window for several days.
