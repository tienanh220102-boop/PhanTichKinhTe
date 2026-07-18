# -*- coding: utf-8 -*-
"""
Lớp TIN BÁO CHÍ bên ngoài (Google News RSS, keyless) — bắt "phốt" doanh nghiệp.

VÌ SAO CẦN: nguồn VCI (vn_events / /v1/news) CHỈ là công bố CHÍNH THỨC của DN
(nghị quyết, KQKD, cổ tức) — KHÔNG bao giờ có tin bị khởi tố/bắt/điều tra/thao túng/
xử phạt. Những "phốt" đó là tin BÁO CHÍ bên ngoài, ảnh hưởng nặng tới tài chính DN,
phải lấy từ báo chí. Google News RSS tiếng Việt (hl=vi) không cần key.

TRIẾT LÝ (khớp yêu cầu user + memory):
  1. THỜI GIAN: luôn sắp theo ngày (mới → cũ), không đảo tin trước ra sau.
  2. SO SÁNH CHÉO: gom tin trùng (một sự kiện nhiều báo đăng) thành 1 đại diện, đếm số nguồn.
  3. TÁC ĐỘNG: chấm điểm — tin pháp lý/tiêu cực (khởi tố, bắt, điều tra, thao túng, phạt,
     hủy niêm yết...) > sự kiện trọng yếu (KQKD, M&A, cổ tức) > tin thường. Chỉ chọn tin
     đáng đọc nhất, không đổ hết.
  4. KHÔNG BỊA: chỉ hiện NGUYÊN VĂN tiêu đề + nguồn + ngày; cờ tiêu cực = do TỪ KHÓA khớp,
     là tin CẦN KIỂM CHỨNG, không phải kết luận. Lọc liên quan để bớt nhiễu (vd 'bắt đáy').
"""
from __future__ import annotations

import re
import sys
import time
import logging
import urllib.parse
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# --- Từ khóa TÁC ĐỘNG (đặt cụm rõ nghĩa, tránh từ đơn dễ nhầm như 'bắt' ↔ 'bắt đáy') ---
# Mức 3 = TIÊU CỰC/pháp lý nặng (phốt) — ưu tiên cảnh báo cao nhất.
# CHỈ giữ cụm rõ nghĩa tiêu cực; ĐÃ BỎ từ mơ hồ ('nợ xấu', 'thanh tra', 'bán tháo', 'sai lệch')
# vì hay dính tin trung tính/tốt (vd 'HOÀN NHẬP nợ xấu' = lãi).
_NEG_KEYWORDS = [
    "khởi tố", "bị bắt", "bắt giữ", "bắt tạm giam", "tạm giam", "truy tố", "truy nã",
    "điều tra", "thao túng", "gian lận", "lừa đảo", "chiếm đoạt", "sai phạm", "vi phạm",
    "xử phạt", "bị phạt", "phạt tiền", "truy thu thuế", "cưỡng chế thuế", "cưỡng chế",
    "phong tỏa", "kê biên", "đình chỉ giao dịch", "hủy niêm yết", "hạn chế giao dịch",
    "kiểm soát đặc biệt", "diện cảnh báo", "vỡ nợ", "phá sản", "mất khả năng thanh toán",
    "thua lỗ", "lỗ nặng", "lỗ lũy kế", "bê bối", "bết bát", "chậm trả gốc", "chậm trả lãi",
    "vỡ nợ trái phiếu", "khắc phục hậu quả",
]
# Cụm ĐẢO CHIỀU TÍCH CỰC — nếu có thì KHÔNG tính là phốt (vd 'hoàn nhập nợ xấu' = tốt).
_POS_REVERSAL = [
    "hoàn nhập", "thu hồi nợ", "xử lý nợ", "xử lý xong", "tất toán", "trả hết nợ",
    "sạch nợ", "giảm mạnh nợ", "thoát diện", "ra khỏi diện", "khắc phục xong", "được xóa",
]
# Mức 2 = TRỌNG YẾU (không tiêu cực nhưng đáng chú ý).
_MATERIAL_KEYWORDS = [
    "kết quả kinh doanh", "lợi nhuận", "doanh thu", "kqkd", "cổ tức", "chia cổ tức",
    "phát hành", "trúng thầu", "trúng gói", "ký hợp đồng", "hợp đồng", "m&a", "sáp nhập",
    "mua lại", "thoái vốn", "chào bán", "niêm yết", "dự án", "đầu tư", "mở rộng",
    "kế hoạch", "đại hội cổ đông", "esop", "hoàn nhập", "nợ xấu",
]

