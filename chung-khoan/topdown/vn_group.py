# -*- coding: utf-8 -*-
"""
CẤU TRÚC TẬP ĐOÀN — danh sách công ty con & công ty liên kết (tên + tỷ lệ sở hữu).

Nguồn: CafeF (keyless) — `GET cafef.vn/du-lieu/Ajax/PageNew/GetDataSubsidiaries.ashx?Symbol=`
Trả `Data.Subsidiaries` (công ty con, tập đoàn kiểm soát) + `Data.AssociatedCompanies`
(công ty liên kết, có ảnh hưởng nhưng không kiểm soát). Mỗi mục:
  CorpCode, Name, OwnershipRate (%), TotalCapital, SharedCapital, TradeCenter.

VCI KHÔNG có dữ liệu này (đã dò 12 endpoint, 404 hết) → phải lấy CafeF.

QUIRK dữ liệu đã verify (21/07/2026, FPT/VNM/HPG/VCB/HAG/PNJ):
  - OwnershipRate = SharedCapital / TotalCapital × 100 (verify: FOX 3372.9/7387.9=45.65%).
  - Đôi khi TotalCapital/SharedCapital bị HOÁN → OwnershipRate > 100% (vd FSOFT 530%, thực tế
    FPT sở hữu 100% FPT Software). Guardrail: >100.5% coi là LỖI NGUỒN → ownership=None + cờ.
  - Nhiều công ty con/liên kết tự NIÊM YẾT (FOX, FRT, FTS...) → CorpCode là mã sàn thật →
    có thể phân tích riêng bằng chính bộ deep-dive này. Con chưa niêm yết: CorpCode = "CORP_xx
    xxx" hoặc mã nội bộ (FSOFT/FPTEDU) → chỉ có tên + tỷ lệ.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set

import requests

logger = logging.getLogger(__name__)

_URL = "https://cafef.vn/du-lieu/Ajax/PageNew/GetDataSubsidiaries.ashx"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://s.cafef.vn/",
    "Accept": "application/json, text/plain, */*",
}
_OWN_MAX = 100.5   # tỷ lệ sở hữu tối đa hợp lệ (trên mức này = lỗi nguồn)


@dataclass
class Affiliate:
    code: str                       # CorpCode (mã sàn thật nếu niêm yết)
    name: str
    ownership: Optional[float]      # % sở hữu; None nếu nguồn lỗi
    ownership_bad: bool             # True nếu nguồn ghi tỷ lệ vô lý (>100%)
    capital: Optional[float]        # vốn điều lệ công ty con (tỷ đồng) = TotalCapital
    trade_center: str               # OTC / HOSE / HNX / UPCOM
    is_listed: bool                 # CorpCode là mã sàn có trong vũ trụ giao dịch


@dataclass
class GroupStructure:
    symbol: str
    subsidiaries: List[Affiliate] = field(default_factory=list)   # công ty con (kiểm soát)
    associates: List[Affiliate] = field(default_factory=list)     # công ty liên kết
    error: Optional[str] = None

    @property
    def n_listed_subs(self) -> int:
        return sum(1 for a in self.subsidiaries if a.is_listed)


class VNGroup:
    def __init__(self, timeout: int = 20, max_retries: int = 3, pause: float = 0.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def _parse(self, item: dict, listed: Set[str]) -> Affiliate:
        code = str(item.get("CorpCode") or "").strip()
        own = item.get("OwnershipRate")
        try:
            own = float(own)
        except (TypeError, ValueError):
            own = None
        bad = own is not None and own > _OWN_MAX
        if bad:
            own = None
        cap = item.get("TotalCapital")
        try:
            cap = float(cap)
        except (TypeError, ValueError):
            cap = None
        # niêm yết nếu CorpCode là mã sàn thật (3 ký tự chữ+số, có trong vũ trụ giao dịch)
        is_listed = bool(code) and code.upper() in listed
        return Affiliate(code=code, name=str(item.get("Name") or "").strip(),
                         ownership=own, ownership_bad=bad, capital=cap,
                         trade_center=str(item.get("TradeCenter") or "").strip(),
                         is_listed=is_listed)

    def get_structure(self, symbol: str, listed_symbols: Optional[Set[str]] = None) -> GroupStructure:
        """Danh sách công ty con + liên kết. `listed_symbols`: set mã sàn để đánh dấu con niêm yết."""
        symbol = symbol.upper().strip()
        listed = {s.upper() for s in (listed_symbols or set())}
        last = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(_URL, params={"Symbol": symbol}, timeout=self.timeout)
                r.raise_for_status()
                data = (r.json() or {}).get("Data") or {}
                gs = GroupStructure(symbol)
                for it in (data.get("Subsidiaries") or []):
                    gs.subsidiaries.append(self._parse(it, listed))
                for it in (data.get("AssociatedCompanies") or []):
                    gs.associates.append(self._parse(it, listed))
                # sắp theo vốn điều lệ giảm dần (công ty lớn trước), None xuống cuối
                for lst in (gs.subsidiaries, gs.associates):
                    lst.sort(key=lambda a: (a.capital is None, -(a.capital or 0)))
                return gs
            except Exception as e:  # noqa: BLE001
                last = e
                logger.warning("CafeF subsidiaries %s (%d/%d): %s", symbol, attempt,
                               self.max_retries, e)
                time.sleep(self.pause * attempt)
        return GroupStructure(symbol, error=str(last))


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.WARNING)
    g = VNGroup()
    for sym in ("FPT", "VNM", "HAG"):
        gs = g.get_structure(sym, listed_symbols={"FOX", "FRT", "FTS", "FOC"})
        print(f"\n=== {sym}: {len(gs.subsidiaries)} công ty con, {len(gs.associates)} liên kết "
              f"({gs.n_listed_subs} con niêm yết) ===")
        for a in gs.subsidiaries[:8]:
            own = f"{a.ownership:.1f}%" if a.ownership is not None else ("LỖI" if a.ownership_bad else "n/a")
            tag = f" [niêm yết {a.code}]" if a.is_listed else ""
            print(f"  con  {own:>6}  {a.name}{tag}")
        for a in gs.associates[:5]:
            own = f"{a.ownership:.1f}%" if a.ownership is not None else "n/a"
            print(f"  lk   {own:>6}  {a.name}")
