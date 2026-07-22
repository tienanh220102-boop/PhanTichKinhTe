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


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if not np.isnan(f) else None
    except (TypeError, ValueError):
        return None


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


def _annual_upto(ratios: pd.DataFrame, year: int) -> pd.DataFrame:
    """Dòng SỐ CẢ NĂM (RATIO_YEAR) với yearReport ≤ year, sắp tăng dần. (Sửa filter quarter==0
    cũ luôn rỗng — cùng bug đã vá ở vn_valuation.)"""
    if ratios is None or ratios.empty or "yearReport" not in ratios.columns:
        return pd.DataFrame()
    r = ratios
    if "ratioType" in r.columns:
        a = r[r["ratioType"] == "RATIO_YEAR"]
        r = a if not a.empty else r
    elif "quarter" in r.columns:
        r = r[pd.to_numeric(r["quarter"], errors="coerce") == 5]
    r = r[pd.to_numeric(r["yearReport"], errors="coerce") <= year]
    return r.sort_values("yearReport") if not r.empty else pd.DataFrame()


def score_point_in_time(fx: VCIFundamentals, sym: str, is_bank: bool,
                        cutoff: int = CUTOFF_YEAR) -> Optional[dict]:
    """Fetch (1 lần) + chấm điểm point-in-time ≤ cutoff. Dùng cho backtest 1-kỳ."""
    if is_bank:
        return None
    try:
        inc = fx.get_statement(sym, "INCOME_STATEMENT", "year")
        cf = fx.get_statement(sym, "CASH_FLOW", "year")
        ratios = fx.get_ratios(sym)
    except Exception:  # noqa: BLE001
        return None
    return _score_from_frames(inc, cf, ratios, cutoff)


