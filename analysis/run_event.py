# -*- coding: utf-8 -*-
"""
run_event — CLI event study tong quat, dung cho MOI loai su kien
(Fed/ECB, OPEC+, ton kho EIA, dia chinh tri...) va tu luu ket qua vao
outputs/analysis_<ten>_<ngay-chay>.txt de tich luy thanh thu vien event study.

Cach dung:
  # Su kien hang hoa: OPEC+ → dau WTI (kiem soat SPY + DXY)
  python analysis/run_event.py --name opec_cut --event 2026-06-01 \\
      --y CL=F --x SPY,DX-Y.NYB

  # Su kien ESG: FOMC → clean energy (kiem soat SPY + XLE)
  python analysis/run_event.py --name fomc_dissent --event 2026-04-29 \\
      --y ICLN --x SPY,XLE

  # Preset co san:
  python analysis/run_event.py --preset fomc_20260429

Goi y chon y/covariates theo loai su kien:
  OPEC+/nguon cung dau : y=CL=F (WTI)   x=SPY,DX-Y.NYB
  Fed/lai suat → vang  : y=GC=F         x=DX-Y.NYB,TLT
  Fed → ESG/xanh       : y=ICLN|ESGU    x=SPY,XLE
  Dia chinh tri → khi  : y=NG=F         x=SPY,CL=F
"""
import argparse
import sys, io
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

from data_pipeline import DataPipeline
from event_impact import EventImpact

_ROOT   = Path(__file__).parent.parent
OUT_DIR = _ROOT / 'outputs'

PRESETS = {
    'fomc_20260429': {
        'event': '2026-04-29', 'y': 'ICLN', 'x': 'SPY,XLE',
        'note':  'FOMC giu lai suat 8-4 dissent (lan dau 4 phieu chong tu 1992)',
    },
}


def run_and_save(name, event, y, x, pre_days=240, note=''):
    """Chay event study va luu ket qua. Tra ve (report_text, file_path)."""
    xs = [t.strip() for t in x.split(',') if t.strip()]
    pre_start = (datetime.strptime(event, '%Y-%m-%d')
                 - __import__('pandas').Timedelta(days=pre_days)).strftime('%Y-%m-%d')

    pipe = DataPipeline()
    tickers = {y: y}
    tickers.update({t: t for t in xs})
    df = pipe.fetch_market(tickers, start=pre_start)
    if df.empty or y not in df:
        raise SystemExit(f'Khong lay duoc du lieu cho {y}')

    ei = EventImpact(df[[y] + [t for t in xs if t in df]], event)
    report = ei.report(y)

    run_date = datetime.now().strftime('%Y-%m-%d')
    lines = [
        f'EVENT STUDY: {name}',
        f'Ngay chay: {run_date} | Su kien: {event} | y={y} | x={",".join(xs)}',
        *(['Ghi chu: ' + note] if note else []),
        '',
        report,
        '',
        f'(Model: statsmodels UnobservedComponents local-level + regression, '
        f'fit MLE tren pre-period — xem analysis/event_impact.py)',
    ]
    text = '\n'.join(lines)

    OUT_DIR.mkdir(exist_ok=True)
    fpath = OUT_DIR / f'analysis_{name}_{run_date}.txt'
    fpath.write_text(text, encoding='utf-8')
    print(text)
    print(f'\nDa luu → {fpath.relative_to(_ROOT)}')
    return text, fpath


def main():
    ap = argparse.ArgumentParser(description='Event study tong quat (CausalImpact-style)')
    ap.add_argument('--preset', choices=sorted(PRESETS), help='dung cau hinh co san')
    ap.add_argument('--name',  help='ten ngan cho file output (vd: opec_cut)')
    ap.add_argument('--event', help='ngay su kien YYYY-MM-DD (ngay nay thuoc post)')
    ap.add_argument('--y',     help='ticker chiu tac dong (yfinance)')
    ap.add_argument('--x',     default='SPY', help='covariates, phan cach bang phay')
    ap.add_argument('--pre-days', type=int, default=240, help='so ngay lich pre-period')
    args = ap.parse_args()

    if args.preset:
        p = PRESETS[args.preset]
        run_and_save(args.preset, p['event'], p['y'], p['x'], note=p.get('note', ''))
        return
    if not (args.name and args.event and args.y):
        ap.error('can --preset HOAC du bo --name --event --y')
    run_and_save(args.name, args.event, args.y, args.x, pre_days=args.pre_days)


if __name__ == '__main__':
    main()
