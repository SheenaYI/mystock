# 实验目录与结果命名

本文件是研究结果的目录，不是收益结论。一个实验组只有在其数据、合同、运行状态和报告均可
回放时，才可出现在组间比较中。

## 当前实验组

| 组别 | 人类可读名称 | 因子菜单 | 配方选择 | LLM / 检索 | 组合规则 | 作用 |
| --- | --- | --- | --- | --- | --- | --- |
| M0 | 20日动量参照 | 仅 `return_20` | 无 | 无 | TopK=10, n_drop=5 | 判断多因子链路是否优于直接20日动量。 |
| S0 | 固定七因子基线 | 七个固定技术因子 | 固定七因子 | 无 | TopK=10, n_drop=5 | 所有增量研究的主基线。 |
| S1 | 静态确定性扩展 | 技术25因子菜单 | 覆盖率/低相关确定性规则 | 无 | TopK=10, n_drop=5 | 判断静态技术扩展是否有价值。 |
| S2 | 状态映射确定性组 | 技术25因子菜单 | 确定性状态→配方映射 | 无 | TopK=10, n_drop=5 | 判断“市场状态”本身是否有价值。 |
| S3 | 受限真实LLM组 | 技术25因子菜单 | ReAct-lite 的 add/drop/replace/abstain | 真实LLM；不检索文献 | TopK=10, n_drop=5 | 判断受约束LLM能否优于确定性状态规则。 |
| S3-next | 文献辅助历史挑战者 | 技术25因子菜单 | ReAct-lite 的 add/drop/replace/abstain | 真实LLM + 文献检索 | 旧合同 | 历史探索结果，保留用于追溯，不再作为当前主线。 |

“增加因子”不是单独的实验组：它指技术25因子菜单，相对 S0 的固定七因子扩大了候选范围；
S1、S2、S3 和 S4 共用该菜单。S4 的新增变化是 **W1 频率（H=5、R=5、K=20、J=20）、
经济意义覆盖约束、联网文献辅助以及 n_drop=2/5 对照**。

## 结果归档规则

报告按组别存放在 `data/warehouse/reports/<组别目录>/`。每组固定使用如下报告名：

| 组别 | 合并报告 | 分段报告前缀 |
| --- | --- | --- |
| M0 | `M0_direct_momentum/report_technical_m0_return_20_direct.html` | 同目录 `train/holdout/locked_2025_*.html` |
| S0 | `S0_fixed_7/report_technical_baseline_7.html` | 同目录 `train/holdout/locked_2025_*.html` |
| S1 | `S1_deterministic/report_technical_s1_deterministic.html` | 同目录 `train/holdout/locked_2025_*.html` |
| S2 | `S2_state_mapping/report_technical_s2_state_mapping.html` | 同目录 `train/holdout/locked_2025_*.html` |
| S3 | `S3_react_lite/report_technical_s3_react_lite.html` | 同目录 `train/holdout/locked_2025_*.html` |
| S3-next | `S3_next_literature/report_technical_s3_next_literature_challenger.html` | 历史挑战者结果，仅供追溯 |
| S4-W1-n5 | `S4_W1_n5/continuous_2024_2025_technical_s4_w1_economic_coverage_n5.html` | 当前主实验：H=5、R=5、K=20、J=20、`n_drop=5`。 |
| S4-W1-n2 | `S4_W1_n2/continuous_2024_2025_technical_s4_w1_economic_coverage_n2.html` | 当前对照：与 n5 同合同，只将 `n_drop` 改为 2。 |

## 当前工作区地图

```text
src/data/                         # AKShare / a-stock-data 原始采集与来源对比
src/research/                     # 研究主链：因子、标签、Qlib、组合、账本、报告
src/research/jobs/                # 可断点恢复的研究任务 manifest / worker
scripts/                          # 数据审计、因子库重建、报告目录迁移
config/                           # 运行合同与数据路径配置
data/raw/                         # 本地原始数据（默认不入 git）
data/warehouse/cache/             # 矩阵、证据、LLM 与文献缓存（默认不入 git）
data/warehouse/reports/<group>/  # 按 M0/S0–S4 分组的可读 HTML 报告
data/warehouse/diagnostics/<group>/ # 与报告对应的 RankIC、状态和组合诊断
data/warehouse/legacy/            # 旧原型结果，仅作历史参照
docs/                             # 设计、实施计划、实验目录与待办
tests/                            # 数据合同、因子、LLM、任务和报告回归测试
```

运行结果和缓存仍留在本地，不提交到 git；代码、合同、测试和目录说明进入版本库。

旧的 `technical_20` 报告是早期原型，不进入当前 S0–S3/S3-next 主比较。它们在需要追溯时
保留，但应在任何图表或汇报中标为“legacy prototype”。

## 后续目录收敛

现在 `reports/` 是便于浏览的展示架；后续如果同一组重复运行，再额外保留一份不可变运行目录：

```text
data/warehouse/runs/<contract_hash>/
├── manifest.json          # profile、数据/代码/合同哈希、运行状态
├── reports/               # train、holdout、locked_2025、合并报告
├── diagnostics/           # RankIC、状态、相对基准诊断
├── execution/             # 整数手账本与隔离订单
└── llm/                   # 本次决策的引用日志和证据快照索引
```

日常只需要打开 `reports/S0_fixed_7/`、`reports/S3_react_lite/` 这样的组别目录。`runs/` 只在
需要追溯“某一次具体运行用了哪份数据和代码”时才使用；不可变结果以 `contract_hash` 为准。

## 解读边界

- S0–S3-next 是研究组名，不是推荐等级；
- 使用 `tradability_mode=block` 的结果是保守诊断，不是正式实盘或严格锁定结论；
- S3-next 若表现更高，也只说明它是候选挑战者；是否升级必须同时比较超额收益、回撤、Beta、
  换手、成本和可回放性，不能只看累计收益。
