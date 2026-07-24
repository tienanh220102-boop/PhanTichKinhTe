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

ĐÃ VÁ 2 LỖI MẪU (v2):
  1. SURVIVORSHIP BIAS — nay GỒM 221 cổ phiếu ĐÃ HỦY NIÊM YẾT (board=DELISTED của VCI, vẫn có
     giá tới ngày hủy + fundamentals). Mã hủy giữa chừng KHÔNG bị loại: dùng giá cuối cùng quan
     sát được làm giá thoát (vẫn NHẸ TAY vì người giữ thật thường mất nhiều hơn).
  2. LOOKAHEAD TRONG CHỌN UNIVERSE — bản cũ xếp thanh khoản HÔM NAY rồi áp ngược về quá khứ
     ('biết trước' mã nào sau này lớn). Nay universe tính TẠI THỜI ĐIỂM vào lệnh: GTGD bình quân
     180 ngày TRƯỚC ngày vào (pit_universe).

CAVEAT còn lại: 4 kỳ vẫn ít; cửa sổ 2-năm chồng lấn (2021→23, 2022→24 dùng chung 2023) → không
độc lập hoàn toàn; chưa trừ phí/trượt giá. Không phải bằng chứng cuối cùng.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from vn_data import VCIClient
from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout
from vn_sectors import VCISectors
from vn_backtest import _score_from_frames, _price_at

logger = logging.getLogger(__name__)

ENTRY_YEARS = [2021, 2022, 2023, 2024]     # vào lệnh cuối các năm này (cutoff = năm-1)
TOP_UNIVERSE = 150
N_PERM = 5000
MIN_GRP = 5                                 # tối thiểu mỗi nhóm/năm để tính spread


def _entry_date(y: int) -> pd.Timestamp:
    return pd.Timestamp(f"{y}-12-28")


def _price_at_ex(df: pd.DataFrame, target: pd.Timestamp,
                 global_last: pd.Timestamp) -> tuple:
    """Giá tại `target`, XỬ LÝ ĐÚNG MÃ BỊ HỦY NIÊM YẾT (chống survivorship bias).

    - target nằm trong chuỗi → giá gần nhất (như cũ).
    - chuỗi KẾT THÚC trước target NHƯNG thị trường vẫn chạy (target ≤ global_last) → mã đã bị
      HỦY/ngừng giao dịch: dùng GIÁ CUỐI CÙNG quan sát được (thua lỗ tới lúc hủy được tính vào,
      thay vì loại mã khỏi mẫu = giả vờ nó không tồn tại). THẬN TRỌNG: người giữ thật thường mất
      NHIỀU HƠN (bị đẩy xuống UPCoM/mất thanh khoản) → cách này VẪN nhẹ tay với mã xấu.
    - target > global_last (tương lai) → None.

    Trả (giá, đã_hủy_niêm_yết).
    """
    if df is None or df.empty:
        return None, False
    df = df.sort_values("date")
    last = df["date"].iloc[-1]
    if target > global_last:
        return None, False               # tương lai — chưa có dữ liệu
    if target > last:
        return float(df["close"].iloc[-1]), True   # đã hủy → giá cuối cùng quan sát được
    diff = (df["date"] - target).abs()
    i = diff.idxmin()
    if diff.loc[i] > pd.Timedelta(days=15):
        return None, False
    return float(df.loc[i, "close"]), False


def _ret(px: pd.DataFrame, y0: int, dyears: int, global_last: pd.Timestamp) -> tuple:
    """Trả (lợi nhuận thô, thoát_do_hủy_niêm_yết). Phí & phạt hủy áp ở tầng phân tích."""
    p0, _ = _price_at_ex(px, _entry_date(y0), global_last)
    p1, delisted = _price_at_ex(px, _entry_date(y0 + dyears), global_last)
    if p0 and p1 and p0 > 0 and p1 > 0:
        return p1 / p0 - 1, delisted
    return None, False


# --- Ma sát thực tế: phí giao dịch + phạt khi thoát do HỦY NIÊM YẾT ---
# Phí VN (khứ hồi, ước): mua ~0.15% + bán ~0.15% + thuế bán 0.1% + trượt giá ~0.2% ≈ 0.6%.
FEE_ROUNDTRIP = 0.006
# Mã bị hủy: "giá cuối quan sát được" VẪN NHẸ TAY (thực tế bị đẩy xuống UPCoM/mất thanh khoản,
# nhiều trường hợp gần như mất trắng). Không có ước lượng chuẩn cho VN → CHẠY ĐỘ NHẠY thay vì
# bịa 1 số. Lưu ý: một phần hủy niêm yết là do M&A/tự nguyện (kết cục TỐT) → phạt đồng loạt là
# HƠI NẶNG TAY; khoảng 0-50% ôm được sự thật.
DELIST_PENALTIES = (0.0, 0.30, 0.50)


