# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

`letak-worker-tesco` is a **ProcMon Process Class** (spec v1.0, type `stdin`)
that parses the Tesco SK leaflet page and reports leaflets that are not in
the caller-supplied `knownLeaflets` list. Stateless; metadata + URLs only
(no downloads).

- **Protocol contract** lives in the `ProcessMonitor` repo:
  `docs/process-class-specification-v1.md` (org `0ics-srls`).
- **Reference implementation** of a sibling class: `sim0n92/letak-worker-kaufland`
  (same protocol; different site, same `main.py` shape).

## Contract (do not break)

- stdin: one JSON line with `_action`; stays open for a later `terminate`.
- stdout: JSON Lines, **only** `{type:progress|result|error}` — never logs.
- logs: `/logs/events.log`, Serilog-style, honor `LOG_LEVEL`.
- exit: 0 success (must emit `result`), 1 error, 2 input error, 4 dependency error.
- `--version` must equal `manifest.json#version`.

## Where to work

- Page fetch + parsing lives in `src/tesco.py` (pure functions, unit-tested
  against `tests/fixtures/tesco.html` and `tests/fixtures/tesco_api.json`). The protocol plumbing is in
  `src/main.py` (`ProcessClass`); `LetakWorker.execute()` wires the two.
- The leaflet catalogue comes from the site's own GraphQL API
  (`tesco.API_URL`, query `getValidLeafletList`, country `sk`) — the primary
  source since 2026-10. www.tesco.sk sits behind Akamai Bot Manager, which
  fingerprints the TLS client: from a Linux container the page answers 403 to
  urllib and curl alike (every ProcMon run failed 2026-07..10), the API answers 200.
- Fallback: the page's Next.js `<script id="__NEXT_DATA__">` JSON blob
  (`props.pageProps.__APOLLO_STATE__`, every `Leaflet:<id>` entity), with a
  realistic `Accept`/`Sec-Fetch-*` header set. `pageUrl` alone (tests) reads
  only the page.
- Validity: `validFrom`/`validTo` are UTC instants; `_iso_date` turns them into
  the Slovak calendar date (CET/CEST), not the UTC date.
- No leaflets at all is `NO_LEAFLETS` (exit 4) — never "Completed, 0 leaflets".
- Keep `manifest.json` input/output schemas in sync with `execute`.
- If Tesco changes markup/data shape, refresh the fixture and keep parser
  tests green.

## Build / test

```bash
python tests/test_parser.py                         # offline parser tests
python tests/test_protocol.py                       # protocol + execute tests
docker build -t letak-worker-tesco .                 # production image
docker build -f Dockerfile.test -t lwt-test .        # in-container tests
```
