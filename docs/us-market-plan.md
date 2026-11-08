# 美股改造计划（`feat/us-market` 分支）

本文记录把 Tick Stock Panel 改造成可以分析美股的方案、已确认的决策和分阶段验收标准。改造遵循 [`CONTRIBUTING.md`](../CONTRIBUTING.md) 与 [`secondary-development.md`](secondary-development.md)：先定契约再写代码，每一步都有测试，A 股原有行为保持不变。

## 0. 基线

| 项目 | 值 |
| --- | --- |
| 上游版本 | `v0.3.34`，commit `b8303417f18124aa541e39949affee41968ad468` |
| 上游协议 | MIT（上游计划未来改为 AGPL-3.0；本分支基于 MIT 版本，同步上游新代码前需复核协议） |
| 后端测试基线 | `uv run --extra dev pytest tests -q`：4496 passed，13 skipped，1 xfailed |
| 运行环境 | 用户本机 Windows x64（桌面版或 `dev.ps1`） |

## 1. 已确认的决策

| 决策 | 结论 |
| --- | --- |
| 数据源 | 做成可切换的数据源插件；第一版接 Yahoo Finance 公开接口，之后评估付费 API 再加一个插件 |
| 代码格式 | 美股直接用交易代码，如 `AAPL`；带类别的股票用连字符，如 `BRK-B`、`BF-B`（与 Yahoo 一致，避免和 `600519.SH` 的点号后缀混淆） |
| 股票池 | 标普 500 + 纳指 100 + 自选股 |
| 实例定位 | 这个实例以美股为主；A 股代码路径保持可用，上游测试全部保持通过，方便以后合并上游 |

## 2. 市场识别

新增 `backend/app/market.py`，作为判断标的属于哪个市场的唯一入口，替代散落各处的后缀判断：

```python
Market = Literal["cn", "us"]

def market_of(symbol: str) -> Market | None:
    """600519.SH / 000001.SZ / 830799.BJ → "cn"；AAPL / BRK-B → "us"；无法识别 → None。"""
```

- A 股规则沿用现有 `^\d{6}\.(SH|SZ|BJ)$`
- 美股规则：`^[A-Z]{1,5}(-[A-Z]{1,2})?$`
- 无法识别的代码返回 `None`，由调用方按自身语义明确处理
- 涨跌停（1a 已完成）：美股返回"无限制"（标量 `None`、polars null、numpy NaN），沿用既有"无涨跌幅限制日"语义；无法识别的代码保持原 A 股主板口径，保证上游测试与 A 股行为不变

## 3. 数据契约映射

美股插件在 provider 边界把数据转换成项目的内部契约，上层不感知供应商格式。

| 内部字段 | 项目契约 | 美股插件做法 |
| --- | --- | --- |
| `symbol` | 标准代码 | `AAPL`、`BRK-B` |
| `date` | 交易日 | 美东交易日期（Yahoo 时间戳按 `America/New_York` 转日期） |
| `open/high/low/close` | 不复权原始价 | Yahoo `quote` 字段是拆股调整后的价格，需要用拆股事件还原为原始价；复权交给 `adj_factor` |
| `volume` | 手（1 手 = 100 股） | 股数 ÷ 100 |
| `amount` | 元 | 美元。Yahoo 不提供成交额，是否允许为空需在实现时按调用链确认，禁止用收盘价 × 成交量伪造 |
| `adj_factor` | 除权事件因子 | 由 Yahoo 的拆股与分红事件按项目公式推导 |
| `turnover_rate` | — | 无股本数据，置空 |

## 4. A 股耦合点清单