def _score_from_frames(inc: pd.DataFrame, cf: pd.DataFrame, ratios: pd.DataFrame,
                       cutoff: int) -> Optional[dict]:
    """Chấm điểm từ 3 báo cáo ĐÃ tải, filter ≤ cutoff (dùng lại cho rolling: fetch 1 lần/mã,
    chấm nhiều năm vào lệnh). Trả cờ forensic + tín hiệu định giá/chất lượng/chu kỳ."""
    cfo = _series_upto(cf, C_CFO, cutoff)
    ni = _series_upto(inc, C_NI, cutoff)
    rev = _series_upto(inc, C_REV, cutoff)
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
    # cờ 4: đòn bẩy cao + thanh khoản yếu (RATIO_YEAR ≤ cutoff — đã sửa filter)
    annual = _annual_upto(ratios, cutoff)
    if not annual.empty:
        row = annual.iloc[-1]
        try:
            de = float(row.get("debtToEquity")); cur = float(row.get("currentRatio"))
            if de > 2 and cur < 1:
                flags += 1
        except (TypeError, ValueError):
            pass

    # ---- TÍN HIỆU MỚI (point-in-time ≤ cutoff) ----
    pb = pe = roic_mean = roic_trend = cyc_pos = None
    if not annual.empty:
        row = annual.iloc[-1]  # RATIO_YEAR năm cutoff (định giá cuối năm đó, công khai năm sau)
        pb = _num(row.get("pb")); pe = _num(row.get("pe"))
        roic_s = pd.to_numeric(annual.get("roic", pd.Series(dtype=float)), errors="coerce").dropna()
        roic_s = roic_s[(roic_s > -1) & (roic_s < 2)]
        if len(roic_s) >= 3:
            roic_mean = float(roic_s.mean())
            half = max(1, len(roic_s) // 2)
            roic_trend = float(roic_s.iloc[-half:].mean() - roic_s.iloc[:half].mean())
        mar_s = pd.to_numeric(annual.get("afterTaxProfitMargin", pd.Series(dtype=float)),
                              errors="coerce").dropna()
        mar_s = mar_s[mar_s != 0]
        if len(mar_s) >= 4 and mar_s.median() > 0:
            cyc_pos = float(mar_s.iloc[-1] / mar_s.median())  # <0.9 đáy, >1.15 đỉnh
    return {"cfo_ni_3y": cfo_ni, "n_flags": flags, "clean": flags == 0,
            "pb": pb, "pe": pe, "roic_mean": roic_mean, "roic_trend": roic_trend,
            "cyc_pos": cyc_pos}


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

    # ---- TÍN HIỆU MỚI (cái ta THÊM cả phiên — có dự báo 2 năm không?) ----
    pb_med = df["pb"].dropna().median()
    print(f"\nD) ĐỊNH GIÁ RẺ theo P/B ≤{CUTOFF_YEAR} (median ngành {pb_med:.2f}):")
    summarize("  Rẻ (P/B ≤ median)", df[df["pb"] <= pb_med])
    summarize("  Đắt (P/B > median)", df[df["pb"] > pb_med])
    print("\nE) CHẤT LƯỢNG — ROIC bình quân ≤cutoff (chi phí vốn ~13%):")
    summarize("  ROIC ≥ 13% (trên hurdle)", df[df["roic_mean"] >= 0.13])
    summarize("  ROIC < 13%", df[(df["roic_mean"].notna()) & (df["roic_mean"] < 0.13)])
    summarize("  ROIC xu hướng TĂNG", df[df["roic_trend"] > 0.01])
    summarize("  ROIC xu hướng GIẢM", df[df["roic_trend"] < -0.01])
    print("\nF) CHU KỲ — biên 2022 vs trung vị (đáy có mean-revert thắng không?):")
    summarize("  ĐÁY biên (cyc<0.9)", df[df["cyc_pos"] < 0.9])
    summarize("  ĐỈNH biên (cyc>1.15)", df[df["cyc_pos"] > 1.15])
    print("\nG) TỔ HỢP 'MUA' = rẻ + sạch cờ + ROIC≥10% (luận điểm hệ khuyến nghị):")
    buy = df[(df["pb"] <= pb_med) & (df["n_flags"] == 0) & (df["roic_mean"] >= 0.10)]
    summarize("  Nhóm MUA", buy)
    summarize("  Phần còn lại", df.drop(buy.index))

    # --- PERMUTATION TEST tổng quát: mỗi tín hiệu có thật hay may rủi? ---
    print(f"\n{'='*66}\nPERMUTATION TEST — tín hiệu có THẬT hay may rủi? (10.000 lần xáo nhãn)\n"
          f"{'='*66}\nH0: nhãn không liên quan lợi nhuận. p<0.05 = khó là ngẫu nhiên.\n")
    rng = np.random.default_rng(42)
    sig_2y = {"n": 0, "total": 0}   # đếm tín hiệu có ý nghĩa ở mốc 2 năm
    horizon_2y = [h for h in HORIZONS if h.startswith("2")]

    def perm(label: str, mask: np.ndarray) -> None:
        line = f"  {label:26}"
        for name in HORIZONS:
            r = df[name].values.astype(float)
            ok = ~np.isnan(r) & ~pd.isna(mask)
            rr = r[ok]; cm = mask[ok].astype(bool)
            if cm.sum() < 5 or (~cm).sum() < 5:
                line += f" | {name.split()[0]}: n/a"; continue
            actual = np.median(rr[cm]) - np.median(rr[~cm])
            n_c = int(cm.sum())
            null = np.empty(10000)
            for i in range(10000):
                idx = rng.permutation(len(rr))
                null[i] = np.median(rr[idx[:n_c]]) - np.median(rr[idx[n_c:]])
            p = float(np.mean(np.abs(null) >= abs(actual)))
            mark = "✓" if p < 0.05 else ("~" if p < 0.15 else "✗")
            line += f" | {name.split()[0]}: {actual*100:+4.0f}% p={p:.2f}{mark}"
            if name in horizon_2y:
                sig_2y["total"] += 1
                if p < 0.05:
                    sig_2y["n"] += 1
        print(line)

    perm("Sạch cờ vs có cờ", (df["n_flags"] == 0).values)
    perm("Rẻ P/B vs đắt", (df["pb"] <= pb_med).values)
    perm("ROIC≥13% vs <13%", (df["roic_mean"] >= 0.13).values)
    perm("ROIC tăng vs giảm", np.where(df["roic_trend"].notna(),
                                       (df["roic_trend"] > 0).values, np.nan))
    perm("Đáy biên vs còn lại", (df["cyc_pos"] < 0.9).values)
    perm("Tổ hợp MUA vs còn lại", df.index.isin(buy.index))

    print("\n✓ p<0.05 khó là ngẫu nhiên · ~ ranh giới (0.05–0.15) · ✗ chưa tách được khỏi nhiễu.")
    print("ĐỌC KỸ: một kỳ vào lệnh + small-n + survivorship bias → p cao KHÔNG có nghĩa tín hiệu")
    print("vô dụng, mà là DỮ LIỆU CHƯA ĐỦ để chứng minh. Cột '2' (2 năm) là horizon user quan tâm.")
    print(f"\n>>> KẾT LUẬN mốc 2 NĂM: {sig_2y['n']}/{sig_2y['total']} tín hiệu đạt p<0.05. "
          + ("KHÔNG tín hiệu nào tách được khỏi may rủi ở 2 năm — hệ nên dùng như BỘ LỌC PHÒNG "
             "THỦ (tránh mã cờ, mạnh ở 1 năm), KHÔNG phải máy 'chọn mã thắng 2 năm'."
             if sig_2y['n'] == 0 else "có tín hiệu đạt ý nghĩa — nhưng vẫn 1 kỳ, cần thêm kỳ."))


if __name__ == "__main__":
    run()
