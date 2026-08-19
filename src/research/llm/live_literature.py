"""Bounded live literature lookup for the explicitly non-PIT S4 study.

This module is intentionally separate from ``literature_registry``.  It is
not historical evidence: a 2022 replay can see material indexed today.  Its
sole purpose is to test whether web-assisted LLM factor selection is useful.
Every successful or failed lookup is snapshotted before model use so an S4
decision can still be replayed from the local cache.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_STATE_QUERIES = {
    "S1_trend": "stock market trend momentum factor",
    "S2_stress": "stock market volatility drawdown liquidity factor",
    "S3_range_or_uncertain": "stock market reversal contrarian liquidity factor",
}


def _fetch_json(url: str, *, timeout_seconds: float = 12.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "mystock-research/0.1 (educational research)"})
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: fixed public API endpoint
        return json.loads(response.read().decode("utf-8"))


def _normalise_item(item: dict[str, Any]) -> dict[str, str]:
    titles = item.get("title") or []
    published = (
        item.get("published-online", {}).get("date-parts")
        or item.get("published-print", {}).get("date-parts")
        or item.get("issued", {}).get("date-parts")
        or [[None]]
    )
    date_parts = published[0]
    date = "-".join(str(part).zfill(2) for part in date_parts if part is not None) or "unknown"
    doi = str(item.get("DOI", ""))
    return {
        "source_id": f"crossref:{doi}" if doi else f"crossref:{item.get('URL', '')}",
        "title": str(titles[0]) if titles else "untitled",
        "published_on": date,
        "url": f"https://doi.org/{doi}" if doi else str(item.get("URL", "")),
        # Crossref abstracts can be verbose JATS/HTML.  A compact plain-text
        # clue is enough for S4's hypothesis generation and keeps the LLM
        # request within a predictable latency budget.
        "summary": re.sub(r"<[^>]+>", " ", str(item.get("abstract", ""))).strip()[:320],
        "provider": "crossref_live",
    }


def retrieve_live_literature(
    *, as_of: str, state: str, cache_root: Path, max_items: int = 3,
) -> list[dict[str, str]]:
    """Fetch or replay a small Crossref result set for one S4 decision.

    A cache hit makes reruns deterministic.  A network failure is persisted as
    an audit snapshot but returns an empty list, because web search is optional
    assistance rather than a research-chain dependency.
    """
    if max_items < 1:
        raise ValueError("max_items must be positive")
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    query = _STATE_QUERIES.get(state, "stock return prediction factor")
    cache_path = cache_root / f"{as_of}_{state}.json"
    if cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return list(payload.get("results", []))

    endpoint = "https://api.crossref.org/works?" + urlencode({"query": query, "rows": max_items})
    payload: dict[str, Any] = {
        "schema_version": "s4-live-literature-v1",
        "as_of": as_of,
        "state": state,
        "query": query,
        "endpoint": "https://api.crossref.org/works",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "non_pit_notice": "live index results are exploratory assistance, not PIT-safe historical evidence",
        "results": [],
    }
    try:
        response = _fetch_json(endpoint)
        items = response.get("message", {}).get("items", [])
        payload["results"] = [_normalise_item(item) for item in items if isinstance(item, dict)]
    except Exception as exc:  # optional network source: snapshot the failure, do not block research
        payload["error"] = f"{type(exc).__name__}: {exc}"
    serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload["snapshot_sha256"] = sha256(serialised.encode("utf-8")).hexdigest()
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return list(payload["results"])
