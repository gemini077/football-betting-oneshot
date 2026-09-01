# CURRENT-UNIVERSE-ROLLOVER-1 — Bounded Source Probe

Status: `READY_FOR_ACCEPTANCE / NO CODE`

Decision: `WAF_BLOCK / NO_CODE`

Target business date: `2026-09-01` (Asia/Shanghai)

## Production evidence

The two supplied production cycles both ran on GitHub-hosted Ubuntu runners and
ended with the same fail-closed projection:

| Run | Main SHA | Current universe | BASE jobs | BASE prediction | Durability |
| --- | --- | ---: | --- | --- | --- |
| [33431411824](https://github.com/gemini077/football-betting-oneshot/actions/runs/33431411824) | `86c743019cc4e26193d4f5185f3dd9da5c82d9ab` | 0 | `BLOCKED_UNIVERSE` | `BLOCKED_UNIVERSE` | `UPSTREAM_GENERATION_NOT_COMPLETE` |
| [33450251359](https://github.com/gemini077/football-betting-oneshot/actions/runs/33450251359) | `94c985a9f03f481bcb9d4f1f49f2d1c74d3eafec` | 0 | `BLOCKED_UNIVERSE` | `BLOCKED_UNIVERSE` | `UPSTREAM_GENERATION_NOT_COMPLETE` |

No production durable state was changed by this milestone.

## GitHub-runner probe

The bounded probe ran once per route in [run 33455183881](https://github.com/gemini077/football-betting-oneshot/actions/runs/33455183881),
on branch commit `199ea36537693fad900e5f1d1608b543b323cbbd`, using
`Linux-6.17.0-1022-azure-x86_64-with-glibc2.39` and Python `3.12.14`.

The exact JSON artifact is preserved at
`CURRENT-UNIVERSE-ROLLOVER-1_PROBE_RUN_33455183881.json`. The probe policy was
one request per route, no retry, and no production-state write. Its SHA-256 is
`C7CE80D034630105B9DDB21083013CB48F2BF61BDF6BEC38E9226AC14FC34B03`.

| Probe | URL contract | HTTP | Response | Success | Available business dates | Target rows | Sample IDs / numbers | WAF/block evidence |
| --- | --- | ---: | --- | --- | --- | ---: | --- | --- |
| A repo route/current headers | `uniform/getMatchCalculatorV1.qry?channel=tycp` | 567 | HTML | false | `[]` | 0 | none | HTTP 567 + EdgeOne security-policy block page |
| A repo route/official page headers | same URL | 567 | HTML | false | `[]` | 0 | none | HTTP 567 + EdgeOne security-policy block page |
| B `jc` match list | `jc/getMatchListV1.qry?clientCode=3001` | 567 | HTML | false | `[]` | 0 | none | HTTP 567 + EdgeOne security-policy block page |
| B `uniform` match list | `uniform/getMatchListV1.qry?clientCode=3001` | 567 | HTML | false | `[]` | 0 | none | HTTP 567 + EdgeOne security-policy block page |
| C `jc` calculator | `jc/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu` | 567 | HTML | false | `[]` | 0 | none | HTTP 567 + EdgeOne security-policy block page |
| C `uniform` calculator | `uniform/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu` | 567 | HTML | false | `[]` | 0 | none | HTTP 567 + EdgeOne security-policy block page |
| D current 500 trade page | `trade.500.com/jczq/?playid=312&g=2` | 200 | HTML | false | `[]` | 0 | none | HTTP 200 challenge HTML; `challenge`/`validate` fields; no match rows |

### 500-specific facts

- Raw match rows: `0`.
- `data-processdate` values: none.
- `data-matchdate` values: none.
- Target business-date rows: `0`.
- Target match-date rows: `0`.
- Current parser target rows: `0`.

The 500 response is an access challenge, not a valid empty schedule. Therefore
the probe does not establish either `SOURCE_ROLLOVER_LAG` or
`BUSINESS_DATE_FILTER_BUG`.

## Classification and gate

The deterministic result is `WAF_BLOCK`:

1. Every official Sporttery route, including the same repo route with official
   mobile-page headers, returned HTTP 567 HTML containing the EdgeOne security
   policy block marker.
2. The 500 page returned HTTP 200 but contained the challenge page and zero raw
   match rows, so it supplies no production schedule evidence.
3. No same-provider official route returned a target-date row. The
   `STALE_ENDPOINT_CONTRACT` and `WRONG_CHANNEL_OR_POOL_CONTRACT` gates are not
   proven.
4. No valid 500 row reached the parser, so no parser-only fix is proven.

Decision gate: `NO_CODE`. Keep the existing Sporttery primary route,
fail-closed universe behavior, Champion, identity, frozen history, and
prospective records unchanged. Do not inject fixtures or add a provider.

## Research-only route seeds

Open-source implementations were used only to expand the bounded probe
candidate list; they are not production providers: [soccer-forecast match-list
example](https://github.com/zhijiang-marionette/soccer-forecast/blob/main/crawler.py),
[SportteryAPI upstream contract](https://github.com/Johnserf-Seed/SportteryAPI/blob/main/src/upstream.ts),
and [public calculator contract notes](https://github.com/wang-zjin/World-Cup-Forecast/blob/main/%E4%BD%93%E5%BD%A9%E8%B6%B3%E7%90%83%E8%B5%94%E7%8E%87%E6%95%B0%E6%8D%AE%E8%8E%B7%E5%8F%96.md).
