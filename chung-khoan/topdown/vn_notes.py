# -*- coding: utf-8 -*-
"""
ĐỌC THUYẾT MINH BCTC — lớp SÂU NHẤT, nơi câu trả lời thật ẩn náu.

Bảng số (VCI) KHÔNG có: giao dịch & số dư BÊN LIÊN QUAN, tuổi nợ/quá hạn phải thu, tập trung
khách hàng, lịch đáo hạn trái phiếu, đóng góp từng mảng. Những thứ này nằm trong THUYẾT MINH
báo cáo tài chính (PDF kiểm toán). Module này:
  1. Tải PDF Báo cáo thường niên (kèm BCTC + thuyết minh) từ CDN Vietstock — KEYLESS, theo mã.
  2. Trích TEXT (pdfplumber/fitz) — kiểm PDF có phải bản text (không scan).
  3. Định vị + bóc các mục thuyết minh GIÁ TRỊ CAO:
     - GIAO DỊCH & SỐ DƯ BÊN LIÊN QUAN: mạng lưới bên liên quan + số dư (neo theo tên → verify được).
     - Dò sự hiện diện: tuổi nợ/quá hạn phải thu, tập trung khách hàng, trái phiếu, mảng/bộ phận.

GIỚI HẠN TRUNG THỰC (ghi rõ, không overclaim):
  - Nguồn = CDN Vietstock `static2.vietstock.vn/.../BCTN/...` — KHÔNG phủ 100% mã (một số 404,
    tên file lệch, hoặc chưa có năm đó). Trang IR công ty thường CHẶN bot (Cloudflare 403).
  - BCTN đôi khi chỉ TÓM TẮT BCTC, không đủ toàn bộ thuyết minh như bản BCTC kiểm toán riêng.
  - Mỗi DN trình bày MỘT KIỂU → parser bóc SỐ chỉ cho phần chuẩn (bên liên quan neo-tên);
    phần khác trả về TRÍCH ĐOẠN + số trang để người đọc tự soi (kèm nhãn "cần đối chiếu PDF").

Chạy:  python vn_notes.py LCG --year 2024
       python vn_notes.py LCG --pdf duong_dan_co_san.pdf   # dùng PDF đã tải
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "bctn_cache")
VS_CDN = "https://static2.vietstock.vn/data/{ex}/{yr}/BCTN/VN/{sym}_Baocaothuongnien_{yr}.pdf"
_EXCHANGES = ("HOSE", "HNX", "UPCOM")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.vietstock.vn/"}


def ensure_utf8_stdout() -> None:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except Exception:
            pass


# ---- số tiền định dạng VN: "79.642.152.583" -> 79642152583 ----
_NUM = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")
_ENTITY = re.compile(r"^(Công ty|Tổng Công ty|Tổng công ty|CTCP|CTy|Ngân hàng|Quỹ|Ông |Bà )",
                     re.IGNORECASE)


_GENERIC = {"công ty", "công ty con", "công ty con trực tiếp", "công ty liên kết",
            "công ty mẹ", "tổng công ty", "công ty liên kết gián tiếp", "các công ty con"}


def _is_entity_name(ln: str) -> bool:
    """Lọc nhiễu: tên bên liên quan thật, không phải cả câu/mô tả (layout mỗi DN mỗi kiểu)."""
    s = ln.strip().rstrip("(*) ").strip()
    if len(s) > 55 or len(s.split()) > 9:
        return False
    if s.lower() in _GENERIC:
        return False
    # câu văn: có động từ/liên từ đặc trưng của mô tả nghiệp vụ
    if re.search(r"\b(và|cung cấp|mua hàng|trên cơ sở|điều kiện|thực hiện|bao gồm)\b", s.lower()):
        return False
    return True


def _parse_num(s: str) -> Optional[int]:
    s = s.strip().replace(" ", "")
    if s in ("-", "", "‐"):
        return 0
    if _NUM.match(s):
        try:
            return int(s.replace(".", ""))
        except ValueError:
            return None
    return None


def _t(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:,.1f} tỷ"
    if a >= 1e6:
        return f"{v/1e6:,.1f} tr"
    return f"{v:,.0f}"


# ============================================================================
# Tải PDF Báo cáo thường niên từ CDN Vietstock
# ============================================================================
def fetch_bctn(symbol: str, year: int = 2024, exchange: Optional[str] = None,
               timeout: int = 90) -> Optional[str]:
    """Tải BCTN về cache; trả đường dẫn file, hoặc None nếu không tìm được (404 mọi sàn)."""
    symbol = symbol.upper().strip()
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_BCTN_{year}.pdf")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return path
    tries = [exchange.upper()] if exchange else []
    tries += [e for e in _EXCHANGES if e not in tries]
    for ex in tries:
        url = VS_CDN.format(ex=ex, yr=year, sym=symbol)
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout)
        except Exception:  # noqa: BLE001
            continue
        if r.status_code == 200 and "pdf" in r.headers.get("content-type", ""):
            with open(path, "wb") as f:
                f.write(r.content)
            return path
    return None


# ============================================================================
# Trích text + định vị mục thuyết minh
# ============================================================================
def _pages_text(pdf_path: str) -> List[str]:
    """Trả list text theo trang. Ưu tiên fitz (nhanh), fallback pdfplumber."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        return [doc[i].get_text() for i in range(doc.page_count)]
    except Exception:  # noqa: BLE001
        pass
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages]
    except Exception:  # noqa: BLE001
        return []


