# -*- coding: utf-8 -*-
"""
Lớp SỰ KIỆN & TIN doanh nghiệp cho cổ phiếu Việt Nam — nguồn VCI (Vietcap), keyless.

Bổ sung mảng còn thiếu của hệ thống: phân tích không chỉ dựa số liệu tĩnh mà còn bắt
các sự kiện làm dịch chuyển giá — cổ tức, phát hành, ĐHCĐ, giao dịch nội bộ (structured),
và tin gốc (KQKD, trúng thầu, nghị quyết HĐQT...).

Gọi thẳng REST `iq.vietcap.com.vn/api/iq-insight-service` (cùng base vn_fundamentals):
  GET /v1/events?ticker=&fromDate=YYYYMMDD&toDate=&eventCode=&page=&size=
      -> data.content[]; field: eventCode, eventNameVi, eventTitleVi, publicDate,
         exrightDate (GDKHQ), recordDate (ĐKCC), payoutDate, valuePerShare, exerciseRatio.
  GET /v1/news?ticker=&fromDate=&toDate=&languageId=1&page=&size=
      -> data.content[]; field: newsTitle, publicDate, newsSource, newsSourceLink.
Cần handshake GET trading.vietcap.com.vn/priceboard để nhận cookie. Ngày trả dạng ISO.

Đơn vị: valuePerShare = ĐỒNG/cp. Triết lý (khớp memory): guardrail ngày/field, thiếu → bỏ
qua chứ không bịa; khử trùng lặp (VCI hay lặp cùng 1 sự kiện nhiều dòng).
"""
from __future__ import annotations

import sys
import time
import logging
import datetime as dt
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


IQ_BASE = "https://iq.vietcap.com.vn/api/iq-insight-service"
HANDSHAKE_URL = "https://trading.vietcap.com.vn/priceboard"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
}

# eventCode -> (nhãn tiếng Việt, độ ưu tiên hiển thị: nhỏ = quan trọng hơn)
_EVENT_MAP = {
    "DIV": ("Cổ tức", 0),
    "ISS": ("Phát hành thêm", 1),
    "AGME": ("ĐHCĐ thường niên", 1),
    "AGMR": ("ĐHCĐ (kết quả)", 1),
    "EGME": ("ĐHCĐ bất thường", 1),
    "DDIND": ("GD cổ đông nội bộ", 3),
    "DDINS": ("GD cổ đông nội bộ", 3),
    "DDRP": ("GD cổ đông lớn", 3),
    "MA": ("M&A", 2),
    "NLIS": ("Niêm yết mới", 2),
    "MOVE": ("Chuyển sàn", 2),
    "SUSP": ("Tạm ngừng GD", 2),
    "RETU": ("Trở lại GD", 2),
    "AIS": ("Thông tin khác", 4),
    "OTHE": ("Khác", 4),
}
# Nhóm sự kiện dùng cho phân tích (bỏ nhiễu giao dịch nội bộ khi cần bằng include_insider=False)
_CORE_CODES = "DIV,ISS,AGME,AGMR,EGME,MA,NLIS,MOVE,SUSP,RETU"
_ALL_CODES = _CORE_CODES + ",DDIND,DDINS,DDRP,AIS,OTHE"


# Vai trò lãnh đạo → hạng ưu tiên (nhỏ = quan trọng/tác động lớn hơn khi dính pháp lý).
# THỨ TỰ QUAN TRỌNG: đặt cụm 'phó ...' TRƯỚC để khớp đúng (không để 'phó chủ tịch' rơi vào
# 'chủ tịch'); Chủ tịch=0, TGĐ=1 để CEO không bị Phó Chủ tịch đẩy xuống.
_LEADER_ROLES = [
    ("phó chủ tịch", 2), ("chủ tịch", 0),
    ("phó tổng giám đốc", 3), ("phó tổng", 3), ("tổng giám đốc", 1),
    ("thành viên hội đồng", 4), ("giám đốc", 3),
    ("ban kiểm soát", 5), ("kế toán trưởng", 6),
]


