# -*- coding: utf-8 -*-
"""
Lớp TOP-DOWN: vĩ mô thị trường → ngành → (drill xuống mã).

Hoàn thiện vision "từ tổng quát đến chi tiết". Nền CFA L2:
  - m37 Economics & Investment Markets: đọc thị trường qua trend + định vị.
  - m23 Market-Based Valuation: gộp bội số theo NGÀNH (ICB) để chọn ngành rẻ/đắt trước.
Kết hợp: vn_data (giá/chỉ số) + vn_fundamentals (bội số) + vn_sectors (bản đồ ICB).

Ba khả năng:
  - market_pulse():   nhịp VN-Index/HNX/UPCoM (trend, vs MA, RSI, %thay đổi) — NHANH.
  - liquid_universe(top): lọc mã thanh khoản nhất (GTGD) từ OHLC batched — NHANH.
  - sector_ranking(universe): median P/E, P/B, ROE theo ngành ICB L1 → xếp hạng ngành.
    (Gọi fundamentals cho từng mã trong universe → dùng universe bị chặn, không quét cả 2000 mã.)
"""
from __future__ import annotations

import sys
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from vn_data import VCIClient
from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout
from vn_sectors import VCISectors

logger = logging.getLogger(__name__)


def _rsi(close: pd.Series, n: int = 14) -> Optional[float]:
    d = close.diff().dropna()
    if len(d) < n + 1:
        return None
    up = d.clip(lower=0).rolling(n).mean().iloc[-1]
    dn = (-d.clip(upper=0)).rolling(n).mean().iloc[-1]
    if dn == 0:
        return 100.0
    rs = up / dn
    return round(100 - 100 / (1 + rs), 1)


def _chg(close: pd.Series, k: int) -> Optional[float]:
    if len(close) <= k:
        return None
    return round((close.iloc[-1] / close.iloc[-1 - k] - 1) * 100, 2)


class VNTopDown:
    def __init__(self, mkt: Optional[VCIClient] = None,
                 fx: Optional[VCIFundamentals] = None,
                 sx: Optional[VCISectors] = None):
        self.mkt = mkt or VCIClient()
        self.fx = fx or VCIFundamentals()
        self.sx = sx or VCISectors()

    # ---- 1. Nhịp thị trường (m37) ----
    def market_pulse(self, days: int = 400) -> Dict[str, Dict]:
        # days = ngày LỊCH; cần ~400 để đủ 200 phiên giao dịch cho MA200
        idx = self.mkt.get_indices(days=days)
        out: Dict[str, Dict] = {}
        for name, df in idx.items():
            if df is None or df.empty:
                continue
            c = df["close"].astype(float)
            ma50 = c.rolling(50).mean().iloc[-1] if len(c) >= 50 else np.nan
            ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else np.nan
            last = c.iloc[-1]
            trend = "?"
            if not np.isnan(ma50) and not np.isnan(ma200):
                if last > ma50 > ma200:
                    trend = "TĂNG (trên cả MA50 & MA200)"
                elif last < ma50 < ma200:
                    trend = "GIẢM (dưới cả MA50 & MA200)"
                else:
                    trend = "ĐI NGANG / chuyển tiếp"
            out[name] = {
                "đóng_cửa": round(last, 2),
                "%_5p": _chg(c, 5), "%_20p": _chg(c, 20), "%_60p": _chg(c, 60),
                "vs_MA50_%": round((last / ma50 - 1) * 100, 2) if not np.isnan(ma50) else None,
                "vs_MA200_%": round((last / ma200 - 1) * 100, 2) if not np.isnan(ma200) else None,
                "RSI14": _rsi(c),
                "trend": trend,
            }
        return out

    # ---- 2. Vũ trụ mã thanh khoản ----
    def liquid_universe(self, top: int = 120, days: int = 20,
                        boards: Optional[List[str]] = None) -> pd.DataFrame:
        uni = self.mkt.get_universe(boards=boards)
        oh = self.mkt.get_ohlcv(uni["symbol"].tolist(), days=days + 15)
        rows = []
        for sym, df in oh.items():
            if df is None or df.empty:
                continue
            amt = df["amount"].tail(days)
            if amt.empty:
                continue
            rows.append({"symbol": sym, "gtgd_tb_ty": float(amt.mean()) / 1e9})
        liq = pd.DataFrame(rows).sort_values("gtgd_tb_ty", ascending=False)
        liq = liq.merge(uni[["symbol", "board", "name"]], on="symbol", how="left")
        return liq.head(top).reset_index(drop=True)

    # ---- 3. Xếp hạng NGÀNH theo định giá (m23) ----
    def sector_ranking(self, universe: List[str], level: str = "icb_l1",
                       min_members: int = 3) -> pd.DataFrame:
        smap = self.sx.get_industry_map()
        recs = []
        for sym in universe:
            try:
                snp = self.fx.snapshot(sym)
            except Exception:  # noqa: BLE001
                continue
            sec = smap[smap["symbol"] == sym]
            if sec.empty:
                continue
            sec = sec.iloc[0]
            recs.append({
                "symbol": sym, "sector": sec[level], "is_bank": sec["is_bank"],
                "pe": snp.get("pe"), "pb": snp.get("pb"),
                "roe": snp.get("roe"), "marketCap": snp.get("marketCap"),
            })
        df = pd.DataFrame(recs)
        if df.empty:
            return df
        for col in ("pe", "pb", "roe"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        # guardrail median: bỏ pe<=0 / vô lý
        def _med_pe(s):
            s = s[(s > 0) & (s < 300)]
            return round(float(s.median()), 2) if len(s) else None
        g = df.groupby("sector")
        agg = g.agg(
            số_mã=("symbol", "count"),
            pe_median=("pe", lambda s: _med_pe(s)),
            pb_median=("pb", lambda s: round(float(s[(s > 0)].median()), 2) if (s > 0).any() else None),
            roe_median=("roe", lambda s: round(float(s.median()) * 100, 1) if s.notna().any() else None),
            vốn_hóa_ty=("marketCap", lambda s: round(float(pd.to_numeric(s, errors="coerce").sum()) / 1e9, 0)),
        ).reset_index()
        agg = agg[agg["số_mã"] >= min_members]
        # xếp theo ROE median giảm dần (ngành sinh lời cao trước)
        return agg.sort_values("roe_median", ascending=False, na_position="last").reset_index(drop=True)


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    td = VNTopDown()

    print("=== 1. NHỊP THỊ TRƯỜNG (m37) ===")
    for name, p in td.market_pulse().items():
        print(f"  {name:12} {p['đóng_cửa']:>10,.1f} | 20p {str(p['%_20p'])+'%':>8} | "
              f"vsMA200 {str(p['vs_MA200_%'])+'%':>8} | RSI {p['RSI14']} | {p['trend']}")

    print("\n=== 2. VŨ TRỤ THANH KHOẢN (top 40 GTGD) ===")
    liq = td.liquid_universe(top=40)
    print(f"  Lấy {len(liq)} mã thanh khoản nhất. Top 8:",
          ", ".join(f"{r.symbol}({r.gtgd_tb_ty:.0f}t)" for r in liq.head(8).itertuples()))

    print("\n=== 3. XẾP HẠNG NGÀNH (ICB L1, trên vũ trụ thanh khoản) ===")
    rank = td.sector_ranking(liq["symbol"].tolist(), level="icb_l1")
    if not rank.empty:
        print(rank.to_string(index=False))
