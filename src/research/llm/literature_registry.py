"""Versioned, date-bounded literature *metadata* for the S3-next challenger.

This is deliberately not a live web-search client.  A historical replay must
not let a 2024 decision read a paper or web page published after that date.
The registry therefore contains concise, source-addressable methodological
metadata.  It is not a local archive of paper full texts or web snapshots.
Retrieval narrows it by the *current* deterministic market state
and the registered factor categories; it never creates factors or relaxes the
numeric portfolio-evidence gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd

from research.factors.catalog import FACTOR_CATEGORIES


LITERATURE_REGISTRY_VERSION = "s3-next-literature-v1"


@dataclass(frozen=True)
class LiteratureEvidence:
    """One compact, auditable methodological source.

    ``supported_categories`` means that the source motivates inspection of a
    category.  It is not a claim that any individual factor will work in this
    project or at a particular date.
    """

    source_id: str
    title: str
    published_on: str
    url: str
    supported_categories: tuple[str, ...]
    states: tuple[str, ...]
    takeaway: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# These predate the 2021--2025 replay.  They are manually registered metadata,
# not downloaded source documents.  Their wording supplies a research question
# for the LLM, while local PIT-safe evidence remains the only authority for
# add/replace.
FROZEN_LITERATURE: tuple[LiteratureEvidence, ...] = (
    LiteratureEvidence(
        source_id="moskowitz_oi_pedersen_2012",
        title="Time Series Momentum",
        published_on="2012-01-01",
        url="https://doi.org/10.1016/j.jfineco.2011.11.003",
        supported_categories=("trend",),
        states=("S1_trend", "S2_stress", "S3_range_or_uncertain"),
        takeaway="趋势信号值得在不同市场环境中检验；不应据此假定单一动量窗口恒定有效。",
    ),
    LiteratureEvidence(
        source_id="daniel_moskowitz_2016",
        title="Momentum Crashes",
        published_on="2016-01-01",
        url="https://doi.org/10.1016/j.jfineco.2015.12.009",
        supported_categories=("trend", "risk"),
        states=("S2_stress",),
        takeaway="压力与快速反转环境可能使动量风险上升，因此应额外审查回撤和波动证据。",
    ),
    LiteratureEvidence(
        source_id="barroso_santa_clara_2015",
        title="Momentum has its moments",
        published_on="2015-01-01",
        url="https://doi.org/10.1016/j.jfineco.2014.11.006",
        supported_categories=("trend", "risk"),
        states=("S2_stress", "S3_range_or_uncertain"),
        takeaway="风险缩放与波动状态值得共同评估；文献结论不替代本地组合成本检验。",
    ),
    LiteratureEvidence(
        source_id="lo_mackinlay_1990",
        title="When Are Contrarian Profits Due to Stock Market Overreaction?",
        published_on="1990-01-01",
        url="https://doi.org/10.1093/rfs/3.2.175",
        supported_categories=("price",),
        states=("S3_range_or_uncertain",),
        takeaway="短期反转是可检验的横截面假设，尤其应与趋势信号区分并避免相关性重复。",
    ),
    LiteratureEvidence(
        source_id="amihud_2002",
        title="Illiquidity and stock returns: cross-section and time-series effects",
        published_on="2002-01-01",
        url="https://doi.org/10.1016/S0304-405X(01)00024-6",
        supported_categories=("liquidity",),
        states=("S2_stress", "S3_range_or_uncertain"),
        takeaway="流动性条件会影响收益与交易可行性，应同时审查信号表现和换手/执行成本。",
    ),
    LiteratureEvidence(
        source_id="ang_hodrick_xing_zhang_2006",
        title="The Cross-Section of Volatility and Expected Returns",
        published_on="2006-01-01",
        url="https://doi.org/10.1111/j.1540-6261.2006.00836.x",
        supported_categories=("risk", "relative"),
        states=("S1_trend", "S2_stress", "S3_range_or_uncertain"),
        takeaway="波动与市场暴露可以作为横截面研究对象，但方向和可交易性必须在本地样本验证。",
    ),
)


def retrieve_literature_as_of(
    *,
    as_of: pd.Timestamp,
    state: str,
    candidates: Iterable[str],
    max_items: int = 4,
) -> list[dict[str, object]]:
    """Return the small, visible literature set relevant to one decision.

    Results are deterministically ordered by state relevance, candidate
    category overlap, publication date and source id.  This makes the same
    historical decision reproducible even when the external web changes.
    """
    cutoff = pd.Timestamp(as_of).normalize()
    categories = {FACTOR_CATEGORIES.get(name) for name in candidates}
    categories.discard(None)
    ranked: list[tuple[tuple[object, ...], LiteratureEvidence]] = []
    for item in FROZEN_LITERATURE:
        published = pd.Timestamp(item.published_on)
        if published > cutoff:
            continue
        state_match = state in item.states
        category_matches = len(categories.intersection(item.supported_categories))
        if not state_match and category_matches == 0:
            continue
        ranked.append((
            (not state_match, -category_matches, -published.value, item.source_id),
            item,
        ))
    return [
        {"registry_version": LITERATURE_REGISTRY_VERSION, **item.as_dict()}
        for _, item in sorted(ranked)[:max_items]
    ]
