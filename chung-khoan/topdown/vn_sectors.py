# -*- coding: utf-8 -*-
"""
Bản đồ NGÀNH (ICB 4 cấp) cho cổ phiếu Việt Nam — nguồn VCI (Vietcap).

Dùng để: (1) so sánh định giá theo PEER thật (m23 method-of-comparables), (2) nền cho
phân tích TOP-DOWN theo ngành. Phân loại ICB (Industry Classification Benchmark) 4 cấp
+ cờ isBank chính chủ từ VCI.

Endpoint đã kiểm chứng 17/07/2026:
  GET v2/company/search-bar?language=1  (1=vi, 2=en) — ~2089 công ty, mỗi mã có
      code, floor(sàn), isBank, icbLv1..icbLv4 {code,name,level}.
Cần handshake GET trading.vietcap.com.vn/priceboard.
"""
from __future__ import annotations

import sys
import time
import logging
from typing import Dict, List, Optional

import requests
import pandas as pd


def ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


logger = logging.getLogger(__name__)

SEARCHBAR_URL = "https://iq.vietcap.com.vn/api/iq-insight-service/v2/company/search-bar"
HANDSHAKE_URL = "https://trading.vietcap.com.vn/priceboard"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}
_BOARD_MAP = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCoM"}
ICB_LEVELS = ("icb_l1", "icb_l2", "icb_l3", "icb_l4")


class VCISectors:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._handshaken = False
        self._map: Optional[pd.DataFrame] = None

    def _handshake(self) -> None:
        if self._handshaken:
            return
        try:
            self.session.get(HANDSHAKE_URL, timeout=15)
        except Exception as e:  # noqa: BLE001
            logger.warning("Handshake lỗi (bỏ qua): %s", e)
        self._handshaken = True

    def get_industry_map(self, lang: str = "vi") -> pd.DataFrame:
        """DataFrame [symbol, name, exchange, is_bank, icb_l1..l4 (+ *_code)]. Cache trong phiên."""
        if self._map is not None:
            return self._map
        self._handshake()
        lang_code = "1" if lang == "vi" else "2"
        last = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(SEARCHBAR_URL, params={"language": lang_code},
                                     timeout=self.timeout)
                r.raise_for_status()
                data = r.json().get("data")
                if not data:
                    raise RuntimeError("search-bar trả rỗng")
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.4 * attempt)
        else:
            raise RuntimeError(f"Không lấy được bản đồ ngành: {last}")

        rows = []
        for c in data:
            def _icb(k):
                v = c.get(k) or {}
                return v.get("name"), v.get("code")
            l1n, l1c = _icb("icbLv1"); l2n, l2c = _icb("icbLv2")
            l3n, l3c = _icb("icbLv3"); l4n, l4c = _icb("icbLv4")
            rows.append({
                "symbol": c.get("code"),
                "name": c.get("shortName") or c.get("name"),
                "exchange": _BOARD_MAP.get(str(c.get("floor", "")).upper(), c.get("floor")),
                "is_bank": bool(c.get("isBank")),
                "icb_l1": l1n, "icb_l1_code": l1c,
                "icb_l2": l2n, "icb_l2_code": l2c,
                "icb_l3": l3n, "icb_l3_code": l3c,
                "icb_l4": l4n, "icb_l4_code": l4c,
            })
        df = pd.DataFrame(rows).dropna(subset=["symbol"]).drop_duplicates("symbol")
        self._map = df.reset_index(drop=True)
        return self._map

    def sector_of(self, symbol: str) -> Dict[str, object]:
        df = self.get_industry_map()
        row = df[df["symbol"] == symbol.upper().strip()]
        return row.iloc[0].to_dict() if not row.empty else {}

    def peers(self, symbol: str, level: str = "icb_l2",
              same_exchange: bool = False, exclude_self: bool = True) -> List[str]:
        """Danh sách mã cùng ngành (theo cấp ICB `level`). Mặc định cấp 2 (đủ rộng mà vẫn cùng nhóm)."""
        symbol = symbol.upper().strip()
        df = self.get_industry_map()
        me = df[df["symbol"] == symbol]
        if me.empty or level not in df.columns:
            return []
        me = me.iloc[0]
        sub = df[df[level] == me[level]]
        if same_exchange:
            sub = sub[sub["exchange"] == me["exchange"]]
        peers = sub["symbol"].tolist()
        if exclude_self and symbol in peers:
            peers.remove(symbol)
        return peers

    def sector_members(self, icb_name: str, level: str = "icb_l2") -> pd.DataFrame:
        df = self.get_industry_map()
        return df[df[level] == icb_name].reset_index(drop=True)


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    sx = VCISectors()
    m = sx.get_industry_map()
    print(f"Tổng công ty: {len(m)} | bank: {int(m['is_bank'].sum())}")
    print("\nSố mã theo ngành cấp 1 (ICB L1):")
    print(m["icb_l1"].value_counts().to_string())
    for sym in ("FPT", "VCB"):
        s = sx.sector_of(sym)
        pr = sx.peers(sym, level="icb_l2")
        print(f"\n{sym}: {s.get('icb_l1')} > {s.get('icb_l2')} > {s.get('icb_l3')} "
              f"(bank={s.get('is_bank')})")
        print(f"   {len(pr)} peer cùng ICB L2 '{s.get('icb_l2')}': {pr[:15]}{'...' if len(pr)>15 else ''}")
