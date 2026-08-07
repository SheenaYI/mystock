"""Real, bounded and auditable ReAct-lite factor selection.

The selector is deliberately narrow: the model may only choose from the
registered extension factors supplied by the deterministic pipeline.  It
cannot change the universe, label horizon, model, portfolio rules or costs.
Every API call (including failed/non-trial calls) is appended to the audit
log before the result is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


PROMPT_VERSION = "react_factor_selector_v1.1.0"


@dataclass(frozen=True)
class SelectionDecision:
    decision_id: str
    state: str
    selected: tuple[str, ...]
    action: str
    rounds: int
    reason: str = ""


_FACTOR_CATEGORIES = {
    "return_5": "trend", "return_20": "trend", "return_60": "trend",
    "return_120": "trend", "reversal_5": "trend", "trend_efficiency_60": "trend",
    "vol_adjusted_return_60": "trend", "ma_gap_5": "trend", "ma_gap_20": "trend",
    "volatility_20": "risk", "downside_volatility_20": "risk", "drawdown_60": "risk",
    "intraday_range": "risk", "return_skewness_20": "risk",
    "volume_ratio_20": "liquidity", "volume_trend_20": "liquidity",
    "volume_price_corr_20": "liquidity", "illiquidity_20": "liquidity",
    "high_low_position_60": "price", "return_1": "price",
}


class ReActLiteSelector:
    """Use a real OpenAI-compatible model with a frozen four-round budget."""

    def __init__(
        self,
        log_path: Path,
        *,
        max_rounds: int = 4,
        max_selected: int = 3,
        use_llm: bool = True,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        if max_selected < 1:
            raise ValueError("max_selected must be positive")
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_rounds = max_rounds
        self.max_selected = max_selected
        self.use_llm = use_llm
        load_dotenv()
        self.model = (
            os.getenv("LLM_MODEL")
            or os.getenv("LITELLM_MODEL")
            or os.getenv("LLM_ONEPROCLOUD_MODELS", "").split(",")[0].strip()
        )
        self.base_url = os.getenv("LLM_API_BASE_URL") or os.getenv(
            "LLM_ONEPROCLOUD_BASE_URL"
        )
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("LLM_ONEPROCLOUD_API_KEY")
        if self.use_llm:
            missing = [name for name, value in {
                "LLM API base URL": self.base_url,
                "LLM API key": self.api_key,
                "LLM model": self.model,
            }.items() if not value]
            if missing:
                raise RuntimeError(
                    "真实 ReAct-lite 缺少配置：" + "、".join(missing)
                    + "；请运行 `mystock config set-llm` 或填写项目 .env"
                )
            self.client = OpenAI(
                base_url=self.base_url, api_key=self.api_key,
                # Evidence-rich S3 prompts can take longer than the smoke-test
                # request; this is an operational network timeout, not an
                # additional ReAct round or trial budget.
                timeout=90.0, max_retries=0,
            )
        else:
            self.client = None

    def decide(
        self,
        *,
        decision_id: str,
        state: str,
        evidence: dict[str, Any],
        candidates: tuple[str, ...],
        current_factors: tuple[str, ...],
    ) -> SelectionDecision:
        """Observe, assess and decide, stopping at the frozen round limit."""
        if not candidates:
            self._write_audit(
                decision_id=decision_id, evidence=evidence, round_no=1,
                output_kind="abstain", output={"reason": "no_candidates"},
            )
            return SelectionDecision(decision_id, state, (), "abstain", 1, "no_candidates")

        prompt_base = self._prompt(
            evidence=evidence, state=state, candidates=candidates,
            current_factors=current_factors,
        )
        feedback = ""
        for round_no in range(1, self.max_rounds + 1):
            try:
                if self.use_llm:
                    raw = self._chat(prompt_base + feedback)
                else:
                    raw = json.dumps({"action": "abstain", "selected": [], "reason": "offline_fixture"})
                parsed = self._parse(raw)
                action, selected, reason = self._validate(
                    parsed, candidates=candidates, current_factors=current_factors,
                    evidence=evidence,
                )
                self._write_audit(
                    decision_id=decision_id, evidence=evidence, round_no=round_no,
                    output_kind=action, output=parsed,
                )
                return SelectionDecision(decision_id, state, selected, action, round_no, reason)
            except Exception as exc:
                self._write_audit(
                    decision_id=decision_id, evidence=evidence, round_no=round_no,
                    output_kind="failure", output={"error": str(exc)},
                )
                feedback = (
                    "\n上一轮输出无效，必须只输出合法 JSON，并满足最终配方 5–9 个、"
                    "动作数量限制和相关簇约束。错误："
                    + str(exc)
                    + "\n"
                )

        # Explicit failure: never silently extend the budget or choose a
        # deterministic fallback after the real model has failed.
        failure = {"action": "selection_failed", "reason": "round_limit_exceeded"}
        self._write_audit(
            decision_id=decision_id, evidence=evidence, round_no=self.max_rounds,
            output_kind="selection_failed", output=failure,
        )
        raise RuntimeError(f"selection_failed: decision_id={decision_id}, max_rounds={self.max_rounds}")

    def _prompt(
        self, *, evidence: dict[str, Any], state: str,
        candidates: tuple[str, ...], current_factors: tuple[str, ...],
    ) -> str:
        return (
            "你是受限 ReAct-lite 因子选择器。只能在已有固定七因子之外选择扩展因子，"
            "不能改动股票池、标签窗口、LightGBM、TopK、调仓频率或交易成本。\n"
            "请按 observe→assess→decide 思路在内部分析：\n"
            "1) observe：读取当前市场状态、当前配方和历史证据；\n"
            "2) assess：指出历史支持不足、相关性过高或证据矛盾的因子；\n"
            "3) decide：只做合法的 add/drop/replace，证据不足就 abstain。\n"
            f"当前状态：{state}\n"
            f"当前配方（{len(current_factors)} 个）：{list(current_factors)}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)}\n"
            f"允许新增候选：{list(candidates)}\n"
            "硬性约束：动作执行后最终配方必须仍有 5–9 个因子；每次最多新增 2 个、删除 2 个、"
            "替换 2 个；删除数量不得使配方少于 5 个；新增或替换不得引入相关簇冲突；"
            "固定七因子已有的相关簇重叠可以保留，但不能新增冲突。\n"
            "只输出 JSON，不要 markdown："
            '{"action":"add|drop|replace|abstain", "add":[], "drop":[], '
            '"replace":[{"drop":"factor_old","add":"factor_new"}], '
            '"reason":"简短理由", "evidence_refs":[]}'
        )

    def _chat(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": "你是严格遵守输出格式的量化研究助手。"},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("empty model output")
        return content

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("output must be a JSON object")
        return parsed

    def _validate(
        self, parsed: dict[str, Any], *, candidates: tuple[str, ...],
        current_factors: tuple[str, ...], evidence: dict[str, Any],
    ) -> tuple[str, tuple[str, ...], str]:
        action = parsed.get("action")
        if action not in {"add", "drop", "replace", "abstain"}:
            raise ValueError("action must be add, drop, replace or abstain")
        add = self._factor_list(parsed.get("add", []), "add")
        drop = self._factor_list(parsed.get("drop", []), "drop")
        replacements = parsed.get("replace", [])
        if not isinstance(replacements, list) or not all(isinstance(x, dict) for x in replacements):
            raise ValueError("replace must be a list of {drop, add} objects")
        replace_drop, replace_add = [], []
        for item in replacements:
            replace_drop.append(item.get("drop"))
            replace_add.append(item.get("add"))
        if any(not isinstance(x, str) for x in (*replace_drop, *replace_add)):
            raise ValueError("replace entries require string drop and add")
        if action == "abstain":
            if add or drop or replacements:
                raise ValueError("abstain must not contain actions")
            return action, current_factors, str(parsed.get("reason", ""))[:1000]
        if action == "add" and (not add or drop or replacements):
            raise ValueError("add must contain only add factors")
        if action == "drop" and (not drop or add or replacements):
            raise ValueError("drop must contain only drop factors")
        if action == "replace" and (not replacements or add or drop):
            raise ValueError("replace must contain only replacement pairs")
        if len(add) + len(drop) > 2 or len(replacements) > 2:
            raise ValueError("one decision may change at most two factors")
        candidate_set = set(candidates)
        current_set = set(current_factors)
        if any(x not in candidate_set or x in current_set for x in add + tuple(replace_add)):
            raise ValueError("add factors must be unused registered candidates")
        if any(x not in current_set for x in drop + tuple(replace_drop)):
            raise ValueError("drop factors must be in the current recipe")
        selected = list(current_factors)
        for factor in drop + tuple(replace_drop):
            selected.remove(factor)
        selected.extend(add)
        selected.extend(replace_add)
        selected = tuple(dict.fromkeys(selected))
        self._validate_recipe(selected, evidence)
        reason = str(parsed.get("reason", ""))[:1000]
        if not reason:
            raise ValueError("non-abstain decisions require a reason")
        return action, selected, reason

    @staticmethod
    def _factor_list(value: Any, field: str) -> tuple[str, ...]:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"{field} must be a list of factor names")
        return tuple(dict.fromkeys(value))

    @staticmethod
    def _validate_recipe(selected: tuple[str, ...], evidence: dict[str, Any]) -> None:
        if not 5 <= len(selected) <= 9:
            raise ValueError("final recipe must contain 5 to 9 factors")
        categories = {_FACTOR_CATEGORIES.get(factor) for factor in selected}
        if not {"trend", "risk", "liquidity"}.issubset(categories):
            raise ValueError("recipe must cover trend, risk and liquidity")
        clusters = evidence.get("correlation_clusters", [])
        baseline = set(evidence.get("base_factors", []))
        for cluster in clusters:
            overlap = set(cluster) & set(selected)
            # The frozen seven-factor baseline is grandfathered at the
            # starting point: otherwise S3 could not even start because the
            # baseline itself contains known redundant pairs.  Any newly
            # added/replaced factor must still respect the one-per-cluster
            # rule; removing a baseline member remains an explicit action.
            newly_introduced = overlap - baseline
            if len(overlap) > 1 and newly_introduced:
                raise ValueError("recipe contains more than one factor from a correlation cluster")

    def _write_audit(
        self, *, decision_id: str, evidence: dict[str, Any], round_no: int,
        output_kind: str, output: dict[str, Any],
    ) -> None:
        snapshot = json.dumps(evidence, sort_keys=True, ensure_ascii=False, default=str)
        record = {
            "call_seq": self._next_call_seq(),
            "decision_id": decision_id,
            "input_snapshot_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
            "prompt_version": PROMPT_VERSION,
            "output": output,
            "output_kind": output_kind,
            "consumes_trial_id": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "round": round_no,
            "evidence": evidence,
            "model": self.model,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _next_call_seq(self) -> int:
        if not self.log_path.exists():
            return 1
        count = sum(1 for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip())
        return count + 1