# từ khóa dò sự hiện diện của từng mục thuyết minh
_NOTE_KW = {
    "bên liên quan": ["bên liên quan"],
    "tuổi nợ / quá hạn phải thu": ["quá hạn", "tuổi nợ", "nợ xấu phải thu", "phân tích tuổi nợ"],
    "tập trung khách hàng": ["tập trung", "khách hàng lớn", "rủi ro tập trung"],
    "trái phiếu / lịch đáo hạn": ["trái phiếu", "kỳ hạn", "đáo hạn"],
    "báo cáo theo bộ phận / mảng": ["bộ phận", "theo mảng", "lĩnh vực kinh doanh"],
}


@dataclass
class RelatedParty:
    name: str
    category: str
    amount_end: Optional[int] = None
    note: str = ""


@dataclass
class Notes:
    symbol: str
    year: int
    pdf_path: str = ""
    n_pages: int = 0
    text_chars: int = 0
    is_text_pdf: bool = True
    related_parties: List[RelatedParty] = field(default_factory=list)
    rp_entities: List[str] = field(default_factory=list)
    rp_pages: List[int] = field(default_factory=list)
    rp_excerpt: str = ""
    present: Dict[str, List[int]] = field(default_factory=dict)
    error: str = ""


def _extract_related_parties(pages: List[str]) -> Tuple[List[RelatedParty], List[int], str]:
    """Bóc số dư bên liên quan theo mẫu 'neo tên': mỗi bản ghi = [số đầu, số cuối, nội dung, TÊN].

    Đọc ngược từ dòng TÊN công ty: 3 dòng trước là [số, số, nội dung] → (tên, số cuối, nội dung).
    Neo theo tên chắc hơn đọc xuôi (thứ tự text PDF có thể xê dịch). Category = tiêu đề gần nhất.
    """
    cat_hdr = re.compile(r"(Phải thu|Trả trước|Phải trả|Cho vay|Phải thu về cho vay|"
                         r"Phải thu ngắn hạn|Đầu tư|Doanh thu|Mua hàng|Cổ tức)", re.IGNORECASE)
    out: List[RelatedParty] = []
    pages_hit: List[int] = []
    excerpt = ""
    for pi, txt in enumerate(pages):
        if "bên liên quan" not in txt.lower():
            continue
        pages_hit.append(pi + 1)
        if not excerpt:
            k = txt.lower().find("bên liên quan")
            excerpt = re.sub(r"\n{2,}", "\n", txt[max(0, k - 80):k + 1400]).strip()
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        cur_cat = ""
        for i, ln in enumerate(lines):
            if cat_hdr.match(ln) and len(ln) < 60:
                cur_cat = ln
            if _ENTITY.match(ln) and i >= 3 and _is_entity_name(ln):
                a1 = _parse_num(lines[i - 3]); a2 = _parse_num(lines[i - 2])
                desc = lines[i - 1]
                if a1 is not None and a2 is not None and not _NUM.match(desc):
                    out.append(RelatedParty(name=ln, category=cur_cat or "bên liên quan",
                                            amount_end=a2, note=desc[:70]))
    # gộp trùng tên (giữ bản ghi số dư lớn nhất mỗi tên+category)
    seen = {}
    for rp in out:
        key = (rp.name, rp.category)
        if key not in seen or (rp.amount_end or 0) > (seen[key].amount_end or 0):
            seen[key] = rp
    dedup = list(seen.values())
    return dedup, pages_hit, excerpt


def extract_notes(symbol: str, year: int, pdf_path: str) -> Notes:
    nt = Notes(symbol=symbol.upper(), year=year, pdf_path=pdf_path)
    pages = _pages_text(pdf_path)
    nt.n_pages = len(pages)
    nt.text_chars = sum(len(p) for p in pages)
    if nt.n_pages == 0 or nt.text_chars < 500:
        nt.is_text_pdf = False
        nt.error = "PDF không trích được text (có thể là bản scan ảnh) → cần OCR, chưa hỗ trợ."
        return nt
    # dò sự hiện diện các mục
    low = [p.lower() for p in pages]
    for label, kws in _NOTE_KW.items():
        hits = [i + 1 for i, t in enumerate(low) if any(k in t for k in kws)]
        if hits:
            nt.present[label] = hits[:12]
    # bóc bên liên quan
    rps, pages_hit, excerpt = _extract_related_parties(pages)
    nt.related_parties = sorted(rps, key=lambda r: -(r.amount_end or 0))
    nt.rp_pages = pages_hit
    nt.rp_excerpt = excerpt
    # danh sách thực thể liên quan (distinct, bỏ header)
    ents = []
    for rp in rps:
        nm = re.sub(r"\s+", " ", rp.name).strip()
        if nm not in ents:
            ents.append(nm)
    nt.rp_entities = ents
    return nt


