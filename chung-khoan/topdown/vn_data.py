# -*- coding: utf-8 -*-
"""
Lớp dữ liệu thị trường chứng khoán Việt Nam (HOSE / HNX / UPCoM).

Gọi thẳng API công khai của VCI (Vietcap) — đúng nguồn mà thư viện vnstock dùng —
nên không phụ thuộc vnstock (vốn pin numpy cũ, kén Python). Chỉ cần requests + pandas.

Ba khả năng chính:
  - get_universe(): toàn bộ mã đang giao dịch, kèm sàn (HOSE/HNX/UPCoM) và tên công ty.
  - get_ohlcv(): nến ngày (OHLCV) cho một danh sách mã.
  - get_indices(): nến ngày cho các chỉ số (VN-Index, VN30, HNX-Index, HNX30, UPCoM-Index).
"""

from __future__ import annotations

import sys
import time
import logging
from typing import Dict, List, Optional

import requests
import pandas as pd


def ensure_utf8_stdout() -> None:
    """Ép stdout/stderr về UTF-8 để in tiếng Việt không vỡ trên console Windows (cp1252).

    Gọi ở đầu mọi script chạy trực tiếp có in tiếng Việt — tự đủ, khỏi cần
    set PYTHONIOENCODING/PYTHONUTF8 mỗi lần chạy.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # Python 3.7+
        except Exception:
            pass


logger = logging.getLogger(__name__)

BASE = "https://trading.vietcap.com.vn"
SYMBOLS_URL = f"{BASE}/api/price/symbols/getAll"
OHLC_URL = f"{BASE}/api/chart/OHLCChart/gap"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}

# Chuẩn hóa tên sàn của VCI về nhãn quen thuộc ở VN.
_BOARD_MAP = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCoM"}
ACTIVE_BOARDS = ("HOSE", "HNX", "UPCoM")

# Ký hiệu chỉ số trên VCI (phân biệt hoa/thường — đã kiểm chứng).
INDEX_SYMBOLS = {
    "VN-Index": "VNINDEX",
    "VN30": "VN30",
    "HNX-Index": "HNXIndex",
    "HNX30": "HNX30",
    "UPCoM-Index": "HNXUpcomIndex",
}

STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


class VCIClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3, pause: float = 0.4):
        self.timeout = timeout
        self.max_retries = max_retries
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    # ---- hạ tầng gọi API có retry + backoff ----
    def _request(self, method: str, url: str, **kwargs):
        last = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.request(method, url, timeout=self.timeout, **kwargs)
                r.raise_for_status()
                return r.json()
            except Exception as e:  # noqa: BLE001
                last = e
                wait = self.pause * attempt
                logger.warning("Gọi %s thất bại (lần %d/%d): %s — chờ %.1fs",
                               url, attempt, self.max_retries, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"Không gọi được {url}: {last}")

    # ---- 1. Vũ trụ mã theo sàn ----
    def get_universe(self, boards: Optional[List[str]] = None) -> pd.DataFrame:
        """Trả DataFrame [symbol, board, name] cho các mã cổ phiếu đang giao dịch."""
        data = self._request("GET", SYMBOLS_URL)
        rows = []
        for it in data:
            if it.get("type") != "STOCK":
                continue
            board = _BOARD_MAP.get(str(it.get("board", "")).upper())
            if board is None:
                continue  # bỏ DELISTED, BOND...
            rows.append({
                "symbol": it.get("symbol"),
                "board": board,
                "name": it.get("organShortName") or it.get("organName")
                        or it.get("enOrganName") or it.get("symbol"),
            })
        df = pd.DataFrame(rows).dropna(subset=["symbol"]).drop_duplicates("symbol")
        if boards:
            want = {_BOARD_MAP.get(b.upper(), b) for b in boards}
            df = df[df["board"].isin(want)]
        return df.reset_index(drop=True)

    # ---- 2. OHLCV theo mã ----
    def get_ohlcv(self, symbols: List[str], days: int = 120,
                  batch_size: int = 60, strict: bool = False) -> Dict[str, pd.DataFrame]:
        """Nến ngày cho nhiều mã. Trả dict: symbol -> DataFrame(STANDARD_COLUMNS).

        CHỊU LỖI TỪNG BATCH (mặc định): nạp cả vũ trụ ~1500 mã là nhiều batch; một batch
        chập chờn mạng KHÔNG được phép giết cả pipeline. Batch fail hết retry → bỏ qua +
        cảnh báo (watchdog), chạy tiếp. `strict=True` để raise như cũ (khi cần fail-fast).
        """
        to_ts = int(time.time())
        from_ts = to_ts - days * 86400
        out: Dict[str, pd.DataFrame] = {}
        n_batch = (len(symbols) + batch_size - 1) // batch_size
        failed = 0
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            payload = {"timeFrame": "ONE_DAY", "symbols": batch,
                       "from": from_ts, "to": to_ts}
            try:
                data = self._request("POST", OHLC_URL, json=payload)
            except Exception as e:  # noqa: BLE001
                if strict:
                    raise
                failed += 1
                logger.warning("Bỏ qua batch %d/%d (%d mã) do lỗi: %s",
                               i // batch_size + 1, n_batch, len(batch), e)
                continue
            for e in data or []:
                df = self._to_frame(e)
                if df is not None and not df.empty:
                    out[e.get("symbol")] = df
            time.sleep(self.pause)
        if failed:
            logger.warning("OHLCV: %d/%d batch lỗi → thiếu tối đa %d mã (báo cáo vẫn chạy)",
                           failed, n_batch, failed * batch_size)
        return out

    def get_indices(self, days: int = 120) -> Dict[str, pd.DataFrame]:
        raw = self.get_ohlcv(list(INDEX_SYMBOLS.values()), days=days)
        # đổi khóa từ mã VCI sang tên hiển thị
        rename = {v: k for k, v in INDEX_SYMBOLS.items()}
        return {rename.get(k, k): v for k, v in raw.items()}

    @staticmethod
    def _to_frame(entry: dict) -> Optional[pd.DataFrame]:
        try:
            t = entry.get("t") or []
            if not t:
                return None
            df = pd.DataFrame({
                "date": pd.to_datetime(pd.Series(t, dtype="int64"), unit="s"),
                "open": entry.get("o"),
                "high": entry.get("h"),
                "low": entry.get("l"),
                "close": entry.get("c"),
                "volume": entry.get("v"),
            })
            df = df.astype({c: "float64" for c in ["open", "high", "low", "close", "volume"]})
            df["amount"] = df["close"] * df["volume"]  # giá trị giao dịch ~ (đơn vị nghìn đồng * cp)
            return df[STANDARD_COLUMNS].sort_values("date").reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("Lỗi parse %s: %s", entry.get("symbol"), e)
            return None


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.INFO)
    c = VCIClient()
    uni = c.get_universe()
    print("Tổng mã cổ phiếu:", len(uni))
    print(uni["board"].value_counts().to_dict())
    idx = c.get_indices(days=30)
    for name, df in idx.items():
        print(f"  {name:12} {len(df)} phiên, đóng cửa gần nhất = {df['close'].iloc[-1]:.2f}")
