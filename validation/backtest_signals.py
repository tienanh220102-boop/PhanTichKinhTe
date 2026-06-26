#!/usr/bin/env python3
"""Backtest tín hiệu rule-based — đo edge thực của MUA/BÁN/GIỮ.

Câu hỏi: tín hiệu `classify_trend_signal` (MA20/MA50 + RSI14) có dự báo được
hướng đi tiếp theo không, hay gần như ngẫu nhiên?

Nguyên tắc trung thực (xem README):
- TÁI DÙNG `classify_trend_signal` của production — KHÔNG viết lại để khỏi lệch.
- KHÔNG nhìn trước (no lookahead): chỉ báo tại ngày t chỉ dùng dữ liệu ≤ t
  (MA = rolling mean tới t; RSI Wilder ewm là đệ quy nên giá trị tại t chỉ phụ
  thuộc quá khứ). Forward return đo t → t+h.
- So với BASELINE (drift vô điều kiện) — edge = vượt baseline, không phải "có lãi".
- v1 CHƯA trừ phí & cửa sổ chồng lấn (xem caveat cuối báo cáo).

Chạy tay (không nằm trong cron):  python validation/backtest_signals.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / 'scripts'))

import numpy as np
import pandas as pd
from commodity_agent import classify_trend_signal, YFINANCE_SYMBOLS  # production logic

HORIZONS = [5, 10, 20]          # số phiên forward return
PERIOD   = '5y'                 # lịch sử để có đủ mẫu (production chỉ dùng 1y khi chạy live)
OUT      = _ROOT / 'outputs'


def indicators_history(close: pd.Series) -> pd.DataFrame:
    """Tái dựng ma20/ma50/rsi14 theo ĐÚNG công thức fetch_prices_yfinance, cho mọi t."""
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs   = gain / loss.replace(0, np.nan)
    rsi  = 100 - 100 / (1 + rs)
    return pd.DataFrame({'value': close, 'ma20': ma20, 'ma50': ma50, 'rsi14': rsi})


def signal_family(sig: str) -> str:
    """Gom về 3 họ long/short/neutral. Nhận CẢ nhãn cũ (MUA/BÁN) lẫn nhãn mô tả mới
    ('Nghiêng tăng/giảm') sau relabel — để backtest không vỡ thầm lặng khi đổi nhãn."""
    s = sig.lower()
    if s.startswith('mua') or 'nghiêng tăng' in s:
        return 'MUA'
    if s.startswith('bán') or 'nghiêng giảm' in s:
        return 'BÁN'
    return 'GIỮ'


def collect(close: pd.Series) -> list[dict]:
    """Mỗi phiên → (tín hiệu, forward return từng horizon). No lookahead."""
    ind = indicators_history(close)
    closes = close.values
    n = len(closes)
    rows = []
    for t in range(n):
        e = ind.iloc[t]
        if pd.isna(e['ma50']):            # chưa đủ 50 phiên → bỏ qua đoạn đầu
            continue
        rsi = None if pd.isna(e['rsi14']) else float(e['rsi14'])
        trend, sig = classify_trend_signal(
            {'value': float(e['value']), 'ma20': float(e['ma20']),
             'ma50': float(e['ma50']), 'rsi14': rsi})
        row = {'trend': trend, 'signal': sig, 'family': signal_family(sig)}
        for h in HORIZONS:
            row[f'fwd{h}'] = (closes[t + h] / closes[t] - 1) * 100 if t + h < n else np.nan
        rows.append(row)
    return rows


def fmt_pct(x):
    return f'{x:+.2f}%' if pd.notna(x) else '  N/A'


def main():
    import yfinance as yf
    symbols = list(YFINANCE_SYMBOLS.values())
    name_by_sym = {v: k for k, v in YFINANCE_SYMBOLS.items()}
    print(f'Tải {len(symbols)} symbol, period={PERIOD} ...')
    raw = yf.download(symbols, period=PERIOD, progress=False, auto_adjust=True)

    all_rows = []
    per_symbol_baseline = {}
    for sym in symbols:
        try:
            close = (raw[('Close', sym)] if ('Close', sym) in raw.columns else raw['Close']).dropna()
        except Exception:
            continue
        if len(close) < 80:
            continue
        rows = collect(close)
        nm = name_by_sym.get(sym, sym)
        for r in rows:
            r['symbol'] = nm
        all_rows.extend(rows)
        # baseline: drift vô điều kiện của chính symbol đó
        per_symbol_baseline[nm] = {
            h: float(np.nanmean([(close.values[t + h] / close.values[t] - 1) * 100
                                 for t in range(len(close) - h)]))
            for h in HORIZONS}

    df = pd.DataFrame(all_rows)
    if df.empty:
        print('Không có dữ liệu — kiểm tra mạng/yfinance.')
        return

    lines = []
    def out(s=''):
        print(s); lines.append(s)

    out('=' * 72)
    out('BACKTEST TÍN HIỆU RULE-BASED (MA20/MA50 + RSI14)')
    out(f'Mẫu: {len(df):,} phiên-tín hiệu | {df["symbol"].nunique()} symbol | period={PERIOD}')
    out('=' * 72)

    # Baseline tổng hợp (drift trung bình mọi phiên mọi symbol)
    out('\n— BASELINE (drift vô điều kiện, mọi phiên) —')
    base = {h: df[f'fwd{h}'].mean() for h in HORIZONS}
    out('  ' + ' | '.join(f'fwd{h}: {fmt_pct(base[h])}' for h in HORIZONS))

    # Theo lớp tín hiệu
    out('\n— FORWARD RETURN THEO LỚP TÍN HIỆU —')
    out('  (edge = mean fwd vượt baseline; hit = % đúng hướng kỳ vọng)')
    for fam in ['MUA', 'BÁN', 'GIỮ']:
        sub = df[df['family'] == fam]
        if sub.empty:
            continue
        out(f'\n  [{fam}]  n={len(sub):,}  ({len(sub)/len(df)*100:.0f}% số phiên)')
        for h in HORIZONS:
            col = sub[f'fwd{h}'].dropna()
            if col.empty:
                continue
            mean = col.mean()
            edge = mean - base[h]
            if fam == 'MUA':
                hit = (col > 0).mean() * 100
            elif fam == 'BÁN':
                hit = (col < 0).mean() * 100
            else:
                hit = (col.abs() < col.abs().median()).mean() * 100  # GIỮ: ít biến động?
            out(f'    fwd{h:>2}: mean {fmt_pct(mean)} | edge {fmt_pct(edge)} '
                f'| hit {hit:4.0f}% | median {fmt_pct(col.median())}')

    # Tín hiệu giao dịch thực (MUA vs BÁN) — chênh lệch là thứ đáng tin nhất
    out('\n— SPREAD MUA−BÁN (nếu tín hiệu có edge, MUA phải > BÁN) —')
    for h in HORIZONS:
        mua = df[df['family'] == 'MUA'][f'fwd{h}'].mean()
        ban = df[df['family'] == 'BÁN'][f'fwd{h}'].mean()
        spread = mua - ban
        verdict = 'CÓ tín hiệu' if spread > 0 else 'NGƯỢC kỳ vọng' if spread < 0 else '~0'
        out(f'  fwd{h:>2}: MUA {fmt_pct(mua)} − BÁN {fmt_pct(ban)} = {fmt_pct(spread)}  → {verdict}')

    out('\n' + '-' * 72)
    out('CAVEAT (đọc trước khi tin):')
    out('  • In-sample, CHƯA trừ phí/spread — edge dương phải đủ lớn để sống sau chi phí.')
    out('  • Cửa sổ forward CHỒNG LẤN → các quan sát không độc lập, ý nghĩa thống kê bị thổi phồng.')
    out('  • Tín hiệu trend-following ⇒ tương quan momentum; MUA có fwd>0 KHÔNG đồng nghĩa edge tradeable.')
    out('  • Đây là đo lường để BIẾT SỰ THẬT, không phải để bật tiền thật.')
    out('-' * 72)

    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / 'validation_backtest_signals.txt'
    report.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\n→ Đã lưu: {report}')


if __name__ == '__main__':
    main()
