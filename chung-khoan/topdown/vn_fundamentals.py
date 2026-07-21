# -*- coding: utf-8 -*-
"""
Lớp dữ liệu CƠ BẢN (fundamentals) cho cổ phiếu Việt Nam — nguồn VCI (Vietcap).

Gọi thẳng REST API công khai `iq.vietcap.com.vn/api/iq-insight-service` (đúng nguồn
vnstock 4.x dùng), nên không phụ thuộc vnstock. Chỉ cần requests + pandas.

Ba khả năng chính:
  - get_ratios(symbol):   tỷ số định giá & chất lượng (PE, PB, PS, EV/EBITDA, ROE, ROA,
                          biên lợi nhuận, D/E, + CAMELS cho ngân hàng: NIM, NPL, CAR, CIR, LDR).
  - get_statement(symbol, section):  báo cáo tài chính (income/balance/cashflow),
                          cột đã đổi sang TÊN TIẾNG VIỆT nhờ bảng ánh xạ /metrics của VCI.
  - snapshot(symbol):     một dòng gọn: định giá + chất lượng kỳ gần nhất — dùng cho watchlist.

Đơn vị: số tiền trên báo cáo = ĐỒNG (VND). marketCap cũng ĐỒNG.

Endpoint đã kiểm chứng 17/07/2026 (FPT, VCB):
  GET /v1/company/{symbol}/statistics-financial                 -> ratios (tên trường rõ)
  GET /v1/company/{symbol}/financial-statement?section=SECTION  -> {years:[...], quarters:[...]} (mã trường)
  GET /v1/company/{symbol}/financial-statement/metrics          -> ánh xạ mã->tên (Việt/Anh)
SECTION ∈ {INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW}. Cần handshake GET /priceboard để nhận cookie.
"""
from __future__ import annotations

import sys
import time
import logging
from typing import Dict, List, Optional

import requests
import pandas as pd


