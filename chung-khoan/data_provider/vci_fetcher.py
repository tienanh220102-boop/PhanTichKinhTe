# -*- coding: utf-8 -*-
"""
VCIFetcher — Vietnam market data source (HOSE / HNX / UPCoM).

Data source: VCI (Vietcap) public trading API (https://trading.vietcap.com.vn).
Same upstream used by the `vnstock` library, but called directly so this fetcher
does not depend on vnstock (which pins an old numpy and is Python-version picky).

Markets: Vietnam only ("vn"). Symbols are addressed with a ``.VN`` suffix
(e.g. ``FPT.VN``, ``ACV.VN``) so they never collide with 1-5 letter US tickers.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)

_BASE = "https://trading.vietcap.com.vn"
_SYMBOLS_URL = f"{_BASE}/api/price/symbols/getAll"
_OHLC_URL = f"{_BASE}/api/chart/OHLCChart/gap"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}

# VCI board label -> nhãn sàn quen thuộc ở VN.
_BOARD_MAP = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCoM"}

# Chỉ số các sàn trên VCI (ký hiệu phân biệt hoa/thường — đã kiểm chứng).
_VN_INDICES = [
    ("VNINDEX", "VN-Index"),
    ("VN30", "VN30"),
    ("HNXIndex", "HNX-Index"),
    ("HNX30", "HNX30"),
    ("HNXUpcomIndex", "UPCoM-Index"),
]

_SYMBOLS_CACHE_TTL = 3600.0  # giây


def is_vn_symbol(stock_code: Optional[str]) -> bool:
    """Mã VN được nhận diện bằng hậu tố ``.VN`` (không phân biệt hoa/thường)."""
    if not stock_code:
        return False
    return stock_code.strip().upper().endswith(".VN")


def strip_vn_suffix(stock_code: str) -> str:
    """Bỏ hậu tố .VN, trả mã gốc dùng cho API VCI (vd 'FPT.VN' -> 'FPT')."""
    code = (stock_code or "").strip().upper()
    return code[:-3] if code.endswith(".VN") else code


class VCIFetcher(BaseFetcher):
    name = "VCIFetcher"
    priority = 4  # chỉ phục vụ thị trường 'vn', được lọc riêng nên không tranh với fetcher A股

    def __init__(self, timeout: int = 30):
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._symbols_cache: Dict[str, Dict[str, str]] = {}
        self._symbols_cache_ts: float = 0.0

    # ---------- HTTP ----------
    def _post_ohlc(self, symbols: List[str], start_date: str, end_date: str) -> List[dict]:
        from_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        to_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86400
        payload = {"timeFrame": "ONE_DAY", "symbols": symbols, "from": from_ts, "to": to_ts}
        resp = self._session.post(_OHLC_URL, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    def _load_symbols(self) -> Dict[str, Dict[str, str]]:
        now = time.time()
        if self._symbols_cache and (now - self._symbols_cache_ts) < _SYMBOLS_CACHE_TTL:
            return self._symbols_cache
        try:
            resp = self._session.get(_SYMBOLS_URL, timeout=self._timeout)
            resp.raise_for_status()
            out: Dict[str, Dict[str, str]] = {}
            for it in resp.json():
                if it.get("type") != "STOCK":
                    continue
                board = _BOARD_MAP.get(str(it.get("board", "")).upper())
                if board is None:
                    continue
                sym = it.get("symbol")
                out[sym] = {
                    "board": board,
                    "name": it.get("organShortName") or it.get("organName")
                    or it.get("enOrganName") or sym,
                }
            if out:
                self._symbols_cache = out
                self._symbols_cache_ts = now
        except Exception as e:  # noqa: BLE001
            logger.warning("[VCI] Không tải được danh sách mã: %s", e)
        return self._symbols_cache

    # ---------- BaseFetcher contract ----------
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = strip_vn_suffix(stock_code)
        if not symbol:
            raise DataFetchError(f"[VCI] Mã không hợp lệ: {stock_code}")
        try:
            self.random_sleep(0.3, 0.9)
            data = self._post_ohlc([symbol], start_date, end_date)
        except Exception as e:  # noqa: BLE001
            raise DataFetchError(f"[VCI] Gọi API thất bại cho {symbol}: {e}") from e

        entry = next((e for e in data if e.get("symbol") == symbol), None)
        if entry is None or not entry.get("t"):
            raise DataFetchError(f"[VCI] Không có dữ liệu cho {symbol}")

        df = pd.DataFrame({
            "t": entry.get("t"),
            "open": entry.get("o"),
            "high": entry.get("h"),
            "low": entry.get("l"),
            "close": entry.get("c"),
            "volume": entry.get("v"),
        })
        if df.empty:
            raise DataFetchError(f"[VCI] Dữ liệu rỗng cho {symbol}")
        df.index = pd.to_datetime(pd.Series(df["t"], dtype="int64"), unit="s")
        df.index.name = None
        return df.drop(columns=["t"])

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df.empty:
            return df
        df = df.copy()
        df["date"] = pd.to_datetime(df.index).date
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["pct_chg"] = (df["close"].pct_change() * 100).fillna(0).round(2)
        df["amount"] = df["close"] * df["volume"]  # giá trị giao dịch (đồng)
        df["code"] = strip_vn_suffix(stock_code)
        keep = ["code"] + STANDARD_COLUMNS
        return df[[c for c in keep if c in df.columns]]

    # ---------- tiện ích thị trường (cho market-review) ----------
    def get_stock_name(self, stock_code: str) -> Optional[str]:
        info = self._load_symbols().get(strip_vn_suffix(stock_code))
        return info["name"] if info else None

    def get_board(self, stock_code: str) -> Optional[str]:
        info = self._load_symbols().get(strip_vn_suffix(stock_code))
        return info["board"] if info else None

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        # Chỉ phục vụ thị trường VN; các region khác trả None để không nhiễu luồng A股/US.
        if region != "vn":
            return None
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now().timestamp() - 15 * 86400)
        start = datetime.fromtimestamp(start).strftime("%Y-%m-%d")
        try:
            data = self._post_ohlc([sym for sym, _ in _VN_INDICES], start, end)
        except Exception as e:  # noqa: BLE001
            logger.warning("[VCI] Lấy chỉ số thất bại: %s", e)
            return None
        by_sym = {e.get("symbol"): e for e in data}
        out = []
        for sym, label in _VN_INDICES:
            e = by_sym.get(sym)
            closes = (e or {}).get("c") or []
            if len(closes) < 2:
                continue
            cur, prev = float(closes[-1]), float(closes[-2])
            out.append({
                "code": sym,
                "name": label,
                "current": round(cur, 2),
                "change": round(cur - prev, 2),
                "change_pct": round((cur / prev - 1) * 100, 2) if prev else None,
                "volume": None,
                "amount": None,
            })
        return out or None
