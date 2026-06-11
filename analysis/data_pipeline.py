# -*- coding: utf-8 -*-
"""
DataPipeline — tang du lieu cho phan tich nhan qua (on-demand, KHONG chay trong cron).

Nguon:
  - World Bank REST (annual, keyless) — chi so vi mo cham: FDI, GDP, R&D, lai suat
  - yfinance (daily)                  — chuoi tan suat cao: ETF/index/commodity

Robustness:
  - align(): resample tat ca ve cung tan suat (M/Q) truoc khi ghep
  - impute(): ffill cho gia thi truong (gia tri cuoi van dung), interpolate
    tuyen tinh cho chi so vi mo (bien tron, doi annual→quarterly)
  - Moi buoc tra ve DataFrame moi — khong mutate input
"""
import requests
import pandas as pd

WB_API = 'https://api.worldbank.org/v2/country/{c}/indicator/{i}?source=2&format=json&mrv={n}&per_page=200'


class DataPipeline:
    """Gom fetch + align + impute. Moi method doc lap de thay ruot tung phan."""

    def __init__(self, timeout=30):
        self.timeout = timeout

    # ── Fetch ─────────────────────────────────────────────────
    def fetch_wb(self, indicators, country='VNM', years=30):
        """World Bank annual → DataFrame index=nam (datetime), cols=indicator code.

        indicators: dict {code: ten_cot}
        """
        codes = ';'.join(indicators)
        url = WB_API.format(c=country, i=codes, n=years)
        data = requests.get(url, timeout=self.timeout).json()
        if len(data) < 2 or not data[1]:
            return pd.DataFrame()
        rows = {}
        for r in data[1]:
            code = (r.get('indicator') or {}).get('id', '')
            if r.get('value') is None:
                continue
            rows.setdefault(code, {})[r['date']] = r['value']
        df = pd.DataFrame(rows).rename(columns=indicators)
        df.index = pd.to_datetime(df.index) + pd.offsets.YearEnd(0)
        return df.sort_index()

    def fetch_market(self, tickers, start, end=None, field='Close'):
        """yfinance daily → DataFrame index=ngay, cols=ticker."""
        import yfinance as yf
        out = {}
        for name, tk in tickers.items():
            try:
                s = yf.Ticker(tk).history(start=start, end=end)[field].dropna()
                if len(s):
                    s.index = s.index.tz_localize(None)
                    out[name] = s
            except Exception as e:
                print(f'  [pipeline] {tk} loi: {e}')
        return pd.DataFrame(out)

    # ── Align & Impute ────────────────────────────────────────
    def align(self, frames, freq='QE', how='last'):
        """Resample tung frame ve cung tan suat roi outer-join theo index.

        freq: 'ME' (thang) | 'QE' (quy). how: 'last' cho gia, 'mean' cho chi so.
        """
        resampled = []
        for df in frames:
            if df.empty:
                continue
            r = df.resample(freq).last() if how == 'last' else df.resample(freq).mean()
            resampled.append(r)
        if not resampled:
            return pd.DataFrame()
        out = resampled[0]
        for r in resampled[1:]:
            out = out.join(r, how='outer')
        return out

    def impute(self, df, market_cols=(), macro_cols=()):
        """Gia thi truong: ffill (gia cuoi con hieu luc). Vi mo: interpolate
        tuyen tinh (annual keo ve quarterly), gioi han trong khoang co data
        (khong extrapolate qua nam cuoi — tranh bia so lieu tuong lai)."""
        out = df.copy()
        for c in market_cols:
            if c in out:
                out[c] = out[c].ffill()
        for c in macro_cols:
            if c in out:
                out[c] = out[c].interpolate(method='linear', limit_area='inside')
        return out
