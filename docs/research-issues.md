# 研究链路问题记录

## ISSUE-001：扩展因子尚未进入统一菜单

- 问题：已有固定七因子，但十三个候选因子没有统一公式、版本和相关簇接口。
- 原因：早期原型只支持单一动量因子，技术因子模块是后续增量建立的。
- 解决方法：新增二十因子统一构建器与 Spearman 强相关簇计算；因子公式与研究设计文档保持一致。
- 状态：处理中。

## ISSUE-002：历史成份股证据存在于外部归档，尚未接入主线

- 问题：主线 `mystock` 当前没有 `data/raw/membership/csi300/` 所需的规范化 CSV + manifest；但已在 `/Users/apple/Projects/phase1a-cleanroom/data/csi300_membership_joinquant/` 找到 2018–2025 的 JoinQuant 成份股快照及年度 manifest。
- 原因：快照格式是 `as_of,index_code,provider,symbol`，缺少当前 `HistoricalUniverse` 加载器要求的 `effective_from/effective_to/announced_at/source_reference`。
- 解决方法：保留当前规范化加载器不变；已新增 `data membership-import` 适配器，将快照转换为规范输入并迁入 `mystock`，同时保留来源 manifest。转换结果明确标记为 `relative_pit_snapshot`，没有把它包装成官方公告时间。
- 状态：已接入主线；仍需在正式运行前完成 OHLCV 复权口径和公司行动证据核验。

## ISSUE-003：`illiquidity_20` 缺少成交额输入

- 问题：冻结公式是 `mean(abs(return) / amount)`，旧研究面板只传入了 `volume`。
- 原因：数据源字段有 `amount`，但 `pipeline.py` 的 DuckDB 查询没有选出该字段。
- 解决方法：已将 `amount` 从 Parquet 查询传入技术因子函数，`illiquidity_20` 现在使用成交额；正式运行仍需补充成交额单位与缺失值校验。
- 状态：已修复接线，已增加数值/缺失/零值校验与异常隔离；单位仍需由 manifest 明确记录。

## ISSUE-004：本地成交额存在 34 条零值记录

- 问题：当前 `data/raw/daily/` 共发现 34 条 `amount <= 0` 的记录；其中既有历史早期的 `volume=0`，也有近年 OHLC 不完整或停牌样式的记录。
- 原因：AKShare 本地归档虽然提供了 `amount` 字段，但字段并不保证每一行都是可交易成交额；单有字段名不能证明该值可用于流动性因子或成交执行。
- 解决方法：正式合同继续 fail-closed：不填充、不把零额改成估计值；在进入 20 因子/回测前生成 `data/warehouse/quality/invalid_amount_rows.csv` 异常行清单。若异常行落在沪深 300 的决策或执行窗口，则该股票日被标记为不可交易并排除；若需要覆盖该窗口，必须先补证据或由数据层重新抓取校验。`illiquidity_20` 不对零额行计算，避免除零和伪造流动性。
- 影响：在异常行被隔离或补齐前，正式数据档案、2024 验证和 2025 锁定窗仍不能宣称通过合同校验。
- 状态：待数据层隔离/补齐。

## ISSUE-005：正式 OHLCV manifest 尚未建立（登记缺失，不等于数据文件不存在）

- 问题：`data/raw/manifests/ohlcv.json` 不存在，合同校验无法确认当前 Parquet 的复权口径、来源、抓取时间和成交额单位；这不是说本地没有行情文件。
- 原因：现有行情文件是历史研究过程中的本地归档，尚未生成与文件集合绑定的不可变数据档案。仓库里已有相对严格 PIT 的设计文档、AKShare 未复权抓取代码和公司行动账本代码，但没有发现与当前 Parquet 文件集合绑定的复权/公司行动证据档案。
- 解决方法：已新增 `mystock data manifest --price-adjustment ...`，由数据层根据当前原始文件生成 manifest，至少包含 schema 版本、文件清单哈希、显式的 `price_adjustment`、来源、抓取时间和 `amount_unit`；生成后再重新运行合同校验。由于旧文件口径尚未被证据确认，不能直接传 `unadjusted`。
- 影响：即使 34 条异常成交额已经可以隔离，正式训练、2024 验证和 2025 锁定窗仍必须阻断。
- 状态：已为新建的 `data/raw/unadjusted_akshare/` 归档建立 manifest；旧 `data/raw/daily/` 仍不作为正式价格输入。

## ISSUE-006：部分历史成份股的 AKShare 未复权补抓失败

