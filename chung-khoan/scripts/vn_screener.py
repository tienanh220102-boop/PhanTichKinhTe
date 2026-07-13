# -*- coding: utf-8 -*-
"""
Bộ lọc (screener) toàn thị trường chứng khoán VN — chọn shortlist mã đáng phân tích sâu.

Chạy TRƯỚC tầng phân tích LLM: quét ~1500 mã (HOSE/HNX/UPCoM) bằng chỉ báo kỹ thuật
(KHÔNG dùng LLM, nhanh, rẻ), chấm điểm rồi in ra top-N mã dạng `FPT.VN,ACV.VN,...`
để nạp vào `main.py --stocks`.

Khẩu vị TRUNG LẬP: bắt CẢ hai nhóm cơ hội —
  (A) Đà tăng / breakout: xu hướng tăng rõ, vượt đỉnh, khối lượng ủng hộ.
  (B) Quá bán CÓ tín hiệu đảo chiều: giảm sâu nhưng đã có nến/khối lượng hồi.
      → CHỦ ĐỘNG LOẠI 'dao rơi': giảm sâu, gãy dưới MA50, còn đỏ, không có dấu hồi.

LƯU Ý phân vai: screener chỉ lọc ỨNG VIÊN có cơ sở kỹ thuật. Việc phán 'cú giảm là
tin xấu cơ bản hay bán quá đà có thể hồi' thuộc TẦNG LLM phía sau (search tin tức +
cơ bản + catalyst/rủi ro cho từng mã). Screener không tự kết luận mua/bán.

Nguồn: API công khai VCI (Vietcap), gọi trực tiếp (requests + pandas), độc lập & nhẹ.

Dùng:
    python scripts/vn_screener.py --top 30 --boards HOSE,HNX,UPCoM
stdout = CSV shortlist (workflow capture). Bảng chẩn đoán in ra stderr.
"""

from __future__ import annotations

import sys
import time
import argparse
from datetime import datetime

import requests
import pandas as pd
import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://trading.vietcap.com.vn"
SYMBOLS_URL = f"{BASE}/api/price/symbols/getAll"
OHLC_URL = f"{BASE}/api/chart/OHLCChart/gap"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}
BOARD_MAP = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCoM"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get_universe(session, boards):
    r = session.get(SYMBOLS_URL, timeout=30)
    r.raise_for_status()
    rows = []
    for it in r.json():
        if it.get("type") != "STOCK":
            continue
        b = BOARD_MAP.get(str(it.get("board", "")).upper())
        if b is None or b not in boards:
            continue
        rows.append({"symbol": it.get("symbol"), "board": b,
                     "name": it.get("organShortName") or it.get("organName") or it.get("symbol")})
    return pd.DataFrame(rows).dropna(subset=["symbol"]).drop_duplicates("symbol").reset_index(drop=True)


def get_ohlcv(session, symbols, days=160, batch=60):
    to_ts = int(time.time())
    from_ts = to_ts - days * 86400
    out = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        try:
            r = session.post(OHLC_URL, json={"timeFrame": "ONE_DAY", "symbols": chunk,
                                             "from": from_ts, "to": to_ts}, timeout=30)
            r.raise_for_status()
            for e in r.json() or []:
                if len(e.get("t") or []) < 30:
                    continue
                out[e.get("symbol")] = pd.DataFrame({
                    "close": e.get("c"), "open": e.get("o"),
                    "high": e.get("h"), "low": e.get("l"), "volume": e.get("v"),
                })
        except Exception as ex:  # noqa: BLE001
            log(f"  [warn] batch {i} lỗi: {ex}")
        time.sleep(0.35)
    return out


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def macd_hist(close):
    ef = close.ewm(span=12, adjust=False).mean()
    es = close.ewm(span=26, adjust=False).mean()
    line = ef - es
    return (line - line.ewm(span=9, adjust=False).mean()).iloc[-1]


