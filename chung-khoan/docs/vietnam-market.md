# 越南市场支持（HOSE / HNX / UPCoM）

本项目支持分析越南证券市场股票，覆盖胡志明证券交易所（HOSE）、河内证券交易所（HNX）以及 UPCoM 板块。

## 代码约定

越南股票代码使用 `.VN` 后缀寻址，避免与 1–5 位美股字母代码冲突：

- `FPT.VN`（HOSE）、`SHS.VN`（HNX）、`ACV.VN` / `VGI.VN`（UPCoM）
- 大小写不敏感：`fpt.vn` 与 `FPT.VN` 等价。

CLI 示例：

```bash
python main.py --stocks FPT.VN,ACV.VN,VGI.VN
```

## 数据源

- `data_provider/vci_fetcher.py::VCIFetcher`，直连 **VCI（Vietcap）公开行情 API**（`https://trading.vietcap.com.vn`）。
- **无需配置任何密钥**，属于常驻数据源，仅对 `vn` 市场生效（其他市场会被 `_DAILY_MARKET_FETCHER_SUPPORT` 过滤跳过，不产生额外开销）。
- 与 `vnstock` 使用同一上游，但直接调用，避免其对 numpy/Python 版本的强约束。

主要端点：

| 用途 | 方法 | 端点 |
| --- | --- | --- |
| 全市场代码 + 所属板块 | GET | `/api/price/symbols/getAll`（字段 `board`：HSX→HOSE / HNX / UPCOM） |
| 日线 OHLCV | POST | `/api/chart/OHLCChart/gap`，body `{"timeFrame":"ONE_DAY","symbols":[...],"from":ts,"to":ts}` |
| 指数 | POST | 同上；指数符号区分大小写：`VNINDEX` / `VN30` / `HNXIndex` / `HNX30` / `HNXUpcomIndex`（UPCoM 指数） |

> 注意：VCI 返回的价格单位为 **越南盾（đồng）**，成交额按 `close * volume` 计算（单位：đồng）。

## 市场语义接入点

新增市场时同步接入的位置（供后续维护参考）：

- `data_provider/base.py`：`_is_vn_market()`、`_market_tag()` 新增 `vn`；`_DAILY_MARKET_FETCHER_SUPPORT["VCIFetcher"] = {"vn"}`；默认数据源列表注册 `VCIFetcher`；`get_daily_data()` 市场判定链新增 `is_vn`。
- `src/market_context.py`：`detect_market()` 识别 `.VN`；`_MARKET_ROLES` / `_MARKET_GUIDELINES` 新增 `vn`（含 HOSE ±7% / HNX ±10% / UPCoM ±15% 涨跌停、外资额度 foreign room、VND 汇率、SBV 政策，及 UPCoM 流动性/披露弱的风险提示）。
- `src/core/trading_calendar.py`：`get_market_for_stock()` 识别 `.VN`；`MARKET_TIMEZONE["vn"] = "Asia/Ho_Chi_Minh"`。未配置 exchange-calendars 日历代码，交易日判定 fail-open（视为开市），与其他未知代码行为一致。
- `src/core/market_strategy.py`：新增 `VN_BLUEPRINT` 与 `get_market_strategy_blueprint("vn")`。

## 已知限制

- 未接入越南交易所的交易日历（exchange-calendars），因此“交易日/盘中阶段”判定对越南市场 fail-open。
- 基本面数据（财报、估值）暂未接入，个股分析以行情 + 技术指标 + 新闻检索 + LLM 为主。
- UPCoM 部分小市值标的流动性与披露较弱，报告已在市场指引中要求显式提示风险。
