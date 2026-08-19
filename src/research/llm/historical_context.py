"""Date-bounded historical market-context evidence for ReAct-lite."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import pandas as pd


SCHEMA_VERSION = "mystock-historical-context-v1"


@dataclass(frozen=True)
class HistoricalContext:
    title: str
    url: str
    published_at: str
    source: str
    snippet: str = ""
    retrieved_at: str = ""
    content_sha256: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _cutoff(cutoff_date: str | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(cutoff_date)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("Asia/Shanghai")
    return stamp.normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)


def _hash_record(title: str, url: str, published_at: str, snippet: str) -> str:
    payload = "\0".join((title.strip(), url.strip(), published_at.strip(), snippet.strip()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GoogleNewsRssSearcher:
    """Optional bounded search adapter; no item may pass the cutoff."""

    def __init__(self, *, max_results: int = 3, timeout_seconds: int = 10) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, cutoff_date: str | pd.Timestamp) -> list[HistoricalContext]:
        cutoff = _cutoff(cutoff_date)
        url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(f"{query} before:{(cutoff + pd.Timedelta(days=1)).date().isoformat()}")
            + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        request = Request(url, headers={"User-Agent": "mystock-historical-context/1.0"})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            root = ET.fromstring(response.read())
        retrieved = datetime.now(timezone.utc).isoformat()
        results: list[HistoricalContext] = []
        for item in root.findall("./channel/item"):
            title = (item.findtext("title") or "").strip()
            item_url = (item.findtext("link") or "").strip()
            pub_text = (item.findtext("pubDate") or "").strip()
            if not title or not item_url or not pub_text:
                continue
            try:
                published = pd.Timestamp(parsedate_to_datetime(pub_text))
                if published.tzinfo is None:
                    published = published.tz_localize("UTC")
                published = published.tz_convert("Asia/Shanghai")
            except (TypeError, ValueError, OverflowError):
                continue
            if published > cutoff:
                continue
            snippet = (item.findtext("description") or "").strip()
            published_iso = published.isoformat()
            results.append(HistoricalContext(
                title=title, url=item_url, published_at=published_iso,
                source="google_news_rss", snippet=snippet,
                retrieved_at=retrieved,
                content_sha256=_hash_record(title, item_url, published_iso, snippet),
            ))
            if len(results) >= self.max_results:
                break
        return results


def search_queries(
    searcher: GoogleNewsRssSearcher, queries: Iterable[str], *,
    cutoff_date: str | pd.Timestamp, max_queries: int = 2,
) -> list[HistoricalContext]:
    """Run a bounded query batch and deduplicate by content hash."""
    query_list = [str(query).strip() for query in queries if str(query).strip()]
    if len(query_list) > max_queries:
        raise ValueError(f"historical context allows at most {max_queries} queries per decision")
    results: list[HistoricalContext] = []
    seen: set[str] = set()
    for query in query_list:
        for item in searcher.search(query, cutoff_date=cutoff_date):
            if item.content_sha256 not in seen:
                results.append(item)
                seen.add(item.content_sha256)
    return results


def load_context_as_of(path: Path, *, cutoff_date: str | pd.Timestamp, max_items: int = 6) -> list[dict[str, str]]:
    """Load only archived records visible by the decision cutoff."""
    if not Path(path).is_file():
        return []
    cutoff = _cutoff(cutoff_date)
    records: list[dict[str, str]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        published = pd.Timestamp(item["published_at"])
        if published.tzinfo is None:
            published = published.tz_localize("Asia/Shanghai")
        if published <= cutoff:
            records.append(item)
    return records[-max_items:]


def append_context(path: Path, records: Iterable[HistoricalContext]) -> int:
    """Append immutable JSONL records for later PIT-filtered replay."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    value = json.loads(line).get("content_sha256")
                    if value:
                        existing.add(str(value))
                except json.JSONDecodeError:
                    continue
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            if record.content_sha256 in existing:
                continue
            payload = {"schema_version": SCHEMA_VERSION, **record.as_dict()}
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            existing.add(record.content_sha256)
            count += 1
    return count