def build_metrics(sym, df):
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    h = df["high"].astype(float)
    lo = df["low"].astype(float)
    o = df["open"].astype(float)
    if len(c) < 30:
        return None
    ma20 = c.rolling(20).mean().iloc[-1]
    ma50 = c.rolling(50).mean().iloc[-1] if len(c) >= 50 else np.nan
    volma20 = v.rolling(20).mean().iloc[-1]
    def f(x):
        return None if x is None or pd.isna(x) else float(x)
    return {
        "symbol": sym, "price": float(c.iloc[-1]),
        "rsi": f(rsi(c).iloc[-1]), "ma20": f(ma20), "ma50": f(ma50),
        "macd_hist": f(macd_hist(c)),
        "open": float(o.iloc[-1]), "high": float(h.iloc[-1]), "low": float(lo.iloc[-1]),
        "hi60": float(h.tail(60).max()),
        "vol_ratio": f(v.iloc[-1] / volma20) if volma20 and not pd.isna(volma20) else None,
        "chg_1d": float((c.iloc[-1] / c.iloc[-2] - 1) * 100) if len(c) > 1 else None,
        "chg_5d": float((c.iloc[-1] / c.iloc[-6] - 1) * 100) if len(c) > 5 else None,
        "chg_20d": float((c.iloc[-1] / c.iloc[-21] - 1) * 100) if len(c) > 21 else None,
        "turnover20": float((c * v).tail(20).mean()),
    }


def score_momentum(m):
    """Nhóm A — đà tăng / breakout."""
    s, why = 0.0, []
    if m["ma20"] and m["ma50"] and m["price"] > m["ma20"] > m["ma50"]:
        s += 3; why.append("giá > MA20 > MA50 (xu hướng tăng)")
    if m["macd_hist"] is not None and m["macd_hist"] > 0:
        s += 1; why.append("MACD dương")
    if m["hi60"] and m["price"] >= 0.98 * m["hi60"]:
        s += 1.5; why.append("vượt/áp sát đỉnh 60 phiên")
    if m["vol_ratio"] and m["vol_ratio"] >= 1.5 and (m["chg_1d"] or 0) > 0:
        s += 1; why.append("bùng khối lượng theo chiều tăng")
    if m["chg_20d"] is not None and m["chg_20d"] > 8:
        s += 1; why.append(f"tăng {m['chg_20d']:.0f}% trong 20 phiên")
    # không quá nóng: RSI quá cao thì bớt hấp dẫn (rủi ro đu đỉnh)
    if m["rsi"] is not None and m["rsi"] >= 80:
        s -= 1; why.append(f"RSI {m['rsi']:.0f} quá mua")
    return s, why


