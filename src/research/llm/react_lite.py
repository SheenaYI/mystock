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
from research.factors.catalog import FACTOR_CATEGORIES, FACTOR_ECONOMIC_MEANINGS


PROMPT_VERSION = "react_factor_selector_v1.5.0"
S3_NEXT_PROMPT_VERSION = "react_factor_selector_s3_next_v1.0.0"
# v1.1 adds optional live literature-index assistance to the standard S4
# protocol.  The version change intentionally isolates old S4 cache entries.
S4_PROMPT_VERSION = "react_factor_selector_s4_economic_coverage_v1.2.0"


@dataclass(frozen=True)
class SelectionDecision:
    decision_id: str
    state: str
    selected: tuple[str, ...]
    action: str
    rounds: int
    reason: str = ""


class ReActLiteSelector:
    """Use a real OpenAI-compatible model with a frozen four-round budget."""

    def __init__(
        self,
        log_path: Path,
        *,
        max_rounds: int = 4,
        max_selected: int = 3,
        use_llm: bool = True,
        prompt_version: str = PROMPT_VERSION,
        require_literature_refs: bool = False,
        enforce_marginal_evidence: bool = True,
        require_economic_rationales: bool = False,
        min_candidate_coverage: float = 0.95,
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
        self.prompt_version = prompt_version
        self.require_literature_refs = require_literature_refs
        self.enforce_marginal_evidence = enforce_marginal_evidence
        self.require_economic_rationales = require_economic_rationales
        self.min_candidate_coverage = min_candidate_coverage
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
        eligible_candidates = self._eligible_candidates(evidence, candidates)
        if not eligible_candidates:
            self._write_audit(
                decision_id=decision_id, evidence=evidence, round_no=1,
                output_kind="abstain", output={
                    "reason": self._no_eligible_reason(),
                    "candidate_count": len(candidates),
                },
            )
            return SelectionDecision(
                decision_id, state, tuple(current_factors), "abstain", 1,
                self._no_eligible_reason(),
            )

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
                    evidence=evidence, eligible_candidates=eligible_candidates,
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
        compact = self._compact_evidence(evidence, candidates)
        prompt = (
            "你是受限 ReAct-lite 因子选择器。只能在已有固定七因子之外选择扩展因子，"
            "不能改动股票池、标签窗口、LightGBM、TopK、调仓频率或交易成本。\n"
            "候选菜单按趋势/动量、价格形态/反转、风险/波动、成交量/流动性、相对市场五类登记；"
            "市场状态变量只是选择依据，不是可自行创造的新因子。\n"
            "请按 observe→assess→decide 思路在内部分析：\n"
            "1) observe：读取当前市场状态、当前配方和历史证据；\n"
            "2) assess：指出历史支持不足、相关性过高或证据矛盾的因子；历史语境和预置文献索引"
            "只能作为辅助，必须检查每条记录发布时间不晚于决策日，不能把事后新闻或新论文当作历史证据；\n"
            "3) decide：只做合法的 add/drop/replace；证据不足时 abstain。\n"
            f"当前状态：{state}\n"
            f"当前配方（{len(current_factors)} 个）：{list(current_factors)}\n"
            f"压缩证据摘要：{json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)}\n"
            f"允许新增候选：{list(candidates)}\n"
        )
        if self.enforce_marginal_evidence:
            prompt += (
                "硬性约束：只有同时满足整体稳定因子证据、当前市场状态下的稳定因子证据、"
                "整体至少两折组合边际改善、当前状态下至少两折组合边际改善，且换手/回撤/Beta没有显著恶化，"
                "才允许 add 或 replace；只提高单因子 IC 不足以执行动作。没有明确证据时默认 abstain。"
            )
        else:
            cards = {name: FACTOR_ECONOMIC_MEANINGS[name] for name in candidates}
            prompt += (
                "这是 S4 探索型挑战者：不使用 S3 的两折组合边际改善门槛，但不等于可以随意选因子。"
                "每个 add 或 replace 必须同时满足：(a) 说明其经济意义及与当前状态的关系；"
                f"(b) 当前基础配方可交易股票内覆盖率不低于 {self.min_candidate_coverage:.0%}；"
                "(c) 不与已选或同次新增因子处于同一强相关簇。"
                "优先构造经济含义互补、跨类别覆盖高、相关性低的稀疏配方；不能同时满足则 abstain。"
                "预置文献索引只能形成假设，不能被当作收益保证。"
                "若 action 是 add 或 replace，factor_rationales 必须为每个新增因子各给一条完整对象，"
                "并且每条都含 factor、economic_meaning、state_relevance、coverage、non_redundancy 五个非空字符串；"
                "缺任一字段即输出 abstain，不得只在 reason 中笼统说明。"
                f"因子经济意义卡：{json.dumps(cards, ensure_ascii=False, sort_keys=True)}\n"
            )
            if compact.get("live_literature"):
                prompt += (
                    "以下是本次实时学术索引检索结果：它们只用于补充研究假设，不是 PIT-safe 历史证据；"
                    "若实际采用，请在 literature_refs 中记录 source_id。"
                    f"实时检索结果：{json.dumps(compact['live_literature'], ensure_ascii=False, sort_keys=True)}\n"
                )
        return prompt + (
            "动作执行后最终配方必须仍有 5–9 个因子；每次最多新增 2 个、删除 2 个、"
            "替换 2 个；删除数量不得使配方少于 5 个；新增或替换不得引入相关簇冲突；"
            "固定七因子已有的相关簇重叠可以保留，但不能新增冲突。\n"
            "若预置文献索引非空，任何 add/drop/replace 都必须在 literature_refs 中引用其中至少一个 source_id；"
            "文献只说明研究方向，不能作为绕过数值门槛的理由。\n"
            "只输出 JSON，不要 markdown："
            '{"action":"add|drop|replace|abstain", "add":[], "drop":[], '
            '"replace":[{"drop":"factor_old","add":"factor_new"}], '
            '"reason":"简短理由", "evidence_refs":[], "literature_refs":[], '
            '"factor_rationales":[{"factor":"候选因子", "economic_meaning":"经济含义", '
            '"state_relevance":"与当前状态的关系", "coverage":"当前覆盖率", "non_redundancy":"与现有配方的互补性"}]}'
        )

    @staticmethod
    def _compact_evidence(evidence: dict[str, Any], candidates: tuple[str, ...]) -> dict[str, Any]:
        """Keep the auditable full snapshot local, but send only decision data."""
        def compact_number(value: Any) -> float | None:
            try:
                return round(float(value), 4)
            except (TypeError, ValueError):
                return None

        all_evidence = evidence.get("factor_evidence", {})
        factors: dict[str, Any] = {}
        for name in candidates:
            item = all_evidence.get(name, {})
            state_item = item.get("state_rank_ic", {}).get(evidence.get("current_state", ""), {})
            factors[name] = {
                "ic": compact_number(item.get("mean_rank_ic")),
                "icir": compact_number(item.get("icir")),
                "coverage": compact_number(item.get("coverage_current")),
                "state_ic": compact_number(state_item.get("mean_rank_ic")),
                "state_icir": compact_number(state_item.get("icir")),
            }
        return {
            "decision_date": evidence.get("decision_date"),
            "mature_through": evidence.get("mature_through"),
            "mature_observations": evidence.get("mature_observations"),
            "current_state": evidence.get("current_state"),
            "market_state_snapshot": evidence.get("market_state_snapshot"),
            "live_literature": [
                {
                    **{key: item.get(key) for key in ("source_id", "title", "published_on", "url")},
                    "summary": str(item.get("summary", ""))[:320],
                }
                for item in evidence.get("live_literature", []) if isinstance(item, dict)
            ],
            "correlation_threshold": evidence.get("correlation_threshold"),
            "correlation_clusters": evidence.get("correlation_clusters"),
            "candidate_evidence": factors,
        }

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
        eligible_candidates: tuple[str, ...] | None = None,
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
        if self.require_literature_refs:
            available_refs = {
                str(item.get("source_id"))
                for item in (*evidence.get("frozen_literature", []), *evidence.get("live_literature", []))
                if isinstance(item, dict) and item.get("source_id")
            }
            cited_refs = parsed.get("literature_refs", [])
            if not isinstance(cited_refs, list) or not all(isinstance(item, str) for item in cited_refs):
                raise ValueError("S3-next non-abstain actions require literature_refs as a string list")
            if not set(cited_refs).intersection(available_refs):
                raise ValueError("S3-next non-abstain actions must cite a retrieved frozen literature source")
        else:
            cited_refs = parsed.get("literature_refs", [])
            if cited_refs:
                if not isinstance(cited_refs, list) or not all(isinstance(item, str) for item in cited_refs):
                    raise ValueError("literature_refs must be a string list when supplied")
                available_refs = {
                    str(item.get("source_id"))
                    for item in (*evidence.get("frozen_literature", []), *evidence.get("live_literature", []))
                    if isinstance(item, dict) and item.get("source_id")
                }
                if not set(cited_refs).issubset(available_refs):
                    raise ValueError("literature_refs must refer to supplied search results")
        if eligible_candidates is None:
            eligible_candidates = self._eligible_candidates(evidence, candidates)
        changed_extensions = add + tuple(replace_add)
        # The strict S3/S3-next protocol only accepts a drop when the
        # portfolio-level marginal-evidence gate supports it.  S4 is an
        # exploratory, coverage-and-economic-meaning constrained protocol;
        # it may remove a baseline factor without pretending it has a
        # portfolio marginal test for a newly-added extension.
        if action == "drop" and not changed_extensions and self.enforce_marginal_evidence:
            raise ValueError("drop requires explicit marginal portfolio evidence")
        if any(factor not in eligible_candidates for factor in changed_extensions):
            if self.enforce_marginal_evidence:
                raise ValueError(
                    "add/replace require stable two-fold portfolio marginal improvement "
                    "with no material turnover/drawdown/beta deterioration"
                )
            raise ValueError(
                f"S4 add/replace require at least {self.min_candidate_coverage:.0%} coverage in the active base universe"
            )
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
        if self.require_economic_rationales:
            self._validate_economic_rationales(parsed, changed_extensions)
        reason = str(parsed.get("reason", ""))[:1000]
        if not reason:
            raise ValueError("non-abstain decisions require a reason")
        return action, selected, reason

    def _eligible_candidates(
        self, evidence: dict[str, Any], candidates: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Apply a fail-closed portfolio-level evidence gate before acting."""
        if not self.enforce_marginal_evidence:
            factor_evidence = evidence.get("factor_evidence", {})
            return tuple(
                factor for factor in candidates
                if float(factor_evidence.get(factor, {}).get("coverage_current", 0.0))
                >= self.min_candidate_coverage
            )
        marginal = evidence.get("portfolio_marginal_evidence", {})
        result: list[str] = []
        for factor in candidates:
            item = marginal.get(factor, {})
            if not isinstance(item, dict):
                continue
            if (
                item.get("factor_evidence_stable") is True
                and item.get("state_factor_evidence_stable") is True
                and int(item.get("qualifying_folds", 0)) >= 2
                and int(item.get("state_qualifying_folds", 0)) >= 2
                and item.get("portfolio_marginal_improvement") is True
                and item.get("risk_cost_ok") is True
                and item.get("state_portfolio_marginal_improvement") is True
                and item.get("state_risk_cost_ok") is True
            ):
                result.append(factor)
        return tuple(result)

    def _no_eligible_reason(self) -> str:
        if self.enforce_marginal_evidence:
            return "no_clear_portfolio_marginal_improvement"
        return f"no_candidate_with_{self.min_candidate_coverage:.0%}_active_universe_coverage"

    @staticmethod
    def _validate_economic_rationales(
        parsed: dict[str, Any], changed_extensions: tuple[str, ...]
    ) -> None:
        """Require one complete, logged rationale for every S4 addition."""
        rationales = parsed.get("factor_rationales", [])
        if not isinstance(rationales, list) or not all(isinstance(item, dict) for item in rationales):
            raise ValueError("S4 non-abstain add/replace actions require factor_rationales")
        by_factor = {item.get("factor"): item for item in rationales}
        for factor in changed_extensions:
            item = by_factor.get(factor)
            if not isinstance(item, dict):
                raise ValueError(f"S4 rationale missing for {factor}")
            required = ("economic_meaning", "state_relevance", "coverage", "non_redundancy")
            if any(not isinstance(item.get(field), str) or not item[field].strip() for field in required):
                raise ValueError(f"S4 rationale for {factor} is incomplete")

    @staticmethod
    def _factor_list(value: Any, field: str) -> tuple[str, ...]:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ValueError(f"{field} must be a list of factor names")
        return tuple(dict.fromkeys(value))

    @staticmethod
    def _validate_recipe(selected: tuple[str, ...], evidence: dict[str, Any]) -> None:
        if not 5 <= len(selected) <= 9:
            raise ValueError("final recipe must contain 5 to 9 factors")
        categories = {FACTOR_CATEGORIES.get(factor) for factor in selected}
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
            "prompt_version": self.prompt_version,
            "output": output,
            "output_kind": output_kind,
            "consumes_trial_id": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "round": round_no,
            "evidence": evidence,
            "model": self.model,
            "enforce_marginal_evidence": self.enforce_marginal_evidence,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _next_call_seq(self) -> int:
        if not self.log_path.exists():
            return 1
        count = sum(1 for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip())
        return count + 1