| # | 耦合点 | 位置 | 处理方式 | 阶段 |
| --- | --- | --- | --- | --- |
| 1 | 涨跌停：对任意非北交所、非创业板代码返回 10% 主板限制，美股会被误判为有 10% 涨跌停，回测会把大涨日当成"涨停买不进" | `app/price_limits.py`（`board_limit_pct` 及 polars/numpy 向量版本），调用方 `indicators/pipeline.py`、`backtest/matrix.py`、`backtest/minute_replay.py`、`api/kline.py`、`api/watchlist.py` | 美股返回"无涨跌幅限制"（判定价为 null），沿用现有"无限制日"语义 | 1a |
| 2 | 用后缀和代码前缀推断 ETF/股票 | `backtest/engine.py:2653`、`strategy/paper.py:401`、`backtest/matrix.py:4379`、`services/market_overview_builder.py`、`services/abnormal_moves.py`、`api/overview.py` | 改用 `market_of()` + 维表 `asset_type`，美股不走 A 股前缀规则 | 1a/2 |
| 3 | 代码格式正则 | 后端 `services/quote_demand.py`、`services/ext_data.py`、`services/dragon_tiger.py`、`services/watchlist_ocr/pipeline.py`；前端 `lib/stockPreviewStore.ts`、`lib/stock-external-link.ts`、`lib/analysis-adapter.ts` | 接受美股代码；外链美股指向 Yahoo Finance | 1b |
| 4 | 北京时间与交易时段 | `app/market_time.py`（49 个文件引用） | 第一阶段只做日线，不受影响；实时行情、分钟线和同步调度在第 3 阶段按市场区分时区（`America/New_York`） | 3 |
| 5 | 首页固定四只 A 股指数 | `services/index_const.py` | 美股实例改为 SPY / QQQ / DIA / IWM 等基准 | 1c |
| 6 | 回测 T+1 与 100 股整手 | `backtest/engine.py`（`lots`、`buy_lot_size`）、`backtest/matrix.py` | 按市场区分：美股 T+0、1 股起买 | 2 |
| 7 | 换手率依赖历史股本 | `share_capital.py` 等 | 美股无股本数据时置空，沿用"不可计算"状态 | 1a |
| 8 | 金额单位显示为"元" | 前端多处 | 按市场显示货币 | 2 |

## 5. 分阶段计划与验收标准

### 阶段 1：美股日线接入

- **1a 市场识别与涨跌停**：新增 `market.py`；美股不再套用 A 股涨跌停。验收：标量、polars、numpy 三条涨跌停路径对 `AAPL` 都返回无限制，对 A 股样本结果与改造前逐值一致；全量测试不回归
- **1b Yahoo 插件**：`app/plugins/yahoo_us/`，声明 `daily`、`adj_factor`，提供标的维表（标普 500 + 纳指 100，含名称与板块）。验收：按 [`plugin-development.md`](plugin-development.md) 的测试要求，用假客户端覆盖字段映射、单位转换（股→手）、拆股还原原始价、空数据与接口异常、能力声明；不依赖真实网络
- **1c 指数与自选**：基准指数改为美股 ETF；自选股可以添加美股代码
- **1d 本机联调**：在用户的 Windows 电脑上同步美股日线，K 线、指标和选股页面能正常显示

### 阶段 2：波段规则与回测

- 回测按市场区分 T+0/T+1、整手规则和货币
- 把"回调买入 + 顺势加仓、2 ATR 止损、单笔 $1,500 风险、单只 30% 上限"写成项目内的策略与仓位策略（`PositionSizingPolicy`）
- 验收：与 `tools/swing-scanner` 的独立回测在同一数据上结果一致（交易笔数、年化、回撤在可解释误差内）

### 阶段 3：每日扫描与推送

- 同步调度按美东收盘时间运行；收盘后自动扫描并通过飞书推送信号
- 实时行情与分钟线视数据源能力再定

### 阶段 4：本机部署

- 在用户的 Windows 电脑上用桌面版或 `dev.ps1` 运行；数据目录、Key 配置与升级方式写进使用说明

## 6. 后续评估

- 付费数据源候选（稳定性、分钟线、实时行情、价格）在阶段 3 前评估，作为第二个插件接入
- `tools/swing-scanner` 在阶段 2 验收后移除