def analyze_notes(symbol: str, year: int = 2024, exchange: Optional[str] = None,
                  pdf_path: Optional[str] = None) -> Notes:
    symbol = symbol.upper().strip()
    if not pdf_path:
        pdf_path = fetch_bctn(symbol, year=year, exchange=exchange)
    if not pdf_path or not os.path.exists(pdf_path):
        nt = Notes(symbol=symbol, year=year)
        nt.error = (f"Không tải được BCTN {symbol} {year} từ CDN Vietstock (404 mọi sàn). "
                    "Tải tay PDF BCTC kiểm toán từ trang IR/HOSE rồi dùng --pdf.")
        return nt
    return extract_notes(symbol, year, pdf_path)


# ============================================================================
# In / render
# ============================================================================
def print_notes(nt: Notes) -> None:
    print(f"\n{'='*66}\nTHUYẾT MINH {nt.symbol} — BCTN {nt.year}\n{'='*66}")
    if nt.error:
        print("  ⚠️", nt.error)
        return
    print(f"  Nguồn: {os.path.basename(nt.pdf_path)} · {nt.n_pages} trang · "
          f"{nt.text_chars:,} ký tự text")
    print("\n  MỤC THUYẾT MINH DÒ ĐƯỢC (số trang):")
    for label in _NOTE_KW:
        pg = nt.present.get(label)
        print(f"    {'✅' if pg else '—'} {label}: {('trang ' + str(pg)) if pg else 'không thấy'}")
    if nt.related_parties:
        print(f"\n  🔗 MẠNG LƯỚI BÊN LIÊN QUAN ({len(nt.rp_entities)} đơn vị, trang {nt.rp_pages}):")
        for rp in nt.related_parties[:15]:
            print(f"    • {rp.name}  —  {rp.note} · số dư cuối năm {_t(rp.amount_end)} [{rp.category}]")
        print("    (số dư trích tự động — ĐỐI CHIẾU PDF trước khi dùng vào quyết định)")
    elif "bên liên quan" in nt.present:
        print(f"\n  🔗 Có mục bên liên quan (trang {nt.present['bên liên quan']}) nhưng chưa bóc được "
              "số theo mẫu — đọc trích đoạn:")
        print("   ", (nt.rp_excerpt[:600] or "").replace("\n", "\n    "))


def _md(nt: Notes) -> str:
    L = [f"# Thuyết minh {nt.symbol} — BCTN {nt.year}\n"]
    if nt.error:
        return L[0] + f"\n> ⚠️ {nt.error}\n"
    L.append(f"_Nguồn: {os.path.basename(nt.pdf_path)} · {nt.n_pages} trang._\n")
    L.append("## Mục thuyết minh dò được\n")
    for label in _NOTE_KW:
        pg = nt.present.get(label)
        L.append(f"- {'✅' if pg else '—'} **{label}**: {('trang ' + str(pg)) if pg else 'không thấy'}")
    if nt.related_parties:
        L.append(f"\n## 🔗 Giao dịch & số dư bên liên quan ({len(nt.rp_entities)} đơn vị)\n")
        L.append("| Bên liên quan | Nội dung | Số dư cuối năm | Khoản mục |")
        L.append("| --- | --- | --- | --- |")
        for rp in nt.related_parties[:25]:
            L.append(f"| {rp.name} | {rp.note} | {_t(rp.amount_end)} | {rp.category} |")
        L.append("\n_Số dư trích tự động từ thuyết minh — cần đối chiếu PDF gốc._")
    return "\n".join(L)


def main() -> None:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser(description="Đọc thuyết minh BCTC (bên liên quan + mục ẩn).")
    ap.add_argument("symbol")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--exchange", default=None, help="HOSE/HNX/UPCOM (mặc định: thử lần lượt)")
    ap.add_argument("--pdf", default=None, help="Dùng PDF đã tải sẵn thay vì tải từ CDN")
    ap.add_argument("--md-out", default=None, help="Xuất Markdown ra file")
    args = ap.parse_args()
    nt = analyze_notes(args.symbol, year=args.year, exchange=args.exchange, pdf_path=args.pdf)
    print_notes(nt)
    if args.md_out:
        with open(args.md_out, "w", encoding="utf-8") as f:
            f.write(_md(nt))
        print(f"\n✅ Markdown: {args.md_out}")


if __name__ == "__main__":
    main()
