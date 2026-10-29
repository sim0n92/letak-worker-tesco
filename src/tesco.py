"""
Tesco SK leaflet page parsing.

Pure, network-light helpers so the parser can be unit-tested against a saved
HTML fixture. Only the standard library is used.

Page model (https://www.tesco.sk/akciove-ponuky/letaky-a-katalogy):
  - The page is server-rendered by Next.js. The full leaflet catalogue lives
    in the Apollo GraphQL cache embedded as JSON in
    `<script id="__NEXT_DATA__">...</script>` -- no HTML scraping of tiles
    needed, no headless browser needed (plain HTTP GET returns it).
  - `props.pageProps.__APOLLO_STATE__` is a flat entity map; every key of the
    form `Leaflet:<id>` is one leaflet, e.g.:
      { "type": "HM", "slug": "tesco-letak-2026-07-01",
        "validFrom": "2026-07-01T06:00:00.000Z",
        "validTo": "2026-07-07T21:59:59.000Z",
        "leafletUrl": "https://digitalcontent.api.tesco.com/.../....pdf" }
  - `validFrom`/`validTo` on the Leaflet entity ARE the real offer validity
    (Tesco does not expose a separate "site display window" the way Kaufland
    does) -- truncate the ISO datetime to a date and use it directly.
  - `type` distinguishes leaflet formats (e.g. "HM" hypermarket, "SM"
    supermarket); part of the novelty key since two leaflets can share dates.
  - The site is behind Akamai Bot Manager: a bare urllib request with no
    `Accept`/`Sec-Fetch-*` headers gets a 403 "Access Denied" from the edge.
    A realistic header set (see `fetch`) is sufficient -- no JS challenge,
    no cookies required.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
import re
import urllib.request

DEFAULT_URL = "https://www.tesco.sk/akciove-ponuky/letaky-a-katalogy"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def fetch(url: str = DEFAULT_URL, timeout: int = 30) -> str:
    """Fetch the leaflet page HTML as a UTF-8 string.

    No Accept-Encoding is sent so the response comes back uncompressed --
    keeps this stdlib-only (no manual gzip handling).
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Dest": "document",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


# The page's own data source (APOLLO_URL in __NEXT_DATA__). Unlike www.tesco.sk it is NOT behind Akamai Bot
# Manager's TLS fingerprinting: from a Linux container the page answers 403 to urllib and curl alike
# (2026-07..10, every ProcMon run failed), the API answers 200.
API_URL = "https://api.prod.retail.tesco.com/marketing/leaflets-be/graphql"
_LEAFLETS_QUERY = """query getValidLeafletList($country: CountryCode!, $currentDate: DateTime!, $storeType: LeafletType) {
  leaflets(options: {filter: {country: {eq: $country}, validTo: {after: $currentDate}, type: {eq: $storeType}}}) {
    items { id slug leafletUrl validFrom validTo type }
    totalItems
  }
}"""


def fetch_api(api_url: str = API_URL, current_date: str = "", timeout: int = 30) -> dict:
    """The currently valid SK leaflets from the GraphQL API (a file:// URL is read as the saved response)."""
    if api_url.startswith("file:"):
        with urllib.request.urlopen(api_url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    body = json.dumps({"operationName": "getValidLeafletList", "query": _LEAFLETS_QUERY,
                       "variables": {"country": "sk", "currentDate": current_date}}).encode("utf-8")
    req = urllib.request.Request(api_url, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": _USER_AGENT,
        "Origin": "https://www.tesco.sk", "Referer": DEFAULT_URL,
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_api(data: dict) -> list[dict]:
    """GraphQL response -> leaflets {id, type, slug, validFrom, validTo, pdfUrl}."""
    if data.get("errors"):
        raise ValueError(f"GraphQL errors: {data['errors'][0].get('message')}")
    items = (((data.get("data") or {}).get("leaflets")) or {}).get("items")
    if items is None:
        raise ValueError("no data.leaflets.items in the API response")
    return [{
        "id": it.get("id"),
        "type": it.get("type"),
        "slug": it.get("slug"),
        "validFrom": _iso_date(it.get("validFrom")),
        "validTo": _iso_date(it.get("validTo")),
        "pdfUrl": it.get("leafletUrl"),
    } for it in items if it.get("leafletUrl")]


def leaflet_key(type_: str | None, valid_from: str | None,
                valid_to: str | None) -> str:
    """Stable novelty key: leaflet type + validity range.

    Independent of the PDF URL (which carries a UUID that changes on
    re-upload). Type is part of the key because two leaflets (e.g. HM and
    SM) can share the same validity dates.

        leaflet_key("HM", "2026-07-01", "2026-07-07") -> "HM|2026-07-01|2026-07-07"
    """
    return f"{type_}|{valid_from}|{valid_to}"


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _iso_date(dt: str | None) -> str | None:
    """'2026-07-01T06:00:00.000Z' -> '2026-07-01': the calendar date in Slovakia (CET/CEST), not in UTC —
    a leaflet valid from local midnight starts at 22:00/23:00 UTC of the previous day."""
    if not dt or len(dt) < 10:
        return None
    try:
        t = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError:
        return dt[:10]
    if t.tzinfo is None:
        return t.date().isoformat()
    t = t.astimezone(timezone.utc).replace(tzinfo=None)
    # EU summer time: last Sunday of March 01:00 UTC .. last Sunday of October 01:00 UTC
    summer = datetime.combine(_last_sunday(t.year, 3), datetime.min.time()) + timedelta(hours=1) <= t \
        < datetime.combine(_last_sunday(t.year, 10), datetime.min.time()) + timedelta(hours=1)
    return (t + timedelta(hours=2 if summer else 1)).date().isoformat()


def _next_data(doc: str) -> dict:
    m = _NEXT_DATA_RE.search(doc)
    if not m:
        raise ValueError("__NEXT_DATA__ script tag not found")
    return json.loads(m.group(1))


def parse_leaflets(doc: str) -> list[dict]:
    """Parse leaflets from the __NEXT_DATA__ Apollo cache.

    Each item: {id, type, slug, validFrom, validTo, pdfUrl}.
    """
    apollo = (
        _next_data(doc)
        .get("props", {})
        .get("pageProps", {})
        .get("__APOLLO_STATE__", {})
    )
    leaflets: list[dict] = []
    for key, entity in apollo.items():
        if not key.startswith("Leaflet:") or not isinstance(entity, dict):
            continue
        pdf_url = entity.get("leafletUrl")
        if not pdf_url:
            continue
        leaflets.append({
            "id": entity.get("id"),
            "type": entity.get("type"),
            "slug": entity.get("slug"),
            "validFrom": _iso_date(entity.get("validFrom")),
            "validTo": _iso_date(entity.get("validTo")),
            "pdfUrl": pdf_url,
        })
    return leaflets
