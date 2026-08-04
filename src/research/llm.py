"""LLM client: intent parsing (front door) and result summarizing
(back door).

These are the only two places in the research pipeline that touch an
LLM. Everything between them (universe, factor, backtest, report) is
deterministic code the LLM never sees or influences beyond the
validated `ExperimentDefinition` fields it produces here.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from common.logger import get_logger
from research.experiment import ExperimentDefinition

logger = get_logger(__name__)

load_dotenv()

_INTENT_SYSTEM_PROMPT = (
    "You convert a user's Chinese research goal into a JSON object "
    "matching this schema, using defaults for anything not "
    'mentioned. Only these fields exist: factor (must be exactly '
    '"momentum_20d", the only implemented factor), top_pct (0-0.5), '
    "rebalance_days (1-120), fee_rate (0-0.02), benchmark (index "
    'symbol, default "000300.SH"). Reply with ONLY the JSON object, '
    "no other text, no markdown code fence."
)

_SUMMARY_SYSTEM_PROMPT = (
    "You explain a momentum-strategy backtest (train period vs "
    "holdout period, both vs a benchmark) to a reader with NO "
    "quant background — assume they don't know what Sharpe, Sortino, "
    "Beta, Alpha, Information Ratio, drawdown, or any other jargon "
    "means. Every time you use a metric, first say in one plain "
    "Chinese phrase what it intuitively means, THEN give the number "
    "— never state a jargon term and number without explaining it "
    "first. Prefer concrete money framing (e.g. '如果投100万...') "
    "over abstract ratios. Cover, in this order: 1) 用大白话说这策略"
    "涨了多少、稳不稳; 2) 最吓人的风险点是什么（比如回撤多深、多久回"
    "本）, explained concretely; 3) 对比 train 和 holdout，是真的变"
    "强了还是只是运气/风险加大了; 4) 一句话建议下一步研究什么。Do "
    "not invent numbers not present in the input. Write in Chinese, "
    "4-6 short paragraphs, no bullet-point jargon dumps."
)


class LLMClient:
    """Thin wrapper around an OpenAI-compatible chat completions API."""

    def __init__(self) -> None:
        base_url = os.environ["LLM_API_BASE_URL"]
        api_key = os.environ["LLM_API_KEY"]
        self.model = os.environ["LLM_MODEL"]
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def parse_intent(self, goal_text: str) -> ExperimentDefinition:
        """Parse a free-text research goal into a validated experiment.

        Falls back to schema defaults if the LLM output doesn't parse
        or doesn't validate — a hallucinated or malformed reply never
        reaches the backtest engine.
        """
        content = self._chat(_INTENT_SYSTEM_PROMPT, goal_text)
        try:
            fields = json.loads(_strip_code_fence(content))
            return ExperimentDefinition(**fields)
        except Exception as exc:
            logger.warning(
                "intent parse failed (%s), using defaults: %r",
                exc, content,
            )
            return ExperimentDefinition()

    def summarize(
        self, metrics: dict, experiment: ExperimentDefinition
    ) -> str:
        """Turn backtest metrics into a written analysis."""
        payload = {
            "experiment": experiment.model_dump(),
            "metrics": metrics,
        }
        user_content = json.dumps(payload, ensure_ascii=False, default=str)
        return self._chat(_SUMMARY_SYSTEM_PROMPT, user_content)

    def _chat(self, system_prompt: str, user_content: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        return response.choices[0].message.content


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return text.strip()