_STOP = set("và của các cho với về trong ngày năm được đã sẽ khi từ đến một những này đó "
            "cổ phiếu công ty tập đoàn ctcp cp tin tức mới nhất hôm nay báo".split())


def _impact(title: str) -> tuple:
    """(level, nhãn): 3=tiêu cực/pháp lý, 2=trọng yếu, 1=thường. Khớp theo cụm từ khóa.

    Có chốt ĐẢO CHIỀU: tiêu đề mang cụm tích cực ('hoàn nhập nợ xấu', 'thoát diện...')
    thì KHÔNG gắn tiêu cực dù có chữ nhạy — tránh false positive.
    """
    low = title.lower()
    reversed_pos = any(p in low for p in _POS_REVERSAL)
    if not reversed_pos:
        for kw in _NEG_KEYWORDS:
            if kw in low:
                return 3, "tiêu cực"
    for kw in _MATERIAL_KEYWORDS:
        if kw in low:
            return 2, "trọng yếu"
    return 1, "thường"


def _tokens(title: str) -> set:
    """Token có nghĩa để so trùng chéo (bỏ dấu câu, stopword, từ ngắn)."""
    words = re.findall(r"[0-9A-Za-zÀ-ỹ]+", title.lower())
    return {w for w in words if len(w) >= 4 and w not in _STOP}


def _similar(a: set, b: set, thr: float = 0.6) -> bool:
    """Jaccard token — cùng một sự kiện nếu trùng cao (nhiều báo đăng lại)."""
    if not a or not b:
        return False
    inter = len(a & b)
    return inter / len(a | b) >= thr


