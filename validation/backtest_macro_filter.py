#!/usr/bin/env python3
"""Backtest CÓ LỌC VĨ MÔ — kiểm định: điều kiện hóa theo DXY / real yield có
tạo ra edge mà tín hiệu trần (backtest_signals.py) không có không?

Giả thuyết grounded từ methodology/01:
  H1 (USD): long hàng hóa hoạt động tốt hơn khi USD YẾU (DXY < MA20).
  H2 (vàng): vàng tăng tốt hơn khi REAL YIELD GIẢM (DFII10 đang xuống).

Cách đo: so mean forward-return của trạng thái "Nghiêng tăng" trong 2 chế độ
vĩ mô (thuận lợi vs bất lợi). Nếu lọc có giá trị, chênh lệch phải DƯƠNG và đủ
lớn để vượt phí. No lookahead: chế độ vĩ mô tại ngày t chỉ dùng dữ liệu ≤ t.

Chạy tay:  python validation/backtest_macro_filter.py
Caveat: in-sample, chồng lấn, chưa phí — xem README.
"""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT.parent / 'scripts'))
from backtest_signals import indicators_history, signal_family  # noqa: E402
from commodity_agent import classify_trend_signal, YFINANCE_SYMBOLS  # noqa: E402

HORIZONS = [5, 10, 20]
PERIOD = '5y'
COSD = '2019-06-01'


def fetch_fred_series(series_id: str, cosd: str) -> pd.Series:
    """Full history keyless qua fredgraph.csv (một lần, không như fetch live 90 ngày)."""
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={cosd}'
    txt = requests.get(url, timeout=40).text
    df = pd.read_csv(io.StringIO(txt))
    dcol, vcol = df.columns[0], df.columns[1]
    df[dcol] = pd.to_datetime(df[dcol])
    df[vcol] = pd.to_numeric(df[vcol].replace('.', np.nan), errors='coerce')
    return df.set_index(dcol)[vcol].dropna()


def lean_frame(close: pd.Series) -> pd.DataFrame:
    """Mỗi ngày → family (MUA/BÁN/GIỮ) + forward returns, index = ngày. No lookahead."""
    ind = indicators_history(close)
    closes = close.values
    n = len(closes)
    recs = []
    for t in range(n):
        e = ind.iloc[t]
        if pd.isna(e['ma50']):
            continue
        rsi = None if pd.isna(e['rsi14']) else float(e['rsi14'])
        _, sig = classify_trend_signal(
            {'value': float(e['value']), 'ma20': float(e['ma20']),
             'ma50': float(e['ma50']), 'rsi14': rsi})
        row = {'date': close.index[t], 'family': signal_family(sig)}
        for h in HORIZONS:
            row[f'fwd{h}'] = (closes[t + h] / closes[t] - 1) * 100 if t + h < n else np.nan
        recs.append(row)
    return pd.DataFrame(recs).set_index('date')


def daily_mask_to_array(mask_daily: pd.Series, target_index) -> np.ndarray:
    """Ánh xạ chế độ vĩ mô (mask theo ngày, sorted) lên từng dòng target (có thể trùng ngày)."""
    src = mask_daily[~mask_daily.index.duplicated()].sort_index()
    all_dates = pd.DatetimeIndex(sorted(set(target_index)))
    aligned = src.reindex(all_dates, method='ffill')          # sorted unique → ffill hợp lệ
    lut = {d: bool(v) if pd.notna(v) else False for d, v in aligned.items()}
    return np.array([lut.get(d, False) for d in target_index], dtype=bool)


def fmt(x):
    return f'{x:+.2f}%' if pd.notna(x) else '  N/A'


