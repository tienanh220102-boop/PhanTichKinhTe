# -*- coding: utf-8 -*-
"""
BACKTEST ROLLING — vào lệnh NHIỀU kỳ để tăng power (khắc phục "1 lần tung xúc xắc").

Backtest 1-kỳ (vn_backtest.py) chỉ vào cuối 2023 → 1 cửa sổ 2-năm (2024-25 bò tót) → không
tách được tín hiệu khỏi may rủi. Ở đây vào lệnh cuối MỖI năm 2021→2024 (mỗi lần chấm điểm bằng
số ≤ năm trước, lookahead sạch), đo 1 & 2 năm tới → 4 cửa sổ qua CÁC CHẾ ĐỘ khác nhau (gồm cú
sập 2022). Dữ liệu: giá VCI lùi 2016, fundamentals 2018 → vào lệnh sớm nhất 2021 (cần ≥3 năm số).

KIỂM ĐỊNH ĐÚNG CÁCH — PERMUTATION THEO KHỐI (xáo nhãn TRONG từng năm): mỗi năm thị trường lên/
xuống khác nhau (2022 sập, 2023-25 hồi). Nếu gộp thẳng, hiệu ứng năm át tín hiệu. Xáo nhãn trong
từng năm giữ nguyên phân phối lợi nhuận của năm đó → chỉ hỏi "TRONG mỗi năm, tín hiệu có tách
người thắng/thua theo hướng NHẤT QUÁN không?". Đây là câu hỏi đúng cho một edge cắt ngang.

CAVEAT vẫn còn: survivorship bias (chỉ mã còn niêm yết — thiên vị CHỐNG phát hiện); 4 kỳ vẫn
ít; chồng lấn cửa sổ 2-năm (2021→23, 2022→24 dùng chung 2023) → không hoàn toàn độc lập; chưa
trừ phí. Không phải bằng chứng cuối cùng, nhưng mạnh hơn 1-kỳ nhiều.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from vn_data import VCIClient
from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout
from vn_topdown import VNTopDown
from vn_sectors import VCISectors
from vn_backtest import _score_from_frames, _price_at

logger = logging.getLogger(__name__)

ENTRY_YEARS = [2021, 2022, 2023, 2024]     # vào lệnh cuối các năm này (cutoff = năm-1)
TOP_UNIVERSE = 150
N_PERM = 5000
MIN_GRP = 5                                 # tối thiểu mỗi nhóm/năm để tính spread


def _entry_date(y: int) -> pd.Timestamp:
    return pd.Timestamp(f"{y}-12-28")


def _ret(px: pd.DataFrame, y0: int, dyears: int) -> Optional[float]:
    p0 = _price_at(px, _entry_date(y0))
    p1 = _price_at(px, _entry_date(y0 + dyears))
    if p0 and p1 and p0 > 0 and p1 > 0:
        return p1 / p0 - 1
    return None


_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "bt_roll_cache.csv")


def collect(use_cache: bool = True) -> pd.DataFrame:
    if use_cache and os.path.exists(_CACHE):
        logger.warning("Nạp cache %s (xóa để tải mới)", _CACHE)
        return pd.read_csv(_CACHE)
    fx = VCIFundamentals(); sx = VCISectors(); dc = VCIClient(); td = VNTopDown()
    uni = td.liquid_universe(top=TOP_UNIVERSE)
    syms = list(uni["symbol"])
    imap = sx.get_industry_map()
    bankset = set(imap[imap["is_bank"] == True]["symbol"]) if "is_bank" in imap else set()  # noqa: E712
    px = dc.get_ohlcv(syms, days=3900)      # ~10.5 năm, 1 lần cho cả vũ trụ

    rows: List[dict] = []
    for s in syms:
        if s in bankset or s not in px:
            continue
        try:
            inc = fx.get_statement(s, "INCOME_STATEMENT", "year")
            cf = fx.get_statement(s, "CASH_FLOW", "year")
            ratios = fx.get_ratios(s)
        except Exception:  # noqa: BLE001
            continue
        pdf = px[s]
        for y in ENTRY_YEARS:
            sc = _score_from_frames(inc, cf, ratios, cutoff=y - 1)   # số ≤ năm trước
            if sc is None:
                continue
            r1 = _ret(pdf, y, 1); r2 = _ret(pdf, y, 2)
            if r1 is None and r2 is None:
                continue
            rows.append({"sym": s, "entry": y, **sc, "ret1": r1, "ret2": r2})
    df = pd.DataFrame(rows)
    try:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        df.to_csv(_CACHE, index=False)
    except Exception:  # noqa: BLE001
        pass
    return df


def _block_perm(df: pd.DataFrame, mask: np.ndarray, retcol: str,
                rng: np.random.Generator) -> Optional[tuple]:
    """Spread cắt ngang trung bình qua các năm + p-value (xáo nhãn TRONG từng năm).

    Trả (actual_spread, p, n_years_valid, per_year[list]). None nếu không đủ năm hợp lệ.
    """
    sub = df[[retcol, "entry"]].copy()
    sub["m"] = mask
    sub = sub.dropna(subset=[retcol, "m"])
    years, blocks = [], []
    per_year = []
    for y, g in sub.groupby("entry"):
        m = g["m"].values.astype(bool)
        r = g[retcol].values.astype(float)
        if m.sum() < MIN_GRP or (~m).sum() < MIN_GRP:
            continue
        sp = np.median(r[m]) - np.median(r[~m])
        years.append(y); blocks.append((r, m)); per_year.append((int(y), sp, int(m.sum()), int((~m).sum())))
    if len(years) < 2:
        return None
    actual = float(np.mean([np.median(r[m]) - np.median(r[~m]) for r, m in blocks]))
    null = np.empty(N_PERM)
    for i in range(N_PERM):
        sps = []
        for r, m in blocks:
            mm = rng.permutation(m)
            sps.append(np.median(r[mm]) - np.median(r[~mm]))
        null[i] = np.mean(sps)
    p = float(np.mean(np.abs(null) >= abs(actual)))
    return actual, p, len(years), per_year


def _one(label: str, sub: pd.DataFrame, mask: np.ndarray, rng: np.random.Generator,
         ret: str = "ret2") -> None:
    res = _block_perm(sub, mask, ret, rng)
    if res is None:
        print(f"  {label:40}: không đủ năm/nhóm hợp lệ"); return
    a, p, ny, py = res
    mark = "✓" if p < 0.05 else ("~" if p < 0.15 else "✗")
    spreads = " ".join(f"{y}:{sp*100:+.0f}%" for y, sp, _, _ in py)
    print(f"  {label:40}: TB {a*100:+5.1f}% p={p:.3f}{mark} ({ny}n) [{spreads}]")


def deep_value(df: pd.DataFrame, rng: np.random.Generator) -> None:
    """Câu hỏi quyết định: SỰ TINH VI (chuẩn hóa chu kỳ + chất lượng) có ăn tiền hơn 'rẻ+sạch'
    đơn giản không? Nếu KHÔNG → nên bỏ bớt phức tạp. Tất cả ở horizon 2 NĂM (ret2)."""
    df = df.copy()
    df["pe_norm"] = np.where((df["pe"] > 0) & (df["cyc_pos"] > 0), df["pe"] * df["cyc_pos"], np.nan)
    df["cheap"] = df.groupby("entry")["pb"].transform(
        lambda s: s <= s.median() if s.notna().any() else False)
    cn = df.groupby("entry")["pe_norm"].transform(
        lambda s: s <= s.median() if s.notna().any() else False)
    df["cheap_norm"] = cn & df["pe_norm"].notna()

    print(f"\n{'='*70}\nDEEP-DIVE: sự tinh vi có ĂN TIỀN hơn 'rẻ + sạch' đơn giản? (2 NĂM)\n{'='*70}")
    print("Q1 — Chuẩn hóa chu kỳ có HƠN rẻ P/B đơn giản không?")
    _one("Rẻ P/B (đơn giản, baseline)", df, df["cheap"].values, rng)
    _one("Rẻ P/E CHUẨN HÓA chu kỳ", df, df["cheap_norm"].values, rng)
    print("\nQ2 — TRONG nhóm rẻ, chất lượng có tách 'rẻ cơ hội' khỏi 'bẫy giá trị'?")
    cheap = df[df["cheap"]].reset_index(drop=True)
    _one("(trong rẻ) sạch cờ vs có cờ", cheap, (cheap["n_flags"] == 0).values, rng)
    _one("(trong rẻ) ROIC≥10% vs <10%", cheap, (cheap["roic_mean"] >= 0.10).values, rng)
    print("\nQ3 — Chất lượng có CỨU tín hiệu đáy-margin (đang thua −22%) không?")
    trough = df[df["cyc_pos"] < 0.9].reset_index(drop=True)
    _one("(trong đáy biên) sạch cờ vs có cờ", trough, (trough["n_flags"] == 0).values, rng)
    _one("(trong đáy biên) rẻ vs đắt", trough, (trough["cheap"]).values, rng)
    print("\nĐỌC: nếu 'chuẩn hóa' ≈ 'rẻ đơn giản' → phức tạp KHÔNG ăn tiền thêm. Nếu chất lượng")
    print("tách được trong nhóm rẻ/đáy → cầu P/B-ROE có ích. Vẫn small-n, đọc spread từng năm.")


def run() -> None:
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    df = collect()
    if df.empty:
        print("Không thu được dữ liệu."); return
    # ngưỡng rẻ P/B theo TỪNG năm vào lệnh (P/B trôi theo thời gian)
    df["cheap"] = df.groupby("entry")["pb"].transform(
        lambda s: s <= s.median() if s.notna().any() else False)
    df["buy"] = df["cheap"] & (df["n_flags"] == 0) & (df["roic_mean"] >= 0.10)

    print(f"\n{'='*70}\nBACKTEST ROLLING — vào lệnh cuối {ENTRY_YEARS}, N={len(df)} quan sát "
          f"(mã×năm)\n{'='*70}")
    print("Số quan sát mỗi năm vào lệnh:")
    for y, g in df.groupby("entry"):
        n1 = g["ret1"].notna().sum(); n2 = g["ret2"].notna().sum()
        print(f"  {y}: {len(g)} mã | có lợi nhuận 1n={n1}, 2n={n2}"
              + ("  (2n chưa đủ — tương lai)" if n2 == 0 else ""))

    signals = [
        ("Sạch cờ (0) vs có cờ", (df["n_flags"] == 0).values),
        ("Rẻ P/B vs đắt (theo năm)", df["cheap"].values),
        ("ROIC≥13% vs <13%", (df["roic_mean"] >= 0.13).values),
        ("ROIC tăng vs giảm", np.where(df["roic_trend"].notna(), (df["roic_trend"] > 0).values, np.nan)),
        ("Đáy biên (<0.9) vs còn lại", (df["cyc_pos"] < 0.9).values),
        ("Tổ hợp MUA vs còn lại", df["buy"].values),
    ]
    rng = np.random.default_rng(7)
    for retcol, hlabel in (("ret1", "1 NĂM"), ("ret2", "2 NĂM")):
        print(f"\n{'─'*70}\nHORIZON {hlabel} — permutation theo khối (xáo nhãn trong từng năm, "
              f"{N_PERM} lần)\n{'─'*70}")
        sig_ok = total = 0
        for label, mask in signals:
            res = _block_perm(df, mask, retcol, rng)
            if res is None:
                print(f"  {label:30}: không đủ năm hợp lệ"); continue
            actual, p, nyr, per_year = res
            total += 1
            mark = "✓" if p < 0.05 else ("~" if p < 0.15 else "✗")
            if p < 0.05:
                sig_ok += 1
            spreads = " ".join(f"{y}:{sp*100:+.0f}%" for y, sp, _, _ in per_year)
            print(f"  {label:30}: spread TB {actual*100:+5.1f}%  p={p:.3f} {mark}  "
                  f"({nyr} năm) [{spreads}]")
        print(f"\n  >>> {hlabel}: {sig_ok}/{total} tín hiệu đạt p<0.05 "
              f"(nhất quán qua các chế độ thị trường).")

    print(f"\n{'='*70}")
    print("ĐỌC: spread từng năm cho thấy tín hiệu có NHẤT QUÁN không (thắng cả năm sập lẫn năm")
    print("hồi?), hay chỉ đúng 1 năm rồi trung bình ra dương. Nhất quán + p thấp = đáng tin hơn.")
    print("Caveat: survivorship bias (chống phát hiện), cửa sổ 2-năm chồng lấn, chưa trừ phí.")

    deep_value(df, rng)


if __name__ == "__main__":
    run()
