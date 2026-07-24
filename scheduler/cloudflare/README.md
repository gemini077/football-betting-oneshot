# FBOS minute scheduler

This Worker only reads the public checkpoint registry and sends a targeted
`repository_dispatch` event. It does not run a model, place a bet, access an
account, or modify bankroll state.

The minute cron dispatches a checkpoint only during its planned minute. If the
registry is still non-terminal ten minutes later, it sends one bounded retry.
It does not continuously redispatch every overdue checkpoint. GitHub's slower
scheduled workflow remains the fallback for events missed outside both windows.

Required secret: `GITHUB_TOKEN`, scoped only to this repository and allowed to
send repository dispatch events. Deploy with Wrangler after setting the secret:

```bash
cd scheduler/cloudflare
npx wrangler secret put GITHUB_TOKEN
npx wrangler deploy
```

The `/health` endpoint performs the same bounded due check and returns JSON,
but never dispatches or changes state. `due` counts all overdue non-terminal
events; `dispatchable` counts only events currently inside a dispatch window.