def regime_split(df, good_arr, label_good, label_bad, title, lines):
    """mean fwd của 'Nghiêng tăng' (family MUA) ở 2 chế độ + chênh lệch. good_arr: bool[] theo dòng."""
    out = lines.append
    out(f'\n— {title} —')
    is_long = (df['family'] == 'MUA').to_numpy()
    gm = np.asarray(good_arr, dtype=bool)
    for h in HORIZONS:
        col = df[f'fwd{h}'].to_numpy()
        valid = ~np.isnan(col)
        g = col[is_long & gm & valid]
        b = col[is_long & ~gm & valid]
        if len(g) == 0 or len(b) == 0:
            continue
        diff = g.mean() - b.mean()
        verdict = 'lọc CÓ giá trị' if diff > 0 else 'lọc VÔ ích/ngược'
        out(f'  fwd{h:>2}: {label_good} {fmt(g.mean())} (n={len(g)}) | '
            f'{label_bad} {fmt(b.mean())} (n={len(b)}) | chênh {fmt(diff)} → {verdict}')


def main():
    import yfinance as yf
    syms = list(YFINANCE_SYMBOLS.values())
    name_by = {v: k for k, v in YFINANCE_SYMBOLS.items()}
    print('Tải giá hàng hóa + DXY ...')
    raw = yf.download(syms + ['DX-Y.NYB'], period=PERIOD, progress=False, auto_adjust=True)

    def close_of(sym):
        return (raw[('Close', sym)] if ('Close', sym) in raw.columns else raw['Close']).dropna()

    dxy = close_of('DX-Y.NYB')
    dxy_weak = (dxy < dxy.rolling(20).mean())             # USD yếu = DXY dưới MA20

    print('Tải DFII10 (FRED full history) ...')
    dfii = fetch_fred_series('DFII10', COSD)
    dfii_falling = dfii.diff(5) < 0                        # real yield 5 phiên giảm

    lines = []
    def out(s=''):
        print(s); lines.append(s)

    out('=' * 72)
    out('BACKTEST CÓ LỌC VĨ MÔ — DXY (USD) & DFII10 (real yield)')
    out(f'period={PERIOD} | giả thuyết: USD yếu→long hàng hóa; real yield giảm→long vàng')
    out('=' * 72)

    # H1: gộp toàn bộ hàng hóa, lọc theo USD yếu/mạnh
    frames = []
    for sym in syms:
        c = close_of(sym)
        if len(c) >= 80:
            lf = lean_frame(c)
            lf['symbol'] = name_by.get(sym, sym)
            frames.append(lf)
    big = pd.concat(frames)
    usd_arr = daily_mask_to_array(dxy_weak, big.index)
    regime_split(big, usd_arr, 'USD yếu ', 'USD mạnh',
                 'H1 — LONG HÀNG HÓA theo chế độ USD (mọi mặt hàng)', lines)

    # H2: chỉ vàng, lọc theo real yield giảm/tăng
    gold = lean_frame(close_of(YFINANCE_SYMBOLS['Gold']))
    ry_arr = daily_mask_to_array(dfii_falling, gold.index)
    regime_split(gold, ry_arr, 'RY giảm ', 'RY tăng ',
                 'H2 — LONG VÀNG theo chế độ real yield (DFII10)', lines)

    # Đối chứng: vàng mọi phiên (không lọc theo lean), real yield giảm vs tăng
    out('\n— ĐỐI CHỨNG: vàng MỌI phiên, real yield giảm vs tăng —')
    for h in HORIZONS:
        col = gold[f'fwd{h}'].to_numpy()
        valid = ~np.isnan(col)
        a = col[ry_arr & valid]; b = col[~ry_arr & valid]
        if len(a) and len(b):
            out(f'  fwd{h:>2}: RY giảm {fmt(a.mean())} (n={len(a)}) | '
                f'RY tăng {fmt(b.mean())} (n={len(b)}) | chênh {fmt(a.mean()-b.mean())}')

    out('\n' + '-' * 72)
    out('CAVEAT: in-sample, cửa sổ chồng lấn, CHƯA trừ phí. Chênh lệch vài phần trăm-điểm')
    out('mỗi 1-4 tuần, không nhất quán giữa các horizon → gần như chắc nằm trong nhiễu,')
    out('KHÔNG đủ làm edge giao dịch. Đọc như "có/không tín hiệu", không phải "có lãi".')
    out('-' * 72)

    rp = _ROOT.parent / 'outputs' / 'validation_macro_filter.txt'
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\n→ Đã lưu: {rp}')


if __name__ == '__main__':
    main()
