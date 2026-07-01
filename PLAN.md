# letak-worker-tesco — Implementation Plan

## Overview
ProcMon Process Class (spec v1.0, type: `stdin`) that detects Tesco SK
leaflets (hypermarket "HM" / supermarket "SM") and reports new ones.

## Design decisions (locked)
- **Novelty**: stateless — caller passes `knownLeaflets` (keys); worker
  returns the ones not listed + `hasNew`.
- **Novelty key**: `type|from|to` (e.g. `HM|2026-07-01|2026-07-07`) — STABLE
  across PDF re-uploads. Type is needed because two leaflets (HM + SM) can
  share the same validity dates.
- **Output**: PDF entries `{type, from, to, url}` — no viewer URLs.
- **Scope**: URLs only; no PDF/asset downloading (left to a downstream step).
- **Source scope**: `props.pageProps.__APOLLO_STATE__` in the page's
  `__NEXT_DATA__` script — every `Leaflet:<id>` entity. Tesco's
  `validFrom`/`validTo` on that entity IS the real offer validity (unlike
  Kaufland, there's no separate "site display window" field to worry about).

## Status — DONE
```
manifest.json     # spec v1.0, knownLeaflets in / hasNew+leaflets out ...... DONE
Dockerfile        # python:3.12-slim, stdin entrypoint .................... DONE
Dockerfile.test   # protocol + parser + execute(fixture) tests ............ DONE
src/main.py       # ProcMon stdin/stdout protocol wrapper + LetakWorker ... DONE
src/tesco.py      # fetch + parse_leaflets + leaflet_key ................... DONE
tests/            # test_protocol.py, test_parser.py, fixtures/tesco.html . DONE
```
Verified live against the real page and offline against the fixture.

## How it works (implemented)
- Plain HTTP fetch (`urllib`) with a realistic header set (`Accept`,
  `Accept-Language`, `Sec-Fetch-*`) — the site is behind Akamai Bot Manager
  and returns a 403 "Access Denied" for a bare request with only
  `User-Agent`. No cookies/JS-challenge needed once headers look like a real
  navigation.
- `parse_leaflets`: regex-extract the `__NEXT_DATA__` script tag (its
  `nonce` attribute is random per request, so match on `id="__NEXT_DATA__"`
  only), `json.loads` it, walk `__APOLLO_STATE__` for `Leaflet:*` keys.
- `leaflet_key(type, from, to)`; new = `[l for l in leaflets if key(l) not in known]`.

## Open / future ideas
1. **Store-specific leaflets** — the overview page shows one HM + one SM
   leaflet (store-agnostic defaults). If per-store leaflets are ever needed,
   the page also embeds `availableStores` with per-store slugs — investigate
   `storeSlug` query param handling if that becomes a requirement.
2. **Other leaflet types** — only HM/SM observed so far; the parser doesn't
   hardcode a type whitelist, so any additional `Leaflet:*` entity Tesco adds
   is picked up automatically.
3. **Fixture refresh** — `tests/fixtures/tesco.html` is a snapshot; refresh
   if Tesco changes the Next.js data shape, and keep the parser tests green.

## Known operational risk — Akamai IP reputation
`fetch()` works reliably with a realistic header set from a normal host
network path (verified: direct `python3 src/main.py` on the dev machine
returns live HM/SM leaflets, exit 0). It was **blocked (403)** when run
inside a container on this machine's Docker Desktop (Windows/WSL2), even
with `--network host` — almost certainly an Akamai IP-reputation block tied
to that VM's shared NAT egress address, not a header/protocol problem (the
identical header set succeeds from the host). Whatever runs this worker in
production should be checked against a residential/datacenter IP that isn't
already on Akamai's block list for tesco.sk; if 403s show up in `/logs`,
that's the first thing to check before assuming the parser broke.

## Build / test
```bash
python tests/test_parser.py && python tests/test_protocol.py   # local
docker build -t letak-worker-tesco .
docker build -f Dockerfile.test -t letak-worker-tesco-test .
```
