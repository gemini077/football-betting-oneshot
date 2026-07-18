# FBOS minute scheduler

This Worker only reads the public checkpoint registry and sends a targeted
`repository_dispatch` event. It does not run a model, place a bet, access an
account, or modify bankroll state.

Required secret: `GITHUB_TOKEN`, scoped only to this repository and allowed to
send repository dispatch events. Deploy with Wrangler after setting the secret:

```bash
cd scheduler/cloudflare
npx wrangler secret put GITHUB_TOKEN
npx wrangler deploy
```

The `/health` endpoint performs the same bounded due check and returns JSON,
but never dispatches or changes state.