def apply_frictions(df: pd.DataFrame, delist_penalty: float,
                    fee: float = FEE_ROUNDTRIP) -> pd.DataFrame:
    """Áp phí khứ hồi + phạt hủy niêm yết lên lợi nhuận thô → cột ret1/ret2 dùng để phân tích."""
    out = df.copy()
    for h, dcol in (("1", "del1"), ("2", "del2")):
        raw = pd.to_numeric(out.get(f"ret{h}_raw"), errors="coerce")
        gross = 1.0 + raw
        if dcol in out.columns:
            gross = gross * np.where(out[dcol].fillna(False).astype(bool), 1.0 - delist_penalty, 1.0)
        out[f"ret{h}"] = gross * (1.0 - fee) - 1.0
    return out


def pit_universe(px: Dict[str, pd.DataFrame], y: int, top: int,
                 lookback_days: int = 180, min_sessions: int = 60) -> List[str]:
    """Vũ trụ TẠI THỜI ĐIỂM vào lệnh: xếp theo GTGD bình quân trong ~180 ngày TRƯỚC ngày vào.

    Sửa lookahead: bản cũ dùng liquid_universe() tính theo thanh khoản HÔM NAY rồi áp ngược về
    quá khứ → 'biết trước' mã nào sau này lớn. Ở đây chỉ dùng dữ liệu có trước ngày vào lệnh.
    """
    end = _entry_date(y)
    start = end - pd.Timedelta(days=lookback_days)
    liq = []
    for s, df in px.items():
        if df is None or df.empty:
            continue
        w = df[(df["date"] > start) & (df["date"] <= end)]
        if len(w) < min_sessions:
            continue                      # chưa niêm yết / ngừng giao dịch quanh lúc đó
        liq.append((s, float(w["amount"].mean())))
    liq.sort(key=lambda x: -x[1])
    return [s for s, _ in liq[:top]]


_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "bt_roll_cache.csv")


_PX_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "bt_px_cache.pkl")
SYMBOLS_URL = "https://trading.vietcap.com.vn/api/price/symbols/getAll"


def _all_stock_symbols() -> List[str]:
    """MỌI mã cổ phiếu gồm ĐÃ HỦY NIÊM YẾT (board=DELISTED) — nền để khử survivorship bias."""
    import requests
    r = requests.get(SYMBOLS_URL, headers={"User-Agent": "Mozilla/5.0",
                                           "Referer": "https://trading.vietcap.com.vn/"}, timeout=30)
    data = r.json()
    return [x["symbol"] for x in data
            if x.get("type") == "STOCK" and x.get("symbol")]


def fetch_all_prices(dc: VCIClient) -> Dict[str, pd.DataFrame]:
    """Giá ~10.5 năm cho TOÀN BỘ cổ phiếu (gồm mã hủy). Cache pickle vì tải rất nặng."""
    if os.path.exists(_PX_CACHE):
        logger.warning("Nạp cache giá %s", _PX_CACHE)
        return pd.read_pickle(_PX_CACHE)
    syms = _all_stock_symbols()
    logger.warning("Tải giá %d mã (gồm mã đã hủy) — nặng, chỉ 1 lần...", len(syms))
    px = dc.get_ohlcv(syms, days=3900)
    try:
        os.makedirs(os.path.dirname(_PX_CACHE), exist_ok=True)
        pd.to_pickle(px, _PX_CACHE)
    except Exception:  # noqa: BLE001
        pass
    return px


def collect(use_cache: bool = True) -> pd.DataFrame:
    """Thu thập quan sát (mã × năm vào lệnh) với universe POINT-IN-TIME + mã đã hủy niêm yết."""
    if use_cache and os.path.exists(_CACHE):
        logger.warning("Nạp cache %s (xóa để tải mới)", _CACHE)
        return pd.read_csv(_CACHE)
    fx = VCIFundamentals(); sx = VCISectors(); dc = VCIClient()
    px = fetch_all_prices(dc)
    global_last = max((df["date"].iloc[-1] for df in px.values() if df is not None and not df.empty),
                      default=pd.Timestamp.today())
    imap = sx.get_industry_map()
    bankset = set(imap[imap["is_bank"] == True]["symbol"]) if "is_bank" in imap else set()  # noqa: E712

    # vũ trụ TẠI TỪNG thời điểm vào lệnh (không dùng thanh khoản hôm nay)
    uni_by_year = {y: pit_universe(px, y, TOP_UNIVERSE) for y in ENTRY_YEARS}
    need = sorted({s for lst in uni_by_year.values() for s in lst} - bankset)
    logger.warning("Universe point-in-time: %s | cần fundamentals %d mã",
                   {y: len(v) for y, v in uni_by_year.items()}, len(need))

    frames: Dict[str, tuple] = {}
    for s in need:
        try:
            frames[s] = (fx.get_statement(s, "INCOME_STATEMENT", "year"),
                         fx.get_statement(s, "CASH_FLOW", "year"),
                         fx.get_ratios(s))
        except Exception:  # noqa: BLE001
            continue

    rows: List[dict] = []
    for y in ENTRY_YEARS:
        for s in uni_by_year[y]:
            if s in bankset or s not in frames or s not in px:
                continue
            inc, cf, ratios = frames[s]
            sc = _score_from_frames(inc, cf, ratios, cutoff=y - 1)   # số ≤ năm trước
            if sc is None:
                continue
            r1, d1 = _ret(px[s], y, 1, global_last)
            r2, d2 = _ret(px[s], y, 2, global_last)
            if r1 is None and r2 is None:
                continue
            rows.append({"sym": s, "entry": y, **sc,
                         "ret1_raw": r1, "ret2_raw": r2, "del1": d1, "del2": d2})
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