def score_reversal(m):
    """Nhóm B — quá bán CÓ tín hiệu đảo chiều; loại 'dao rơi'."""
    r = m["rsi"]
    if r is None or r > 45:
        return 0.0, []
    # loại dao rơi: gãy quá sâu dưới MA50, hoặc còn giảm mạnh hôm nay, hoặc không có nến hồi
    falling_knife = (m["ma50"] and m["price"] < m["ma50"] * 0.72) or ((m["chg_1d"] or 0) < -3)
    recovered = ((m["chg_1d"] or 0) > 0) or (m["close_gt_open"]) or \
                (m["high"] > m["low"] and m["price"] >= m["low"] + 0.5 * (m["high"] - m["low"]))
    if falling_knife or not recovered:
        return 0.0, []  # quá bán nhưng chưa có dấu hồi / rơi gãy → bỏ (để LLM khỏi phải gỡ rác)
    s, why = 0.0, []
    if r <= 30: s += 3; why.append(f"RSI {r:.0f} quá bán sâu")
    elif r <= 38: s += 2; why.append(f"RSI {r:.0f} quá bán")
    else: s += 1; why.append(f"RSI {r:.0f} yếu")
    if m["ma20"] and m["price"] < m["ma20"]:
        disc = (m["ma20"] - m["price"]) / m["ma20"]
        if disc >= 0.05: s += 1; why.append(f"chiết khấu {disc*100:.0f}% dưới MA20")
    why.append("đã có nến/độ nảy hồi phục")  # điều kiện recovered ở trên
    if m["chg_5d"] is not None and m["chg_5d"] < -3:
        s += 0.5; why.append(f"vừa bị bán {abs(m['chg_5d']):.0f}% tuần qua")
    return s, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--boards", default="HOSE,HNX,UPCoM")
    ap.add_argument("--min-turnover", type=float, default=5e8,
                    help="Sàn thanh khoản tối thiểu (đồng/phiên, TB 20 phiên)")
    args = ap.parse_args()
    boards = {BOARD_MAP.get(b.strip().upper(), b.strip()) for b in args.boards.split(",")}

    session = requests.Session(); session.headers.update(HEADERS)
    log(f"[screener] {datetime.now():%Y-%m-%d %H:%M} | sàn={sorted(boards)} | khẩu vị=TRUNG LẬP | top={args.top}")
    uni = get_universe(session, boards)
    log(f"[screener] vũ trụ: {len(uni)} mã ({uni['board'].value_counts().to_dict()})")
    ohlcv = get_ohlcv(session, uni["symbol"].tolist())
    log(f"[screener] lấy được OHLCV: {len(ohlcv)} mã")

    name_of = dict(zip(uni["symbol"], uni["name"]))
    board_of = dict(zip(uni["symbol"], uni["board"]))
    rows = []
    for sym, df in ohlcv.items():
        m = build_metrics(sym, df)
        if m:
            m["board"] = board_of.get(sym); m["name"] = name_of.get(sym, sym)
            m["close_gt_open"] = m["price"] > m["open"]
            rows.append(m)

    turns = np.array([r["turnover20"] for r in rows if r["turnover20"] > 0])
    gate = max(float(np.percentile(turns, 50)) if len(turns) else 0, args.min_turnover)
    liquid = [r for r in rows if r["turnover20"] >= gate]
    log(f"[screener] cổng thanh khoản ≈ {gate/1e9:.2f} tỷ/phiên → còn {len(liquid)}/{len(rows)} mã")

    for r in liquid:
        sm, wm = score_momentum(r)
        sr, wr = score_reversal(r)
        if sm >= sr:
            r["score"], r["type"], r["reasons"] = sm, "ĐÀ TĂNG", "; ".join(wm)
        else:
            r["score"], r["type"], r["reasons"] = sr, "QUÁ BÁN-HỒI", "; ".join(wr)
    # chỉ giữ mã có điểm dương (có cơ sở kỹ thuật thực sự)
    cand = [r for r in liquid if r["score"] > 0]
    cand.sort(key=lambda r: (r["score"], r["turnover20"]), reverse=True)
    top = cand[:args.top]

    n_mom = sum(1 for r in top if r["type"] == "ĐÀ TĂNG")
    log(f"\n[screener] SHORTLIST top {len(top)}  (đà tăng: {n_mom} | quá bán-hồi: {len(top)-n_mom})")
    log(f"  {'Mã':6} {'Sàn':5} {'Nhóm':11} {'Giá':>9} {'RSI':>4} {'Δ1p':>6} {'Δ20p':>7} {'GTGD tỷ':>8} {'Điểm':>5}  Lý do")
    for r in top:
        log(f"  {r['symbol']:6} {r['board']:5} {r['type']:11} {r['price']:>9,.0f} "
            f"{(r['rsi'] or 0):>4.0f} {(r['chg_1d'] or 0):>+6.1f} {(r['chg_20d'] or 0):>+7.1f} "
            f"{r['turnover20']/1e9:>8.1f} {r['score']:>5.1f}  {r['reasons']}")
    log("\n[screener] Lưu ý: đây là ứng viên kỹ thuật. Tầng LLM sẽ xét tin tức/cơ bản để "
        "phân biệt 'tin xấu nên tránh' với 'bán quá đà có thể hồi', và ra khuyến nghị cuối.")

    print(",".join(f"{r['symbol']}.VN" for r in top))  # stdout = shortlist


if __name__ == "__main__":
    main()