def _role_rank(pos: str) -> int:
    low = (pos or "").lower()
    for kw, r in _LEADER_ROLES:
        if kw in low:
            return r
    return 9


def _parse_date(s: object) -> Optional[dt.date]:
    """ISO 'YYYY-MM-DDTHH:MM:SS' hoặc 'YYYY-MM-DD' -> date; None nếu hỏng."""
    if not s or not isinstance(s, str):
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "")).date()
    except (ValueError, TypeError):
        try:
            return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


class VCIEvents:
    def __init__(self, timeout: int = 25, max_retries: int = 3, pause: float = 0.4):
        self.timeout = timeout
        self.max_retries = max_retries
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._handshaken = False

    def _handshake(self) -> None:
        if self._handshaken:
            return
        try:
            self.session.get(HANDSHAKE_URL, timeout=15)
        except Exception as e:  # noqa: BLE001
            logger.warning("Handshake /priceboard lỗi (bỏ qua): %s", e)
        self._handshaken = True

    def _get(self, path: str, params: dict) -> List[dict]:
        self._handshake()
        url = f"{IQ_BASE}{path}"
        last = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                j = r.json()
                data = j.get("data") if isinstance(j, dict) else j
                if isinstance(data, dict):
                    return data.get("content", []) or []
                return data or []
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(self.pause * attempt)
        logger.warning("Không gọi được %s (%s): %s", url, params.get("ticker"), last)
        return []

    # ---- 1. Sự kiện structured (cổ tức/ĐHCĐ/phát hành/nội bộ) ----
    def get_events(self, symbol: str, days: int = 120, size: int = 40,
                   include_insider: bool = True) -> List[Dict[str, object]]:
        """Sự kiện trong `days` ngày gần nhất, đã chuẩn hóa + khử trùng lặp.

        Mỗi phần tử: {code, nhóm, tên, tiêu_đề, ngày_công_bố, GDKHQ, ĐKCC, chi_trả,
                      giá_trị_cp, tỷ_lệ}. Sắp theo ngày công bố giảm dần.
        """
        symbol = symbol.upper().strip()
        codes = _ALL_CODES if include_insider else _CORE_CODES
        to = dt.date.today()
        frm = to - dt.timedelta(days=days)
        raw = self._get("/v1/events", {
            "ticker": symbol, "fromDate": frm.strftime("%Y%m%d"),
            "toDate": to.strftime("%Y%m%d"), "eventCode": codes,
            "page": 0, "size": size,
        })
        out: List[Dict[str, object]] = []
        seen = set()
        for e in raw:
            code = e.get("eventCode")
            pub = _parse_date(e.get("publicDate"))
            if pub is None or pub < frm:
                continue
            label, _ = _EVENT_MAP.get(code, (code or "?", 5))
            title = e.get("eventTitleVi") or e.get("eventNameVi") or label
            key = (code, e.get("publicDate"), title)
            if key in seen:
                continue  # VCI hay lặp cùng sự kiện nhiều dòng
            seen.add(key)
            vps = e.get("valuePerShare")
            out.append({
                "code": code, "nhóm": label, "tên": e.get("eventNameVi"),
                "tiêu_đề": title,
                "ngày_công_bố": pub,
                "GDKHQ": _parse_date(e.get("exrightDate")),
                "ĐKCC": _parse_date(e.get("recordDate")),
                "chi_trả": _parse_date(e.get("payoutDate")),
                "giá_trị_cp": float(vps) if vps not in (None, "", 0) else None,
                "tỷ_lệ": e.get("exerciseRatio"),
            })
        out.sort(key=lambda x: x["ngày_công_bố"], reverse=True)
        return out

    # ---- 2. Tin gốc (KQKD, trúng thầu, nghị quyết HĐQT...) ----
    def get_news(self, symbol: str, days: int = 30, size: int = 30) -> List[Dict[str, object]]:
        """Tin trong `days` ngày gần nhất: {tiêu_đề, ngày, nguồn, link}. Mới → cũ."""
        symbol = symbol.upper().strip()
        to = dt.date.today()
        frm = to - dt.timedelta(days=days)
        raw = self._get("/v1/news", {
            "ticker": symbol, "fromDate": frm.strftime("%Y%m%d"),
            "toDate": to.strftime("%Y%m%d"), "languageId": 1,
            "page": 0, "size": size,
        })
        out: List[Dict[str, object]] = []
        seen = set()
        for n in raw:
            title = n.get("newsTitle") or n.get("friendlyTitle")
            if not title:
                continue
            d = _parse_date(n.get("publicDate"))
            if d is None or d < frm:
                continue
            if title in seen:
                continue
            seen.add(title)
            out.append({
                "tiêu_đề": title.strip(),
                "ngày": d,
                "nguồn": n.get("newsSource"),
                "link": n.get("newsSourceLink"),
            })
        out.sort(key=lambda x: x["ngày"], reverse=True)
        return out

    # ---- 3. Lãnh đạo ĐƯƠNG NHIỆM (để dò tin pháp lý theo tên người) ----
    def get_officers(self, symbol: str, max_n: int = 6) -> List[Dict[str, object]]:
        """Lãnh đạo ĐƯƠNG NHIỆM từ VCI /shareholder: [{tên, chức, rank}], ưu tiên vai trò cao.

        LƯU Ý: chỉ có người ĐƯƠNG NHIỆM — CỰU lãnh đạo (đã rời) KHÔNG xuất hiện ở nguồn này.
        """
        symbol = symbol.upper().strip()
        data = self._get(f"/v1/company/{symbol}/shareholder", {})
        out, seen = [], set()
        for it in data or []:
            if str(it.get("ownerType", "")).upper() != "INDIVIDUAL":
                continue
            nm = (it.get("ownerName") or "").strip()
            pos = (it.get("positionName") or "").strip()
            if not nm or not pos or nm in seen:
                continue
            rank = _role_rank(pos)
            if rank >= 9:  # không phải vai trò lãnh đạo rõ ràng → bỏ
                continue
            seen.add(nm)
            out.append({"tên": nm, "chức": pos, "rank": rank})
        out.sort(key=lambda x: x["rank"])
        return out[:max_n]

    # ---- 4. Tóm tắt gọn cho báo cáo ----
    def recent(self, symbol: str, days_events: int = 120, days_news: int = 30,
               max_events: int = 4, max_news: int = 4) -> Dict[str, object]:
        """Bản gọn dùng cho báo cáo: sự kiện quan trọng (bỏ nhiễu nội bộ) + tin mới nhất."""
        events = self.get_events(symbol, days=days_events, include_insider=False)
        news = self.get_news(symbol, days=days_news)
        return {
            "symbol": symbol.upper().strip(),
            "sự_kiện": events[:max_events],
            "tin": news[:max_news],
        }


def fmt_event(e: Dict[str, object]) -> str:
    """Một dòng gọn cho sự kiện."""
    parts = [f"{e['nhóm']}"]
    if e.get("code") == "DIV" and e.get("giá_trị_cp"):
        parts.append(f"{e['giá_trị_cp']:,.0f} đ/cp")
    if e.get("GDKHQ"):
        parts.append(f"GDKHQ {e['GDKHQ'].strftime('%d/%m')}")
    elif e.get("ĐKCC"):
        parts.append(f"ĐKCC {e['ĐKCC'].strftime('%d/%m')}")
    tt = e.get("tiêu_đề")
    head = " · ".join(parts)
    return f"{head} — {tt}" if tt and tt != e["nhóm"] else head


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    ev = VCIEvents()
    for sym in ("FPT", "VCB", "HPG"):
        r = ev.recent(sym)
        print(f"\n=== {sym} ===")
        print(" Sự kiện:")
        for e in r["sự_kiện"]:
            print("   •", fmt_event(e))
        print(" Tin gần đây:")
        for n in r["tin"]:
            print(f"   - [{n['ngày'].strftime('%d/%m')}] {n['tiêu_đề']}")
