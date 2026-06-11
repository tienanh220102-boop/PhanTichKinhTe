#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test quant engine — chạy tay, cần mạng, KHÔNG cần Telegram/Gemini key:
    python tests/test_quant_smoke.py
Kiểm tra: yfinance indicators, tín hiệu rule-based, bảng số liệu,
liên thị trường, CFTC COT, hiệu suất tuần, prompt build.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

import commodity_agent as ca


def main():
    print('=== 1. yfinance (1y + indicators) ===')
    prices = ca.fetch_prices_yfinance()
    assert prices, 'yfinance khong tra ve gia nao'
    sample = next(iter(prices.values()))
    for key in ('value', 'chg_pct', 'ma20', 'ma50', 'rsi14', 'atr_pct', 'pos52w'):
        assert key in sample, f'thieu chi bao: {key}'
    print(f'OK — {len(prices)} symbols, sample keys: {sorted(sample.keys())}')

    print('=== 2. Tin hieu rule-based ===')
    for name, e in prices.items():
        trend, signal = ca.classify_trend_signal(e)
        sup, res = ca.support_resistance(e)
        print(f'  {name}: {trend} / {signal} | S/R: {sup} / {res}')

    print('=== 3. Bang so lieu ===')
    table = ca.build_quant_table(prices)
    assert table and len(table.splitlines()) >= 5
    print(table)

    print('=== 4. Lien thi truong ===')
    for line in ca.build_cross_asset_lines(prices):
        print(f'  {line}')

    print('=== 5. CFTC COT (structured + WoW state) ===')
    state = {}
    cot = ca.build_cot_block(state)
    if cot:
        print(cot)
        assert state.get('cot_history'), 'cot_history khong duoc luu vao state'
    else:
        print('  COT khong fetch duoc (mang/CFTC down) — chap nhan duoc')

    print('=== 6. Hieu suat tuan ===')
    perf = ca.build_weekly_perf_block(prices)
    assert perf
    print(perf)

    print('=== 7. Prompt build (khong goi Gemini) ===')
    fake_articles = [{'source': 'Test', 'title': 'Oil prices rise on OPEC cut', 'desc': 'crude supply'}]
    prompt = ca.build_session_report_prompt(
        fake_articles, 'morning', '2026-06-11', 6,
        price_block=ca.format_price_for_prompt(prices, {}, cot),
        prices=prices,
    )
    assert 'TÍNH SẴN' in prompt and 'RSI' in prompt
    print(f'OK — prompt {len(prompt)} chars (~{len(prompt)//4} tokens)')

    print('=== 8. Chon loc bai theo diem ===')
    arts = [
        {'title': 'Gold and oil surge as OPEC cuts crude supply', 'desc': 'commodity rally', 'collected_at': '2026-06-11 07:00'},
        {'title': 'Celebrity news today', 'desc': 'entertainment', 'collected_at': '2026-06-11 08:00'},
        {'title': 'Wheat harvest drought', 'desc': 'corn soybean', 'collected_at': '2026-06-11 06:00'},
    ]
    top = ca.select_top_articles(arts, limit=2)
    assert top[0]['title'].startswith('Gold'), 'bai diem cao nhat phai dung dau'
    assert all('Celebrity' not in a['title'] for a in top), 'bai khong lien quan phai bi loai'
    print(f'OK — top: {[a["title"][:30] for a in top]}')

    print('\n=== TAT CA PASS ===')


if __name__ == '__main__':
    main()
