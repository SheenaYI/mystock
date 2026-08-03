# mystock

## 项目定位

mystock 是一个量化研究基础工具，未来将逐步扩展为涵盖数据采集、因子研究、策略回测与实盘交易的完整量化研究平台。

## 当前阶段

**数据采集 CLI（Phase 1 脚手架）**。当前只搭建工程结构：CLI 命令框架、数据采集模块接口、本地存储接口、基础配置与日志。不下载真实数据，不接入任何数据源或策略引擎。

## 后续规划

- **Phase 1**：数据采集和本地数据仓库
- **Phase 2**：因子研究和策略回测
- **Phase 3**：AI 量化研究
- **Phase 4**：实盘交易

## 安装

```bash
pip install -e .
```

## 运行

```bash
mystock --help
mystock data --help
mystock data fetch
mystock data update
```

## 配置

配置文件位于 `config/settings.yaml`，包含数据路径、存储格式与日志级别。

## 测试

```bash
pytest
```