- 问题：使用同一 AKShare `adjust=""` 重新抓取 553 个历史成份股代码时，538 个成功，15 个返回空响应；其中 8 个曾出现在 2021–2025 成份股区间。
- 原因：部分历史/退市代码在当前 AKShare 接口没有可返回的完整历史记录。
- 解决方法：14 个聚宽文件已导入 `data/raw/unadjusted_akshare/daily/`，与 AKShare 文件共同生成新的未复权 manifest（来源明确标为 `AKShare+JoinQuant`）。聚宽停牌/无成交造成的 578 个无效 amount 单元由 pipeline 隔离，不填充、不交易；其余失败代码仍不估算、不混入旧前复权价格。
- 状态：15 个代码的价格/成交额已补齐到当前归档；578 个停牌/无成交日已隔离，正式报告需披露数据源混合和隔离数量。

## ISSUE-007：公司行动观测尚非完全严格 PIT

- 问题：公司行动原始观测缺少统一的实际到账时间和完整公告时分秒。
- 解决方法：已新增观测转换器和回测覆盖层，将可识别的现金分红、送转股份转换为 `CorporateAction`，在持仓相关的日收益中计入现金/股份影响，并保留原始 evidence_id。无法解析的记录不参与覆盖。
- 状态：账本已接入相对 PIT 研究链路；数据质量仍标记为 `development_only_not_strict_pit`，不能宣称完全严格 PIT。

## ISSUE-008：JoinQuant 可成交字段存在历史不完整日

- 问题：手动导出的 `paused/high_limit/low_limit/pre_close` 已覆盖历史沪深300成分股的
  文件和日期，但 2021–2025 生效区间仍有 386 个股票日四字段同时为空；同期部分 OHLCV
  仍有成交记录，因此不能把它们解释为停牌。
- 解决方法：新增 `mystock data tradability-audit`，按历史成分股 `effective_from/to`
  生成 `tradability_coverage.json`，并写出精确缺口清单 `manifests/incomplete_rows.csv`。
  执行引擎正式模式遇到缺失字段显式失败；诊断模式可将订单标记为
  `blocked_missing_tradability`，不前填、不从价格猜测。
- 状态：已接受为当前研究边界，暂不阻断因子/模型诊断；正式结果需使用保守阻断模式并披露缺口，后续补齐后再恢复严格成交校验。

## ISSUE-009：多供应商补数尚无统一的非覆盖合并协议

- 问题：新供应商补回 OHLCV 或状态字段时，不能直接覆盖既有 AKShare/JoinQuant 记录；同一
  股票日字段可能存在数值、复权口径或单位差异。
- 处理约定：新数据只进入独立暂存区；先做 `(symbol,date,field)` 覆盖率和冲突复核，
  冲突进入清单并人工决定，确认后才生成新的正式 manifest。
- 状态：待实现为通用数据层能力；当前 JoinQuant 可成交档案已遵守独立目录原则。

## ISSUE-010：旧档案与新供应商的覆盖/一致性报告尚未固化

- 问题：目前可以导入和审计单一档案，但尚未自动输出旧供应商、新供应商和合并结果的逐字段
  覆盖率、缺失日期、差异数量和来源优先级报告。
- 处理约定：新增数据复核命令，先报告再合并；任何差异不静默覆盖，manifest 绑定复核结果。
- 状态：待实现；不影响当前只读 JoinQuant 可成交档案的诊断运行。

## ISSUE-011：OHLCV 质量与覆盖闭环尚未封存

- 问题：历史 OHLCV 仍有异常 `amount` 行，部分历史代码曾从 AKShare 补抓失败，且当前
  正式输入包含 AKShare 与 JoinQuant 的补充档案；这些数据需要在进入正式因子/执行窗口前
  统一复核，而不能只看文件是否存在。
- 处理约定：生成异常行清单、代码覆盖清单、来源分布和最终 manifest；异常窗口不填充、不
  估算，供应商混合必须保留来源与哈希。
- 状态：待完成最终复核；已有隔离和 manifest 机制，但尚未完成一次封存级报告。

## ISSUE-012：持仓估值日存在 OHLCV 缺失

- 问题：S1 保守运行在 2023-06-16 无法估值持仓 `688065.SH`；该股票前一日可能被选中，
  但当日原始 OHLCV 没有收盘记录。不能用前收盘价静默前填，否则会改变执行合同。
- 处理方法：新增 `mystock data repair-missing`，按股票/日期重抓并只补缺失行；本例
  AKShare 重抓仍返回空，因此不是接线遗漏。保守诊断模式允许对已有持仓使用上一次有效
  收盘标记，并记录 `blocked_missing_valuation`；正式严格模式仍显式失败。
- 状态：已转为可继续运行的诊断边界；S0/S1/S2 均可在保守模式走通，但该日期仍须在报告
  中披露，不能把诊断结果包装成严格成交结论。