def ensure_utf8_stdout() -> None:
    """Ép stdout/stderr về UTF-8 (in tiếng Việt không vỡ trên console Windows cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


logger = logging.getLogger(__name__)

IQ_BASE = "https://iq.vietcap.com.vn/api/iq-insight-service"
HANDSHAKE_URL = "https://trading.vietcap.com.vn/priceboard"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}

SECTIONS = ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")

# Các tỷ số cốt lõi cho snapshot watchlist (khớp CFA L2: m23 multiples, m24 P/B-ROE,
# m13 CAMELS bank, m14 chất lượng). Chỉ giữ field thực sự có trong nguồn.
_SNAPSHOT_FIELDS = [
    "yearReport", "quarter", "marketCap",
    # định giá (m23)
    "pe", "pb", "ps", "evToEbitda", "priceToCashFlow", "dividendYield",
    # sinh lời & chất lượng (m24, m14)
    "roe", "roa", "roic", "grossMargin", "ebitMargin",
    "preTaxProfitMargin", "afterTaxProfitMargin",
    # đòn bẩy & thanh khoản
    "debtToEquity", "financialLeverage", "currentRatio", "quickRatio", "cashRatio",
    # ngân hàng (m13 CAMELS) — chỉ có giá trị với mã bank
    "netInterestMargin", "npl", "car", "cir", "costToIncome", "ldrLoanDepositRatio",
    "casaRatio", "loansLossReserveToLoans",
]


class VCIFundamentals:
    def __init__(self, timeout: int = 30, max_retries: int = 3, pause: float = 0.4):
        self.timeout = timeout
        self.max_retries = max_retries
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._handshaken = False
        self._metrics_cache: Dict[str, Dict[str, str]] = {}

    # ---- hạ tầng ----
    def _handshake(self) -> None:
        if self._handshaken:
            return
        try:
            self.session.get(HANDSHAKE_URL, timeout=15)
        except Exception as e:  # noqa: BLE001
            logger.warning("Handshake /priceboard lỗi (bỏ qua): %s", e)
        self._handshaken = True

    def _get(self, path: str, params: Optional[dict] = None):
        self._handshake()
        url = f"{IQ_BASE}{path}"
        last = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                j = r.json()
                if isinstance(j, dict) and j.get("successful") is False:
                    raise RuntimeError(f"VCI trả lỗi: {j.get('msg')}")
                return j.get("data") if isinstance(j, dict) else j
            except Exception as e:  # noqa: BLE001
                last = e
                wait = self.pause * attempt
                logger.warning("GET %s thất bại (%d/%d): %s — chờ %.1fs",
                               url, attempt, self.max_retries, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"Không gọi được {url}: {last}")

    # ---- 1. Tỷ số định giá & chất lượng ----
    def get_ratios(self, symbol: str) -> pd.DataFrame:
        """DataFrame các tỷ số theo năm/quý (mỗi dòng = 1 kỳ). Field tên rõ (pe, pb, roe...)."""
        symbol = symbol.upper().strip()
        data = self._get(f"/v1/company/{symbol}/statistics-financial")
        if not isinstance(data, list) or not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        # sắp theo (năm, quý); quarter rỗng/0 = số liệu năm
        sort_cols = [c for c in ("yearReport", "quarter") if c in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols).reset_index(drop=True)
        return df

    # ---- 2. Báo cáo tài chính (đổi cột sang tiếng Việt) ----
    def _metrics_map(self, symbol: str, section: str) -> Dict[str, str]:
        """Ánh xạ mã trường -> tên tiếng Việt cho một section (cache theo section)."""
        if section in self._metrics_cache:
            return self._metrics_cache[section]
        data = self._get(f"/v1/company/{symbol}/financial-statement/metrics")
        out: Dict[str, str] = {}
        if isinstance(data, dict):
            for item in data.get(section, []) or []:
                field = item.get("field")
                name = item.get("titleVi") or item.get("titleEn") or field
                if field:
                    out[field] = name
        self._metrics_cache[section] = out
        return out

    def get_statement(self, symbol: str, section: str = "INCOME_STATEMENT",
                      period: str = "year", rename: bool = True) -> pd.DataFrame:
        """Báo cáo tài chính. section ∈ SECTIONS; period ∈ {'year','quarter'}.

        rename=True: đổi cột mã (isa1...) sang tên tiếng Việt. Giữ lại các cột meta
        (yearReport, quarter, lengthReport, publicDate) nếu có.
        """
        symbol = symbol.upper().strip()
        section = section.upper()
        if section not in SECTIONS:
            raise ValueError(f"section không hợp lệ: {section}. Hỗ trợ: {SECTIONS}")
        key = "quarters" if period.startswith("q") else "years"
        data = self._get(f"/v1/company/{symbol}/financial-statement",
                         {"section": section})
        rows = (data or {}).get(key, []) if isinstance(data, dict) else []
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if rename:
            cmap = self._metrics_map(symbol, section)
            # chỉ đổi các cột có trong ánh xạ; cột meta giữ nguyên
            df = df.rename(columns={c: cmap.get(c, c) for c in df.columns})
        return df

    # ---- 2b. Hồ sơ công ty (tên, ngành, mô tả bản chất kinh doanh) ----
    def company_info(self, symbol: str) -> Dict[str, object]:
        """Hồ sơ công ty từ /v1/company/{sym}: tên VN/EN, ngành, vốn hóa, rating, và
        `profile`/`enProfile` = mô tả BẢN CHẤT KINH DOANH (HTML). Rỗng nếu lỗi."""
        symbol = symbol.upper().strip()
        try:
            data = self._get(f"/v1/company/{symbol}")
        except Exception as e:  # noqa: BLE001
            logger.warning("company_info %s lỗi: %s", symbol, e)
            return {}
        return data if isinstance(data, dict) else {}

    # ---- 3. Snapshot gọn cho watchlist ----
    def snapshot(self, symbol: str, period: str = "year") -> Dict[str, object]:
        """Một dict gọn: các tỷ số định giá/chất lượng của KỲ GẦN NHẤT (mặc định: năm)."""
        df = self.get_ratios(symbol)
        if df.empty:
            return {"symbol": symbol.upper(), "error": "không có dữ liệu ratio"}
        # kỳ năm: quarter rỗng/0; nếu muốn quý thì lấy quarter>0
        if period.startswith("q") and "quarter" in df.columns:
            sub = df[df["quarter"].fillna(0) > 0]
        else:
            sub = df[df["quarter"].fillna(0) == 0] if "quarter" in df.columns else df
        if sub.empty:
            sub = df
        row = sub.iloc[-1]
        out: Dict[str, object] = {"symbol": symbol.upper()}
        for f in _SNAPSHOT_FIELDS:
            if f in row and pd.notna(row[f]):
                out[f] = row[f]
        return out


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    fx = VCIFundamentals()
    for sym in ("FPT", "VCB"):
        snap = fx.snapshot(sym)
        print(f"\n=== {sym} snapshot (kỳ năm gần nhất) ===")
        for k, v in snap.items():
            if isinstance(v, float):
                print(f"   {k:22} {v:,.4f}")
            else:
                print(f"   {k:22} {v}")
