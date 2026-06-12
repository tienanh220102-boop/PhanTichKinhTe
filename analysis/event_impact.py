# -*- coding: utf-8 -*-
"""
EventImpact — phan tich can thiep kieu CausalImpact, chay tren statsmodels.

VI SAO KHONG DUNG tfcausalimpact:
  tfcausalimpact keo theo TensorFlow + TF-Probability (~600MB+) chi de fit
  mot Bayesian Structural Time Series. Cung mo hinh trang thai do
  (local level + hoi quy covariate) fit duoc bang
  statsmodels.UnobservedComponents (MLE) — nhe hon ~30 lan, ket qua
  counterfactual tuong duong cho muc dich event study. Neu sau nay can
  full Bayesian posterior, chi can thay ruot ham `fit()` — interface giu nguyen.

MO HINH:
  y_t = mu_t + beta·X_t + eps_t      (eps ~ N(0, sigma2_irregular))
  mu_t = mu_{t-1} + eta_t            (local level, eta ~ N(0, sigma2_level))

  - Fit tren PRE-PERIOD → du bao counterfactual cho POST-PERIOD (y neu
    khong co su kien) → effect = y_thuc − y_counterfactual.
  - "Prior" trong ban Bayesian goc ⇔ o day la phan phoi cua 2 phuong sai
    trang thai, uoc bang MLE tu pre-period (xem giai thich cuoi file).

GIA DINH BAT BUOC (in ra trong report):
  - Covariates KHONG bi su kien tac dong theo cach khac y (voi su kien
    vi mo chung, moi tai san deu bi tac dong → ket qua doc la "phan ung
    BAT THUONG cua y so voi cac factor", tuc relative event study).
  - Quan he y~X on dinh tu pre sang post.
"""
import numpy as np
import pandas as pd


class EventImpact:
    """
    data : DataFrame daily — cot dau la y, cac cot sau la covariates
    event_date : 'YYYY-MM-DD' — ngay su kien (ngay nay thuoc POST)
    pre_start  : ngay bat dau pre-period

    Dung log-price → effect doc duoc nhu % (xap xi log-return tich luy).
    """

    def __init__(self, data, event_date, pre_start=None, use_log=True):
        df = data.dropna().copy()
        if use_log:
            df = np.log(df)
        # Business-day freq + ffill: statsmodels can index co tan suat de
        # forecast dung; ngay nghi le lap bang gia phien truoc
        df = df.asfreq('B').ffill().dropna()
        self.use_log = use_log
        self.event_date = pd.Timestamp(event_date)
        if pre_start:
            df = df.loc[pd.Timestamp(pre_start):]
        self.pre  = df.loc[:self.event_date - pd.Timedelta(days=1)]
        self.post = df.loc[self.event_date:]
        self.ycol = df.columns[0]
        self.xcols = list(df.columns[1:])
        if len(self.pre) < 60:
            raise ValueError(f'Pre-period chi co {len(self.pre)} phien — can >=60')
        self.result = None

    def fit(self):
        """Local level + regression tren pre-period (MLE)."""
        from statsmodels.tsa.statespace.structural import UnobservedComponents
        self.model = UnobservedComponents(
            self.pre[self.ycol],
            level='llevel',
            exog=self.pre[self.xcols] if self.xcols else None,
        )
        self.fitted = self.model.fit(disp=False)
        # MLE khong hoi tu (hay gap voi chuoi volatile nhu clean energy):
        # thu lai bang Powell — cham hon nhung ben hon voi likelihood phang
        if not self.fitted.mle_retvals.get('converged', True):
            self.fitted = self.model.fit(method='powell', disp=False, maxiter=500)
        return self

    def run(self):
        """Counterfactual post-period + khoang tin cay 95%."""
        if not hasattr(self, 'fitted'):
            self.fit()
        fc = self.fitted.get_forecast(
            steps=len(self.post),
            exog=self.post[self.xcols] if self.xcols else None,
        )
        pred  = fc.predicted_mean
        ci    = fc.conf_int(alpha=0.05)
        ci.columns = ['lo', 'hi']
        actual = self.post[self.ycol]

        eff       = actual.values - pred.values             # point effect (log)
        cum_eff   = float(np.sum(eff))
        # CI cua cumulative effect: phuong sai cong don tu CI tung diem
        sd_t      = (ci['hi'].values - ci['lo'].values) / (2 * 1.96)
        cum_sd    = float(np.sqrt(np.sum(sd_t ** 2)))
        avg_eff   = cum_eff / len(eff)
        # Relative effect cuoi ky (log-diff ≈ %)
        rel_end   = float(actual.iloc[-1] - pred.iloc[-1])

        self.result = {
            'n_pre':         len(self.pre),
            'n_post':        len(self.post),
            'rel_effect_end':   rel_end,           # lech % tai ngay cuoi
            'rel_ci_lo':     float(actual.iloc[-1] - ci['hi'].iloc[-1]),
            'rel_ci_hi':     float(actual.iloc[-1] - ci['lo'].iloc[-1]),
            'avg_daily_eff': avg_eff,
            'cum_eff':       cum_eff,
            'cum_sd':        cum_sd,
            'significant':   abs(rel_end) > (ci['hi'].iloc[-1] - ci['lo'].iloc[-1]) / 2,
            'pred':          pred, 'ci': ci, 'actual': actual,
        }
        return self.result

    def report(self, y_name=None):
        if self.result is None:
            self.run()
        r = self.result
        y = y_name or self.ycol
        pct = lambda v: f'{v * 100:+.2f}%'
        sig = 'CO Y NGHIA (vuot CI 95%)' if r['significant'] else 'KHONG vuot CI 95% — co the la noise'
        return '\n'.join([
            f'=== Event Impact: {y} | su kien {self.event_date.date()} ===',
            f'Pre: {r["n_pre"]} phien | Post: {r["n_post"]} phien | covariates: {", ".join(self.xcols) or "(khong)"}',
            f'Lech thuc te vs counterfactual tai ngay cuoi: {pct(r["rel_effect_end"])}'
            f'  (CI95: {pct(r["rel_ci_lo"])} .. {pct(r["rel_ci_hi"])})',
            f'Ket luan thong ke: {sig}',
            'Luu y: day la phan ung BAT THUONG so voi covariates (relative event',
            'study) — khong tach duoc kenh tac dong neu su kien anh huong ca covariates.',
            'CI gia dinh Gaussian — daily returns co fat tails + volatility clustering',
            'nen CI THAT rong hon con so in ra; doc CI nay nhu CAN DUOI cua bat dinh.',
        ])