class VNNews:
    def __init__(self, timeout: int = 15, pause: float = 0.15):
        self.timeout = timeout
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def _rss(self, query: str, n: int = 30) -> List[Dict[str, object]]:
        """Tiêu đề tin tiếng Việt qua Google News RSS. Trả [{tiêu_đề, ngày, nguồn, link}]."""
        try:
            u = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
            r = self.session.get(u, timeout=self.timeout)
            root = ET.fromstring(r.content)
        except Exception as e:  # noqa: BLE001
            logger.warning("Google News lỗi '%s': %s", query, e)
            return []
        out = []
        for it in root.findall(".//item")[:n]:
            title = (it.findtext("title") or "").strip()
            if not title:
                continue
            # Google News: "Tiêu đề - Nguồn"
            src = ""
            m = re.search(r"\s-\s([^-]+)$", title)
            if m:
                src = m.group(1).strip()
                title = title[:m.start()].strip()
            d = None
            pub = it.findtext("pubDate")
            if pub:
                try:
                    d = parsedate_to_datetime(pub).date()
                except Exception:  # noqa: BLE001
                    d = None
            out.append({"tiêu_đề": title, "ngày": d, "nguồn": src,
                        "link": it.findtext("link")})
        return out

    @staticmethod
    def _relevant(title: str, symbol: str, name: Optional[str]) -> bool:
        """Giữ tin có nhắc mã hoặc tên (bớt nhiễu tin không liên quan)."""
        low = title.lower()
        if re.search(rf"\b{re.escape(symbol.lower())}\b", low):
            return True
        if name:
            # khớp ≥1 từ đặc trưng của tên (bỏ từ chung)
            nm = [w for w in _tokens(name) if w not in _STOP]
            return any(w in low for w in nm)
        return False

    def curate(self, symbol: str, name: Optional[str] = None, days: int = 30,
               pool: int = 30, max_items: int = 4) -> List[Dict[str, object]]:
        """Danh sách tin ĐÃ CHỌN LỌC cho một mã:
          - lọc liên quan + trong `days` ngày,
          - SO SÁNH CHÉO gom tin trùng (1 sự kiện = 1 đại diện, đếm nguồn),
          - chấm TÁC ĐỘNG, chọn top `max_items` theo (tác động, mới nhất),
          - trả về SẮP THEO NGÀY mới→cũ (không đảo trước-sau).
        """
        symbol = symbol.upper().strip()
        q = f"{name} {symbol}" if name else f"{symbol} cổ phiếu"
        raw = self._rss(q, n=pool)
        time.sleep(self.pause)
        today = dt.date.today()
        cutoff = today - dt.timedelta(days=days)

        # lọc liên quan + trong hạn
        items = []
        for it in raw:
            if it["ngày"] is None or it["ngày"] < cutoff or it["ngày"] > today:
                continue
            if not self._relevant(it["tiêu_đề"], symbol, name):
                continue
            lvl, lab = _impact(it["tiêu_đề"])
            items.append({**it, "tok": _tokens(it["tiêu_đề"]),
                          "tác_động": lvl, "nhãn": lab, "số_nguồn": 1})

        # so sánh chéo: gom tin trùng (cùng sự kiện) → giữ đại diện đủ thông tin nhất
        groups: List[Dict[str, object]] = []
        for it in sorted(items, key=lambda x: x["ngày"]):  # cũ→mới để lấy ngày "vỡ" sự kiện
            hit = None
            for g in groups:
                if _similar(it["tok"], g["tok"]):
                    hit = g
                    break
            if hit is None:
                groups.append(it)
            else:
                hit["số_nguồn"] += 1
                # giữ tiêu đề dài hơn (đủ ý hơn); giữ ngày SỚM nhất (khi sự kiện vỡ)
                if len(it["tiêu_đề"]) > len(hit["tiêu_đề"]):
                    hit["tiêu_đề"], hit["link"], hit["nguồn"] = it["tiêu_đề"], it["link"], it["nguồn"]
                    hit["tác_động"], hit["nhãn"] = it["tác_động"], it["nhãn"]

        # chọn theo (tác động cao, mới nhất), rồi HIỂN THỊ sắp theo ngày mới→cũ
        chosen = sorted(groups, key=lambda x: (x["tác_động"], x["ngày"]), reverse=True)[:max_items]
        chosen.sort(key=lambda x: x["ngày"], reverse=True)
        for c in chosen:
            c.pop("tok", None)
        return chosen


def fmt_news(n: Dict[str, object]) -> str:
    """Một dòng tin: [ngày] m/mark tiêu đề (nguồn ×số_nguồn)."""
    d = n["ngày"].strftime("%d/%m") if n.get("ngày") else "?"
    mark = "🚨" if n["tác_động"] == 3 else ("📰" if n["tác_động"] == 2 else "•")
    src = n.get("nguồn") or ""
    cnt = f"×{n['số_nguồn']}" if n.get("số_nguồn", 1) > 1 else ""
    tail = f" ({src}{cnt})" if src or cnt else ""
    return f"{mark} [{d}] {n['tiêu_đề']}{tail}"


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    nx = VNNews()
    # tên lấy tay để test; thực tế vn_report truyền tên từ bản đồ ngành
    for sym, name in [("PNJ", "Vàng bạc Phú Nhuận"), ("FPT", "FPT"),
                      ("VCB", "Vietcombank"), ("HPG", "Hòa Phát")]:
        print(f"\n=== {sym} ({name}) ===")
        for n in nx.curate(sym, name):
            print("  ", fmt_news(n))
