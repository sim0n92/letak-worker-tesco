# letak-worker-tesco

ProcMon Process Class (spec v1.0, type: `stdin`) that detects Tesco SK
promotional leaflets ("letaky") and reports the ones that are new.

> Protocol contract: `ProcessMonitor/docs/process-class-specification-v1.md`.
> Reference implementation of a sibling class: `sim0n92/letak-worker-kaufland`.

## How It Works

1. Receives a JSON message on stdin with `_action: "execute"`.
2. Fetches the leaflet page
   (`https://www.tesco.sk/akciove-ponuky/letaky-a-katalogy`) and reads the
   leaflet catalogue directly out of the page's embedded Next.js data
   (`<script id="__NEXT_DATA__">` → `__APOLLO_STATE__` → every `Leaflet:<id>`
   entity) — no HTML tile-scraping, no headless browser.
3. Each leaflet has a **stable key** = `type|from|to`
   (e.g. `HM|2026-07-01|2026-07-07`) — independent of the PDF URL, which
   carries a UUID that changes on re-upload. Any leaflet whose key is not in
   the `knownLeaflets` input list is reported as **new**.
4. Writes the result to `outputPath` and emits a `result` with `hasNew` +
   `leaflets` (each entry `{type, from, to, url}`, where `url` is the
   downloadable PDF).
5. Logs diagnostics to `/logs/events.log` (honoring `LOG_LEVEL`).

The worker is **stateless**: novelty is decided purely from the
`knownLeaflets` list supplied by the caller.

## Build

```bash
docker build -t letak-worker-tesco .
```

## Test

```bash
docker build -f Dockerfile.test -t letak-worker-tesco-test .
```

## Run

```bash
echo '{"_action":"execute","outputPath":"/out/leaflets.json","knownLeaflets":[]}' \
  | docker run -i -v "$PWD/out:/out" -v "$PWD/logs:/logs" letak-worker-tesco
```

## Protocol

### Input (stdin JSON)

| Field           | Type     | Required | Description |
|-----------------|----------|----------|-------------|
| `_action`       | string   | yes      | `execute` or `terminate` (system-injected) |
| `outputPath`    | string   | yes      | Absolute path for the result JSON |
| `knownLeaflets` | string[] | no       | Keys already seen (`type|from|to`); anything not listed is "new" |
| `types`         | string[] | no       | Case-insensitive type filter (e.g. `["HM"]`); empty/absent = all types |
| `pageUrl`       | string   | no       | Override leaflet page URL (default SK page) |
| `customData`    | object   | no       | Source-specific hints |
| `_meta`         | object   | no       | Execution metadata (system-injected) |

### Output (stdout JSON Lines)

- `{"type":"progress","percent":N,"message":"..."}` — progress (percent may be `null`)
- `{"type":"result","data":{...}}` — final result with:
  `outputPath`, `count`, `hasNew`, `leaflets[]`, `fileSize`
- `{"type":"error","code":"...","message":"...","data":{...}}` — managed error

Each `leaflets` entry is `{type, from, to, url}`, where `url` is the
**directly downloadable PDF**. The full leaflet list is also written to
`outputPath`. Novelty key = `type|from|to`; feed the keys of leaflets you've
handled back via `knownLeaflets` on the next run.

### Result example

```json
{"type":"result","data":{"count":1,"hasNew":true,
  "leaflets":[{"type":"HM","from":"2026-07-01","to":"2026-07-07",
          "url":"https://digitalcontent.api.tesco.com/v2/media/dotcom-hu/.../....pdf"}],
  "outputPath":"/out/leaflets.json","fileSize":210}}
```

A downstream program just GETs each `leaflets[].url` (public, no auth):

```python
import json, urllib.request
data = json.loads(result_stdout)["data"]        # or json.load(open(outputPath))
for item in data["leaflets"]:
    url = item["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(url.rsplit("/", 1)[-1], "wb") as f:
        f.write(r.read())
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0    | Success (a `result` was emitted) |
| 1    | Generic error |
| 2    | Input error |
| 3    | Timeout (killed by wrapper) |
| 4    | Dependency error (upstream/network/markup change) |

## Environment

| Variable     | Default | Description |
|--------------|---------|-------------|
| `LOG_LEVEL`  | `Info`  | `Debug` / `Info` / `Warning` / `Error` |
| `EXECUTION_ID` | –     | Execution UUID (system-provided) |
| `LOG_DIR`    | `/logs` | Log directory (override for local dev) |

## Layout

```
letak-worker-tesco/
├── manifest.json         # ProcMon manifest (spec v1.0)
├── Dockerfile            # Production image
├── Dockerfile.test       # Protocol + parser test image
├── requirements.txt      # stdlib-only at runtime
├── src/
│   ├── main.py           # stdin/stdout protocol wrapper + LetakWorker
│   └── tesco.py           # page fetch + leaflet parsing (pure, testable)
└── tests/
    ├── test_protocol.py  # protocol + execute behaviour
    ├── test_parser.py    # offline parser tests
    └── fixtures/tesco.html
```

## Local development

```bash
python tests/test_parser.py     # offline parser tests (uses fixture)
python tests/test_protocol.py   # protocol + execute tests (offline via file://)
```
