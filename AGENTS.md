# AGENTS.md

给在这个仓库里工作的 AI agent（以及人类贡献者）看的说明。项目背景和使用方式见 [README.md](README.md)，这里只写"怎么改这个仓库"相关的约定。

## 项目是什么

mystock 是一个 AI 辅助的量化研究工具：数据采集 → 因子 → 回测 → 报告 → LLM 解读，一条闭环。当前重点是验证这条闭环本身是否可信（防过拟合、结果可解释），不是产出能实盘的策略。

## 技术栈与约定

- Python 3.12，src layout，但 `src/` 下**没有**额外的包名嵌套——`cli.py`、`commands/`、`data/`、`common/`、`research/` 都是顶层模块，互相用绝对导入（`from data.akshare import AKShareProvider`），不要加回 `src/mystock/` 这层
- CLI 用 Typer；配置在 `config/settings.yaml`（PyYAML）；密钥只放 `.env`（`python-dotenv` 加载），**绝不提交到 git**，新增密钥要同时更新 `.env.example`（只写变量名，不写真实值）
- 每一层都是「抽象基类 + 具体实现」的可插拔模式：`DataProvider`/`Storage`（`data/`），`Factor`/`Strategy`/`BacktestEngine`/`ReportGenerator`（`research/`）。新增数据源/因子/回测引擎/报告工具，只需要在对应子目录加一个新的实现类，不要改调用方主流程
- 代码风格：单行尽量不超过约 79 字符，但不是死规则——可读性优先于严格换行
- 不加没用到的抽象、不为假设的未来需求设计；一个 bug 修复不需要顺手重构

## 环境限制（重要，换环境要重新验证）

当前开发环境访问不了东方财富（`eastmoney.com`），AKShare 里走这个域名的接口（如 `stock_zh_a_hist`）会连接失败。数据采集统一改用新浪财经接口：`ak.stock_zh_a_daily`（个股日线）、`ak.stock_zh_index_daily`（指数日线）、`ak.stock_info_a_code_name`（股票列表，含北交所需要重试，`www.bse.cn` 偶发抖动）。这些接口目前从这个环境能访问。如果换了部署环境，应该先重新跑一遍连通性检查，而不是假设结论还成立。

## 设计上的关键约束（不要随便改）

- `ExperimentDefinition`（`research/experiment.py`）是 LLM 意图解析和回测引擎之间的强契约：字段用 `Literal`/范围校验锁死，LLM 输出校验失败就回退默认值，绝不能让 LLM 生成的字段未经校验直接进入回测
- train/holdout 时间切分（`config/settings.yaml` 的 `research.train_start` / `train_end` / `holdout_start`）**不是** `ExperimentDefinition` 的字段，即不允许 LLM 通过用户的自然语言请求来修改——这是刻意的方法论护栏，防止过拟合评估被绕过
- `ExperimentLog`（写到 `data/warehouse/experiments.jsonl`）每次完整 run 只应该 append **一条**记录。历史上出过 bug：train/holdout 两个阶段各 append 一条，导致 `count_trials()` 把一次 run 算成两次试验，已修复——新增阶段/子步骤时注意不要重犯

## 数据规模与存储

全市场 A 股日线全历史大约 1500-2000 万行、几百 MB（Parquet + ZSTD 压缩），DuckDB 直接查询 `data/raw/daily/*.parquet`，不需要为这个数据量引入分布式方案。`data/raw/`、`data/warehouse/` 下除 `.gitkeep` 外都在 `.gitignore` 里，本地生成，不进 git。

## 常用命令

```bash
.venv/bin/pip install -e .              # 装到项目自己的 venv，不装到全局
.venv/bin/mystock data status           # 看本地数据仓库概况
.venv/bin/pytest                        # 跑测试（目前还没有正式用例）
awk '{ if (length($0) > 79) print FILENAME":"FNR }' $(find src -name "*.py")
                                          # 检查行宽
```

## 提交前检查

- 改了 `data/akshare.py` 或新增了外部 API 调用：先手动跑一次确认真的能连通（这个环境对不同域名的可达性不一致，之前踩过东方财富/北交所的坑）
- 改了 `research/` 下任何一层：跑一次 `mystock research run "<某个目标>"` 端到端验证，不要只测单元
- 不要把 `.env`、`data/raw/`、`data/warehouse/` 下的生成产物加进 git
