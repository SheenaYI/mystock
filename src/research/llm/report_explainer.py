"""LLM report narration; it receives results but cannot alter them."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class ReportExplainer:
    """Translate fixed metrics into Chinese explanation without making decisions."""

    def __init__(self) -> None:
        # Accept the current project names and the already-used OneProCloud
        # names.  This keeps the research repo independent of the old app
        # while allowing the same local .env values to be reused.
        base_url = os.getenv("LLM_API_BASE_URL") or os.getenv("LLM_ONEPROCLOUD_BASE_URL")
        api_key = os.getenv("LLM_API_KEY") or os.getenv("LLM_ONEPROCLOUD_API_KEY")
        self.model = os.getenv("LLM_MODEL") or os.getenv("LITELLM_MODEL", "")
        self.client = (
            OpenAI(base_url=base_url, api_key=api_key, timeout=30.0, max_retries=0)
            if base_url and api_key and self.model else None
        )

    def explain(self, *, metrics: dict, method_summary: str) -> str:
        prompt = (
            "Explain these completed backtest metrics in plain Chinese. Do not invent numbers, "
            "change the method, or give trading instructions. State that a backtest is not a return guarantee."
        )
        if self.client is None:
            return "报告解释未调用 LLM：当前环境未配置 LLM_API_BASE_URL、LLM_API_KEY 和 LLM_MODEL。" \
                "以下指标仅作研究回测记录，不代表未来收益保证。"
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"method": method_summary, "metrics": metrics}, ensure_ascii=False, default=str)}],
            )
            return response.choices[0].message.content
        except Exception as exc:
            return f"报告解释调用失败（{type(exc).__name__}）；以下指标仅作研究回测记录，不代表未来收益保证。"
