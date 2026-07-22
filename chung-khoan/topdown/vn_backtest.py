# -*- coding: utf-8 -*-
"""
BACKTEST — kiểm hệ forensic CÓ dự báo lợi nhuận không (validation, không phải tô điểm).

Câu hỏi: nhóm mã "sạch cờ + chất lượng dòng tiền tốt" (đánh giá bằng số CHỈ tới FY2022) có
THẮNG nhóm "nhiều cờ" trong 2024–2026 không?

LOOKAHEAD SẠCH: chỉ dùng BCTC năm ≤ 2022 (biết chắc vào cuối 2023) để chấm điểm, rồi "mua"
tại giá cuối 2023 và đo lợi nhuận tới cuối 2024 / cuối 2025 / hiện tại. Giá VCI đã điều chỉnh
cổ tức/chia tách (đã kiểm: không có phiên nhảy do chia tách).

CAVEAT PHẢI ĐỌC (theo pipeline validation của user):
  1. SURVIVORSHIP BIAS: vũ trụ chỉ gồm mã ĐANG niêm yết → mã đã hủy niêm yết/phá sản (thường
     là nhóm "nhiều cờ") bị loại → kết quả THIÊN VỊ CÓ LỢI cho nhóm xấu. Bias này làm hệ trông
     KÉM hiệu quả hơn thực (nếu hệ vẫn phân biệt được thì càng đáng tin).
  2. MỘT KỲ DUY NHẤT (mua cuối 2023): kết quả là 1 điểm dữ liệu, phụ thuộc may rủi giai đoạn.
     Không đủ để kết luận chắc — chỉ là sanity check hướng.
  3. Số nhỏ (small-n), không tính phí/trượt giá. Không phải bằng chứng cuối cùng.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from vn_data import VCIClient
from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout
from vn_topdown import VNTopDown
from vn_sectors import VCISectors

logger = logging.getLogger(__name__)

CUTOFF_YEAR = 2022          # chỉ dùng BCTC ≤ năm này (biết chắc cuối 2023)
ENTRY = pd.Timestamp("2023-12-29")
HORIZONS = {"1 năm (2024)": pd.Timestamp("2024-12-29"),
            "2 năm (2025)": pd.Timestamp("2025-12-29"),
            "tới nay (~2.5n)": None}   # None = phiên cuối cùng

C_CFO = "Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh"
C_REV = "Doanh thu thuần"
C_NI = "Lãi/(lỗ) thuần sau thuế"


def _series_upto(df: pd.DataFrame, col: str, year: int) -> Dict[int, float]:
    if df is None or df.empty or "yearReport" not in df.columns or col not in df.columns:
        return {}
    out = {}
    sub = df[col]
    if isinstance(sub, pd.DataFrame):
        sub = sub.iloc[:, 0]
    for y, v in zip(df["yearReport"], sub):
        try:
            yi, fv = int(y), float(v)
        except (TypeError, ValueError):
            continue
        if yi <= year and not np.isnan(fv):
            out[yi] = fv
    return out


def score_point_in_time(fx: VCIFundamentals, sym: str, is_bank: bool) -> Optional[dict]:
    """Chấm điểm forensic CHỈ bằng số ≤ CUTOFF_YEAR. Trả {cfo_ni_3y, n_flags, clean}."""
    if is_bank:
        return None
    try:
        inc = fx.get_statement(sym, "INCOME_STATEMENT", "year")
        cf = fx.get_statement(sym, "CASH_FLOW", "year")
        ratios = fx.get_ratios(sym)
    except Exception:  # noqa: BLE001
        return None
    cfo = _series_upto(cf, C_CFO, CUTOFF_YEAR)
    ni = _series_upto(inc, C_NI, CUTOFF_YEAR)
    rev = _series_upto(inc, C_REV, CUTOFF_YEAR)
    common = sorted(set(cfo) & set(ni))
    if len(common) < 3:
        return None
    last3 = common[-3:]
    sni = sum(ni[y] for y in last3)
    scfo = sum(cfo[y] for y in last3)
    cfo_ni = (scfo / sni) if sni > 0 else (-1.0 if sni <= 0 else None)
    flags = 0
    y = common[-1]
    # cờ 1: CFO âm kỳ gần nhất
    if cfo.get(y, 0) < 0:
        flags += 1
    # cờ 2: chất lượng LN kém (CFO 3 năm < 40% lãi ròng)
    if sni > 0 and scfo / sni < 0.4:
        flags += 1
    # cờ 3: kinh doanh đi lùi (doanh thu giảm >15% hoặc chuyển lỗ)
    ry = sorted(rev)
    if len(ry) >= 2 and rev[ry[-2]] > 0 and (rev[ry[-1]] - rev[ry[-2]]) / rev[ry[-2]] < -0.15:
        flags += 1
    if sni <= 0:
        flags += 1
    # cờ 4: đòn bẩy cao + thanh khoản yếu (từ ratios ≤ cutoff)
    try:
        rr = ratios[ratios.get("yearReport") <= CUTOFF_YEAR] if "yearReport" in ratios else ratios
        annual = rr[rr.get("quarter").fillna(0) == 0] if "quarter" in rr else rr
        if not annual.empty:
            row = annual.iloc[-1]
            de = float(row.get("debtToEquity")); cur = float(row.get("currentRatio"))
            if de > 2 and cur < 1:
                flags += 1
    except Exception:  # noqa: BLE001
        pass
    return {"cfo_ni_3y": cfo_ni, "n_flags": flags, "clean": flags == 0}


def _price_at(df: pd.DataFrame, target: Optional[pd.Timestamp]) -> Optional[float]:
    """Close tại phiên gần target nhất (trong 7 ngày); None nếu cuối chuỗi thì lấy phiên cuối."""
    if df is None or df.empty:
        return None
    df = df.sort_values("date")
    if target is None:
        return float(df["close"].iloc[-1])
    diff = (df["date"] - target).abs()
    i = diff.idxmin()
    if diff.loc[i] > pd.Timedelta(days=10):
        return None
    return float(df.loc[i, "close"])


def run() -> None:
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    td = VNTopDown(); fx = VCIFundamentals(); sx = VCISectors(); dc = VCIClient()
    uni = td.liquid_universe(top=120)
    syms = list(uni["symbol"])
    imap = sx.get_industry_map()
    bankset = set(imap[imap["is_bank"] == True]["symbol"]) if "is_bank" in imap else set()  # noqa: E712

    # giá: 1 lần cho cả vũ trụ
    px = dc.get_ohlcv(syms, days=1050)

    rows = []
    for s in syms:
        if s in bankset:
            continue
        sc = score_point_in_time(fx, s, is_bank=False)
        if sc is None:
            continue
        pdf = px.get(s)
        p0 = _price_at(pdf, ENTRY)
        if p0 is None or p0 <= 0:
            continue
        rec = {"sym": s, **sc, "p0": p0}
        for name, tgt in HORIZONS.items():
            pt = _price_at(pdf, tgt)
            rec[name] = (pt / p0 - 1) if (pt and pt > 0) else None
        rows.append(rec)

    df = pd.DataFrame(rows)
    print(f"\n{'='*66}\nBACKTEST: mua cuối 2023 bằng số ≤{CUTOFF_YEAR}, N={len(df)} mã phi ngân hàng\n{'='*66}")
    print("(SURVIVORSHIP BIAS: chỉ mã còn niêm yết — thiên vị CÓ LỢI cho nhóm xấu)\n")

    def summarize(label, sub):
        if sub.empty:
            print(f"{label}: (rỗng)"); return
        line = f"{label:28} n={len(sub):>3}"
        for name in HORIZONS:
            v = sub[name].dropna()
            line += f" | {name}: {v.median()*100:+5.0f}% (thắng {(v>0).mean()*100:.0f}%)" if len(v) else f" | {name}: -"
        print(line)

    print("A) Theo SỐ CỜ ĐỎ (điểm forensic point-in-time):")
    summarize("  Sạch (0 cờ)", df[df["n_flags"] == 0])
    summarize("  1 cờ", df[df["n_flags"] == 1])
    summarize("  ≥2 cờ", df[df["n_flags"] >= 2])
    print("\nB) Theo CHẤT LƯỢNG DÒNG TIỀN (CFO/LN 3 năm):")
    q = df.dropna(subset=["cfo_ni_3y"])
    summarize("  CFO/LN ≥ 80% (tốt)", q[q["cfo_ni_3y"] >= 0.8])
    summarize("  CFO/LN 0–80%", q[(q["cfo_ni_3y"] >= 0) & (q["cfo_ni_3y"] < 0.8)])
    summarize("  CFO/LN < 0 (âm)", q[q["cfo_ni_3y"] < 0])
    print("\nC) BASELINE (toàn bộ mã — proxy thị trường):")
    summarize("  Tất cả", df)


if __name__ == "__main__":
    run()
