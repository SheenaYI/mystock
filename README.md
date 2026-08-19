# mystock

## 项目定位

mystock 是一个 AI 辅助的量化研究工具。目标不是重新造一个量化平台，而是搭一条

> 用户提出研究目标 → LLM 设计实验 → 数据/因子/回测引擎执行 → 生成研究报告 → LLM 分析结果

的完整闭环，用来验证"怎么系统性地找因子、做回测、校验结果"这件事本身是否可行，而不是急于产出能实盘的策略。

## 当前阶段

- **数据采集**：AKShare（新浪接口）全市场 A 股日线 + 指数行情，本地 Parquet 存储，DuckDB 作为查询层
- **AI 研究闭环 MVP**：单因子（20 日动量）+ 干净 universe（剔除 ST、流动性 Top N）+ 训练期/验证期分离回测（VectorBT）+ QuantStats 报告 + LLM 意图解析与结果解读

后续因子、回测引擎、数据源都可以按需扩展（详见「架构」一节），不改动主流程。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env   # 填入 LLM_API_BASE_URL / LLM_API_KEY / LLM_MODEL
```

`.venv` 是本项目独立的虚拟环境，不影响机器上其他项目。

## CLI 命令

```bash
mystock --help

# 数据采集
mystock data fetch --universe all        # 全市场全历史（默认，可断点续传）
mystock data fetch --symbols 600519.SH   # 只拉指定股票，调试用
mystock data update                      # 增量更新已下载过的股票
mystock data supplement --source a-stock-data --symbols 600000.SH,000001.SZ \
  --start-date 2025-01-01 --end-date 2025-12-31  # 补充源审计，不覆盖 AKShare
mystock data status                      # 查看本地数据仓库概况
mystock research context-search --query "沪深300 波动率" --cutoff-date 2024-12-31  # 受日期约束的历史语境归档

# 本地凭据（只写入 .env，不覆盖行情数据）
mystock config set-llm                    # 交互式填写 LLM 配置
mystock config set-joinquant              # 交互式填写聚宽配置
mystock config status                     # 脱敏查看配置状态

# AI 研究闭环
mystock research run "研究A股动量策略"     # 一条命令跑完整闭环，输出 HTML 报告 + AI 分析
```

## 项目结构

```
src/
├── cli.py                    # CLI 入口
├── commands/                  # data / research 命令组（薄封装，只做参数转发）
├── common/logger.py           # 读 config/settings.yaml，配置 logging
├── data/                      # 数据采集层：Provider / Storage 抽象 + AKShare / Parquet 实现
└── research/                  # AI 研究层，每一层都是「抽象基类 + 具体实现」，方便扩展：
    ├── experiment.py           # LLM ↔ 引擎之间的强契约（pydantic schema）+ 实验试跑日志
    ├── universe.py             # 干净 universe 构建
    ├── factor.py / factors/    # 因子接口 + MomentumFactor
    ├── strategy.py / strategies/  # 组合构建接口 + TopPctStrategy
    ├── engine.py / engines/    # 回测引擎接口 + VectorBTEngine
    ├── report.py / reports/    # 报告生成接口 + QuantStatsReport
    ├── llm.py                  # LLM 客户端：意图解析 + 结果解读
    └── pipeline.py             # 把以上各层串成一次完整 run
```

新增因子/回测引擎/数据源，只需要在对应的子目录新增一个实现子类，不用改 `pipeline.py` 的主流程。

## 配置

- `config/settings.yaml`：数据路径、存储格式、日志级别，以及 `research` 下的训练期/验证期切分日期、universe 大小、交易成本、调仓周期等——这些是刻意不开放给 LLM 修改的方法论护栏
- `.env`（不提交到 git）：`LLM_API_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`，OpenAI 兼容接口
- 聚宽凭据：`JQ_USERNAME` / `JQ_PASSWORD`，仅用于自动抓取历史 `paused`、`high_limit`、`low_limit`；数据写入独立的 `data/raw/tradability_joinquant/`，不会覆盖 AKShare OHLCV

## 环境限制说明

当前开发环境访问不了东方财富（eastmoney.com），AKShare 里依赖该域名的接口会失败，因此数据采集统一走新浪财经接口。换到网络环境不同的机器上部署时，这个假设需要重新验证。

## 测试

```bash
pytest
```

## 后续规划

- 更多因子（价值、质量等）与批量因子对比
- 接入 Qlib 做多因子/机器学习研究
- 成分股历史名单（避免 universe 选择的前视偏差）
- 实盘/模拟盘（miniQMT）