BASE_PENALTY = 0.30      # giả định cơ sở cho phạt hủy niêm yết (xem độ nhạy cuối báo cáo)


def sensitivity(raw: pd.DataFrame, rng: np.random.Generator) -> None:
    """Kết luận có ĐỔI theo giả định phạt hủy niêm yết không? (giả định lạc quan hay đảo kết luận)"""
    print(f"\n{'='*70}\nĐỘ NHẠY — phạt khi thoát do HỦY NIÊM YẾT (2 NĂM, đã trừ phí "
          f"{FEE_ROUNDTRIP*100:.1f}%)\n{'='*70}")
    print(f"  {'phạt hủy':>9} | {'sạch cờ':>16} | {'rẻ P/B':>16} | {'ROIC≥13%':>16} | {'tổ hợp MUA':>16}")
    for pen in DELIST_PENALTIES:
        d = apply_frictions(raw, pen)
        d["cheap"] = d.groupby("entry")["pb"].transform(
            lambda s: s <= s.median() if s.notna().any() else False)
        d["buy"] = d["cheap"] & (d["n_flags"] == 0) & (d["roic_mean"] >= 0.10)
        cells = []
        for mask in ((d["n_flags"] == 0).values, d["cheap"].values,
                     (d["roic_mean"] >= 0.13).values, d["buy"].values):
            res = _block_perm(d, mask, "ret2", rng)
            cells.append(f"{res[0]*100:+5.1f}% p={res[1]:.3f}" if res else "      n/a     ")
        print(f"  {pen*100:>8.0f}% | " + " | ".join(cells))
    n_del = int(pd.to_numeric(raw.get("del2"), errors="coerce").fillna(0).astype(bool).sum())
    print(f"\nKẾT LUẬN BỀN nếu dấu & ý nghĩa GIỮ NGUYÊN qua mọi mức phạt. Phạt 0% = nhẹ tay nhất")
    print("(mã hủy thoát ở giá cuối); 50% = nặng tay (một phần hủy là M&A/tự nguyện, kết cục tốt).")
    if n_del < 0.05 * len(raw):
        print(f"⚠️ CHỈ {n_del}/{len(raw)} quan sát thoát do hủy → độ nhạy này KHÔNG cung cấp thông "
              "tin (dùng TRUNG VỊ nên vài quan sát không dịch được kết quả). ĐỪNG đọc thành 'kết "
              "luận bền vững trước survivorship'.")
        print("   ĐÍNH CHÍNH ATTRIBUTION: cú lật 'mua rẻ' (+13.6%→−9.2%) KHÔNG do thêm mã hủy "
              "(chỉ 6 mã: FLC/ROS/HAI/AMD/KLF/BII) mà do SỬA LOOKAHEAD UNIVERSE — 96 mã (172/525 "
              "quan sát, 33%) từng thanh khoản cao nhưng nay TEO khỏi top-150. Universe cũ xếp theo "
              "thanh khoản HÔM NAY = chỉ chọn mã đã SỐNG VÀ LỚN LÊN. Rủi ro lớn hơn 'chết' là 'TEO'.")


def run() -> None:
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    raw = collect()
    if raw.empty:
        print("Không thu được dữ liệu."); return
    n_del2 = int(pd.to_numeric(raw.get("del2"), errors="coerce").fillna(0).astype(bool).sum())
    df = apply_frictions(raw, BASE_PENALTY)
    print(f"\n[Ma sát] phí khứ hồi {FEE_ROUNDTRIP*100:.1f}% + phạt hủy niêm yết "
          f"{BASE_PENALTY*100:.0f}% (cơ sở) · {n_del2} quan sát thoát do hủy ở mốc 2 năm")
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
    sensitivity(raw, rng)


if __name__ == "__main__":
    run()
