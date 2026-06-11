# -*- coding: utf-8 -*-
"""
Event study: FOMC 29/04/2026 — giu lai suat voi 8-4 phieu chong
(lan dau 4 dissent tu 10/1992; boi canh gia nang luong tang vi Trung Dong).

Cau hoi: tai san xanh/ESG co phan ung BAT THUONG voi tin hieu hawkish-hold
nay khong, sau khi kiem soat thi truong chung (SPY) va nang luong (XLE)?

  y          : ICLN (iShares Global Clean Energy)  — proxy dau tu xanh
  kiem chung : ESGU (iShares MSCI USA ESG)         — ESG dien rong
  covariates : SPY, XLE

Chay: python analysis/run_fomc_20260429.py
"""
import sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

from data_pipeline import DataPipeline
from causal_dag import CausalDAG
from event_impact import EventImpact

EVENT     = '2026-04-29'
PRE_START = '2025-09-02'

pipe = DataPipeline()

print('=== 1. DAG — gia dinh nhan qua (tai lieu, khong phai uoc luong) ===')
dag = CausalDAG()
print(dag.assumptions_table())
print()
print(dag.backdoor_note('policy_rate', 'esg_inv'))
print()

print('=== 2. Smell test dau tuong quan tren du lieu WB annual (VN) ===')
wb = pipe.fetch_wb({
    'FR.INR.LEND':          'policy_rate',   # proxy: lai suat cho vay
    'BX.KLT.DINV.WD.GD.ZS': 'fdi',
    'NY.GDP.MKTP.KD.ZG':    'gdp',
}, country='VNM', years=30)
if not wb.empty:
    print(dag.sign_checks(wb).to_string(index=False))
print()

print('=== 3. Event Impact: FOMC 2026-04-29 ===')
for y_name, tk in [('ICLN (clean energy)', 'ICLN'), ('ESGU (MSCI USA ESG)', 'ESGU')]:
    df = pipe.fetch_market(
        {y_name.split()[0]: tk, 'SPY': 'SPY', 'XLE': 'XLE'},
        start=PRE_START,
    )
    try:
        ei = EventImpact(df, EVENT)
        print(ei.report(y_name))
    except Exception as e:
        print(f'{y_name}: loi — {e}')
    print()
