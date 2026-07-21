# -*- coding: utf-8 -*-
"""
Renderer + CLI cho BÁO CÁO FORENSIC MỘT MÃ (vn_deepdive.VNDeepDive).

Xuất:
  - Markdown dài theo form chuyên gia phân tích  → reports/<SYM>_deepdive.md
  - HTML tự chứa (theme-aware, biểu đồ SVG inline) → reports/<SYM>_deepdive.html

Chạy tay:
  python vn_deepdive_report.py FPT                # md + html, có định giá
  python vn_deepdive_report.py NVL --no-html
  python vn_deepdive_report.py VNM --telegram     # gửi kèm tóm tắt Telegram gọn

Wire đầy đủ fundamentals + sectors (tên/ngành/is_bank) + valuation (định giá). Keyless,
tất định, không LLM. Đơn vị số tiền = ĐỒNG.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import logging
import os
from typing import List, Optional

import numpy as np
import pandas as pd

from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout
from vn_deepdive import VNDeepDive, DeepDive, Section, _t

logger = logging.getLogger(__name__)

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


# ============================================================================
# Định dạng ô bảng
# ============================================================================
def _fmt_cell(col: str, v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if "Năm" in col:                                  # cột năm: luôn là số nguyên năm
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return str(v)
    if isinstance(v, float):
        if "Biên" in col or "/LN" in col:            # tỷ lệ
            return f"{v*100:.1f}%"
        if "ngày" in col:
            return f"{v:,.0f}"
        return _t(v)                                  # tiền → tỷ
    return str(v)


def _df_to_md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for _, row in df.iterrows():
        body.append("| " + " | ".join(_fmt_cell(c, row[c]) for c in cols) + " |")
    return "\n".join([head, sep] + body)


# ============================================================================
# Markdown
# ============================================================================
_SCOPE = [
    "**Báo cáo này làm gì:** đọc báo cáo tài chính nhiều năm đã công bố để soi chất lượng lợi "
    "nhuận, dòng tiền, cân đối kế toán, cấu trúc tập đoàn và định giá — phát hiện dấu hiệu 'làm "
    "đẹp sổ'.",
    "**Nguồn dữ liệu:** báo cáo tài chính & tỷ số từ VCI (Vietcap); danh sách công ty con từ CafeF.",
    "**Giả định định giá:** chi phí vốn chủ r≈13%, tăng trưởng dài hạn g≈5% (điều chỉnh được).",
    "**KHÔNG bao gồm:** nội dung thuyết minh (giao dịch bên liên quan, chi tiết khoản mục), đóng "
    "góp lợi nhuận của từng công ty con, lịch đáo hạn nợ, yếu tố vĩ mô/ngành, và dự phóng tương "
    "lai. Điểm số Beneish/Altman hiệu chỉnh cho thị trường Mỹ → chỉ là cờ tham khảo.",
]


_RATING_VI = {
    "BUY": "MUA", "SELL": "BÁN", "HOLD": "NẮM GIỮ", "M-PF": "TRUNG LẬP (Market Perform)",
    "O-PF": "KHẢ QUAN (Outperform)", "U-PF": "KÉM KHẢ QUAN (Underperform)",
    "MARKET PERFORM": "TRUNG LẬP", "OUTPERFORM": "KHẢ QUAN", "UNDERPERFORM": "KÉM KHẢ QUAN",
}


def _px(v) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.0f} đ"


def _header_stats_md(dd: DeepDive) -> str:
    i = dd.info or {}
    bits = []
    if i.get("price") is not None:
        bits.append(f"Giá {_px(i['price'])}")
    if i.get("marketcap") is not None:
        bits.append(f"vốn hóa {_t(i['marketcap'])}")
    rating = i.get("rating")
    if rating:
        r = _RATING_VI.get(str(rating).upper(), str(rating))
        up = i.get("upside")
        tgt = f", giá mục tiêu {_px(i.get('target'))}" if i.get("target") else ""
        upt = f" ({up*100:+.0f}%)" if isinstance(up, (int, float)) else ""
        bits.append(f"**Khuyến nghị Vietcap: {r}**{tgt}{upt}")
    return "> " + " · ".join(bits) if bits else ""


def _header_stats_html(dd: DeepDive) -> str:
    i = dd.info or {}
    if not i:
        return ""
    chips = []
    if i.get("price") is not None:
        chips.append(f"<span class='chip'>Giá {_px(i['price'])}</span>")
    if i.get("marketcap") is not None:
        chips.append(f"<span class='chip'>Vốn hóa {_t(i['marketcap'])}</span>")
    rating = i.get("rating")
    if rating:
        r = _RATING_VI.get(str(rating).upper(), str(rating))
        up = i.get("upside")
        cls = ("b-red" if str(rating).upper() in ("SELL", "U-PF", "UNDERPERFORM") else
               "b-green" if str(rating).upper() in ("BUY", "O-PF", "OUTPERFORM") else "b-amber")
        upt = f" {up*100:+.0f}%" if isinstance(up, (int, float)) else ""
        tgt = f" · MT {_px(i.get('target'))}" if i.get("target") else ""
        chips.append(f"<span class='chip badge {cls}'>Vietcap: {html.escape(r)}{tgt}{upt}</span>")
    return "<div class='stats'>" + "".join(chips) + "</div>" if chips else ""


def _vietcap_reco(dd: DeepDive) -> str:
    i = dd.info or {}
    rating = i.get("rating")
    if not rating:
        return ""
    r = _RATING_VI.get(str(rating).upper(), str(rating))
    up = i.get("upside")
    upt = f" — tiềm năng {up*100:+.0f}% so giá hiện tại {_px(i.get('price'))}" \
        if isinstance(up, (int, float)) else ""
    who = f" (chuyên viên {i['analyst']})" if i.get("analyst") else ""
    return (f"**Khuyến nghị giới phân tích (Vietcap):** {r}, giá mục tiêu "
            f"{_px(i.get('target'))}{upt}.{who} *Đây là quan điểm của Vietcap, tham khảo — độc "
            f"lập với phần forensic ở trên.*")


def render_markdown(dd: DeepDive) -> str:
    today = _dt.date.today().isoformat()
    out: List[str] = []
    title = f"{dd.symbol}" + (f" — {dd.name}" if dd.name and dd.name != dd.symbol else "")
    out.append(f"# Báo cáo phân tích đầu tư: {title}")
    out.append(f"> Ngành: {dd.sector or 'n/a'} · Lập ngày {today} · Nguồn: BCTC VCI (Vietcap)")
    out.append(_header_stats_md(dd))
    out.append("")
    if dd.error:
        out.append(f"**Lỗi tải dữ liệu:** {dd.error}")
        return "\n".join(out)

    # ---- MEMO ĐẦU TƯ (đọc phần này là nắm được câu chuyện) ----
    # 1. Luận điểm đầu tư — đoạn văn mạch lạc
    if dd.thesis:
        out.append("## Luận điểm đầu tư")
        out.append(dd.thesis)
        out.append("")
    # 2. Góc nhìn hai mặt
    out.append("## Góc nhìn đầu tư")
    out.append("**✅ Điểm hấp dẫn**")
    for b in (dd.bull or ["(chưa nổi bật)"]):
        out.append(f"- {b}")
    out.append("")
    out.append("**⚠️ Điều khiến e ngại**")
    for b in (dd.bear or ["Không phát hiện cờ đỏ forensic nào từ dữ liệu."]):
        out.append(f"- {b}")
    out.append("")
    # 3. Điều rút ra cho doanh nghiệp (hàm ý)
    if dd.takeaways:
        out.append("## Điều rút ra cho doanh nghiệp")
        for tk in dd.takeaways:
            out.append(f"- {tk}")
        out.append("")
    # 4. Góc nhìn nhà đầu tư: khuyến nghị Vietcap + loại NĐT + kịch bản
    out.append("## Góc nhìn nhà đầu tư")
    reco = _vietcap_reco(dd)
    if reco:
        out.append(reco)
        out.append("")
    if dd.lenses:
        out.append("**Theo khẩu vị nhà đầu tư:**")
        for ln in dd.lenses:
            out.append(f"- {ln}")
        out.append("")
    if dd.scenarios:
        out.append("**Ba kịch bản (điều kiện, không phải dự phóng):**")
        for sc in dd.scenarios:
            out.append(f"- {sc}")
        out.append("")
    # 5. Mấu chốt cần theo dõi (thay cho 'định hướng tương lai' — không suy đoán)
    if dd.watch_items:
        out.append("## Mấu chốt cần theo dõi")
        for w in dd.watch_items[:3]:
            out.append(f"- {w}")
        out.append("")

    # 6. Phạm vi & giả định (đọc để hiểu báo cáo dựa trên gì)
    out.append("## Phạm vi & giả định")
    for s in _SCOPE:
        out.append(f"- {s}")
    out.append("")
    out.append("---")
    out.append("## Phân tích chi tiết (bằng chứng cho luận điểm trên)")
    out.append("")

    # Các phần theo thứ tự
    order = ["group", "business", "quality", "cashflow", "balance", "distress", "valuation", "conclusion", "bank"]
    for key in order:
        sec = dd.sections.get(key)
        if not sec:
            continue
        out.append(f"## {sec.title}")
        for ln in sec.lines:
            out.append(ln + "  ")
        if sec.table is not None and not sec.table.empty:
            out.append("")
            out.append(_df_to_md(sec.table))
        # Beneish components (chỉ ở phần quality)
        if key == "quality" and getattr(dd, "_beneish_comps", None):
            out.append("")
            out.append("*Thành phần Beneish M-score (>1 với DSRI/SGI/... = hướng nghi ngờ):*  ")
            comp = dd._beneish_comps
            out.append("| " + " | ".join(comp.keys()) + " |")
            out.append("| " + " | ".join("---" for _ in comp) + " |")
            out.append("| " + " | ".join(f"{v:.2f}" if v is not None else "—"
                                          for v in comp.values()) + " |")
        if sec.explain:
            out.append("")
            for ex in sec.explain:
                out.append(f"> 💡 {ex}")
            out.append("")
        out.append("")

    out.append("---")
    out.append("*Báo cáo tất định, sinh tự động từ báo cáo tài chính công bố (VCI). Các điểm số "
               "Beneish/Altman hiệu chỉnh cho thị trường Mỹ — dùng làm cờ tham khảo, không phải "
               "khuyến nghị đầu tư. Cần đối chiếu thuyết minh BCTC và bản kiểm toán.*")
    return "\n".join(out)


# ============================================================================
# HTML tự chứa
# ============================================================================
_CSS = """
:root{color-scheme:light dark;
  --bg:#f7f8fa;--card:#fff;--fg:#1a1d23;--mut:#5b6472;--line:#e3e7ee;
  --red:#c0392b;--redbg:#fdecea;--green:#1e8e5a;--greenbg:#e9f7ef;
  --amber:#b7791f;--accent:#2563a8;--th:#eef1f6;}
@media (prefers-color-scheme:dark){:root{
  --bg:#14171c;--card:#1c2027;--fg:#e6e9ee;--mut:#9aa4b2;--line:#2a2f38;
  --red:#ff6b5e;--redbg:#3a1f1c;--green:#4ade80;--greenbg:#16281f;
  --amber:#e0b04a;--accent:#6ea8dc;--th:#232833;}}
:root[data-theme=dark]{
  --bg:#14171c;--card:#1c2027;--fg:#e6e9ee;--mut:#9aa4b2;--line:#2a2f38;
  --red:#ff6b5e;--redbg:#3a1f1c;--green:#4ade80;--greenbg:#16281f;
  --amber:#e0b04a;--accent:#6ea8dc;--th:#232833;}
:root[data-theme=light]{
  --bg:#f7f8fa;--card:#fff;--fg:#1a1d23;--mut:#5b6472;--line:#e3e7ee;
  --red:#c0392b;--redbg:#fdecea;--green:#1e8e5a;--greenbg:#e9f7ef;
  --amber:#b7791f;--accent:#2563a8;--th:#eef1f6;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.6;}
.wrap{max-width:900px;margin:0 auto;padding:32px 20px 80px;}
h1{font-size:1.9rem;margin:0 0 4px;}
.sub{color:var(--mut);font-size:.92rem;margin-bottom:24px;}
h2{font-size:1.25rem;margin:34px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line);}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin:16px 0;}
.verdict{font-size:1.05rem;font-weight:600;}
.flag{background:var(--redbg);border-left:4px solid var(--red);color:var(--fg);
  padding:9px 13px;border-radius:6px;margin:7px 0;font-size:.94rem;}
.pos{background:var(--greenbg);border-left:4px solid var(--green);
  padding:9px 13px;border-radius:6px;margin:7px 0;font-size:.94rem;}
.note{color:var(--mut);font-size:.86rem;}
p.line{margin:8px 0;}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:-8px 0 20px;}
.chip{display:inline-block;padding:4px 12px;border-radius:20px;background:var(--th);
  font-size:.85rem;font-weight:600;border:1px solid var(--line);}
.thesis{font-size:1.05rem;line-height:1.7;border-left:4px solid var(--accent);}
.bullbear{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0;}
.bb{flex:1;min-width:260px;border:1px solid var(--line);border-radius:12px;padding:14px 18px;}
.bb h4{margin:0 0 8px;font-size:1rem;}
.bb ul{margin:0;padding-left:20px;}
.bb li{margin:6px 0;font-size:.92rem;}
.bb-bull{background:var(--greenbg);}
.bb-bear{background:var(--redbg);}
.explain{background:var(--th);border-left:4px solid var(--accent);border-radius:6px;
  padding:11px 15px;margin:12px 0;font-size:.9rem;}
.explain .lbl{font-weight:700;color:var(--accent);}
.explain p{margin:6px 0;}
table{border-collapse:collapse;width:100%;font-size:.87rem;margin:12px 0;}
.tblwrap{overflow-x:auto;}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap;}
th{background:var(--th);font-weight:600;}
th:first-child,td:first-child{text-align:left;}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.8rem;font-weight:600;}
.b-red{background:var(--redbg);color:var(--red);}
.b-green{background:var(--greenbg);color:var(--green);}
.b-amber{background:#fff5e0;color:var(--amber);}
@media (prefers-color-scheme:dark){.b-amber{background:#332a15;}}
.charts{display:flex;flex-wrap:wrap;gap:18px;}
.chart{flex:1;min-width:240px;}
.chart h4{margin:0 0 6px;font-size:.9rem;color:var(--mut);font-weight:600;}
em{color:var(--mut);}
.foot{color:var(--mut);font-size:.8rem;margin-top:40px;border-top:1px solid var(--line);padding-top:14px;}
.toggle{position:fixed;top:14px;right:14px;background:var(--card);border:1px solid var(--line);
  color:var(--fg);border-radius:8px;padding:6px 12px;cursor:pointer;font-size:.85rem;}
"""

_TOGGLE_JS = """
(function(){var r=document.documentElement;var b=document.getElementById('tg');
function cur(){return r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');}
b.onclick=function(){var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);
b.textContent=n==='dark'?'☀️ Sáng':'🌙 Tối';};})();
"""


def _svg_bars(pairs, unit_div=1e9, color="var(--accent)", w=260, h=110):
    """Biểu đồ cột đơn giản từ [(label, value)]. value theo ĐỒNG, chia unit_div (tỷ)."""
    pairs = [(l, v) for l, v in pairs if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not pairs:
        return "<div class='note'>(thiếu dữ liệu)</div>"
    vals = [v / unit_div for _, v in pairs]
    vmax = max(vals + [0]); vmin = min(vals + [0])
    span = (vmax - vmin) or 1
    pad = 22; bw = (w - pad) / len(pairs) * 0.62; gap = (w - pad) / len(pairs)
    zero_y = h - pad - (0 - vmin) / span * (h - 2 * pad)
    bars = []
    for i, (lab, v) in enumerate(zip([p[0] for p in pairs], vals)):
        x = pad + i * gap + gap * 0.19
        y = h - pad - (v - vmin) / span * (h - 2 * pad)
        top = min(y, zero_y); ht = abs(y - zero_y)
        col = color if v >= 0 else "var(--red)"
        bars.append(f"<rect x='{x:.1f}' y='{top:.1f}' width='{bw:.1f}' height='{ht:.1f}' "
                    f"rx='2' fill='{col}'/>")
        bars.append(f"<text x='{x+bw/2:.1f}' y='{h-6:.1f}' font-size='9' fill='var(--mut)' "
                    f"text-anchor='middle'>{html.escape(str(lab))}</text>")
        bars.append(f"<text x='{x+bw/2:.1f}' y='{top-3:.1f}' font-size='8.5' fill='var(--fg)' "
                    f"text-anchor='middle'>{v:,.0f}</text>")
    bars.append(f"<line x1='{pad}' y1='{zero_y:.1f}' x2='{w}' y2='{zero_y:.1f}' "
                f"stroke='var(--line)'/>")
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' role='img'>{''.join(bars)}</svg>")


def _svg_grouped(labels, series, w=260, h=110):
    """2 chuỗi cạnh nhau (vd LN vs CFO). series=[('LN',color,vals),('CFO',color,vals)] tỷ."""
    labels = list(labels)
    if not labels:
        return "<div class='note'>(thiếu dữ liệu)</div>"
    allv = [v for _, _, vs in series for v in vs if v is not None]
    if not allv:
        return "<div class='note'>(thiếu dữ liệu)</div>"
    vmax = max(allv + [0]); vmin = min(allv + [0]); span = (vmax - vmin) or 1
    pad = 22; group = (w - pad) / len(labels); bw = group * 0.32
    zero_y = h - pad - (0 - vmin) / span * (h - 2 * pad)
    el = []
    for gi, lab in enumerate(labels):
        for si, (nm, col, vs) in enumerate(series):
            v = vs[gi] if gi < len(vs) else None
            if v is None:
                continue
            x = pad + gi * group + group * 0.14 + si * (bw + 2)
            y = h - pad - (v - vmin) / span * (h - 2 * pad)
            top = min(y, zero_y); ht = abs(y - zero_y)
            c = col if v >= 0 else "var(--red)"
            el.append(f"<rect x='{x:.1f}' y='{top:.1f}' width='{bw:.1f}' height='{ht:.1f}' "
                      f"rx='2' fill='{c}'/>")
        el.append(f"<text x='{pad+gi*group+group*0.4:.1f}' y='{h-6:.1f}' font-size='9' "
                  f"fill='var(--mut)' text-anchor='middle'>{html.escape(str(lab))}</text>")
    el.append(f"<line x1='{pad}' y1='{zero_y:.1f}' x2='{w}' y2='{zero_y:.1f}' stroke='var(--line)'/>")
    leg = "  ".join(f"<span style='color:{col}'>■</span> {html.escape(nm)}" for nm, col, _ in series)
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' role='img'>{''.join(el)}</svg>"
            f"<div class='note' style='text-align:center'>{leg}</div>")


def _df_to_html(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    cols = list(df.columns)
    th = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    rows = []
    for _, row in df.iterrows():
        tds = "".join(f"<td>{html.escape(_fmt_cell(c, row[c]))}</td>" for c in cols)
        rows.append(f"<tr>{tds}</tr>")
    return f"<div class='tblwrap'><table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _md_inline(ln: str) -> str:
    """Thoát HTML rồi khôi phục **đậm** → <strong>, *nghiêng* → <em> (không bọc <p>)."""
    import re as _re
    esc = html.escape(ln)
    esc = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
    esc = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc)
    return esc


def _line_html(ln: str) -> str:
    return f"<p class='line'>{_md_inline(ln)}</p>"


def render_html(dd: DeepDive) -> str:
    today = _dt.date.today().isoformat()
    title = f"{dd.symbol}" + (f" — {dd.name}" if dd.name and dd.name != dd.symbol else "")
    n = len(dd.red_flags)
    badge = ("<span class='badge b-green'>Không cờ đỏ</span>" if n == 0 else
             f"<span class='badge b-amber'>{n} lưu ý</span>" if n <= 2 else
             f"<span class='badge b-red'>{n} cờ đỏ</span>")
    P: List[str] = []
    P.append("<button class='toggle' id='tg'>🌙 Tối</button>")
    P.append("<div class='wrap'>")
    P.append(f"<h1>{html.escape(title)} {badge}</h1>")
    P.append(f"<div class='sub'>Ngành: {html.escape(dd.sector or 'n/a')} · Lập ngày {today} · "
             f"Nguồn: BCTC VCI (Vietcap)</div>")
    P.append(_header_stats_html(dd))
    if dd.error:
        P.append(f"<div class='flag'>Lỗi tải dữ liệu: {html.escape(dd.error)}</div></div>")
        return _html_shell(title, "".join(P))

    # ---- MEMO ĐẦU TƯ ----
    # 1. Luận điểm đầu tư (đoạn văn nổi bật)
    if dd.thesis:
        P.append("<h2>Luận điểm đầu tư</h2>")
        P.append(f"<div class='card thesis'>{html.escape(dd.thesis)}</div>")
    # 2. Góc nhìn hai mặt (bull / bear cạnh nhau)
    P.append("<h2>Góc nhìn đầu tư</h2>")
    P.append("<div class='bullbear'>")
    P.append("<div class='bb bb-bull'><h4>✅ Điểm hấp dẫn</h4>")
    if dd.bull:
        P.append("<ul>" + "".join(f"<li>{html.escape(b)}</li>" for b in dd.bull) + "</ul>")
    else:
        P.append("<p class='note'>(chưa nổi bật)</p>")
    P.append("</div>")
    P.append("<div class='bb bb-bear'><h4>⚠️ Điều khiến e ngại</h4>")
    if dd.bear:
        P.append("<ul>" + "".join(f"<li>{html.escape(b)}</li>" for b in dd.bear) + "</ul>")
    else:
        P.append("<p class='note'>Không phát hiện cờ đỏ forensic nào.</p>")
    P.append("</div></div>")
    # 3. Điều rút ra cho doanh nghiệp
    if dd.takeaways:
        P.append("<h2>Điều rút ra cho doanh nghiệp</h2>")
        P.append("<div class='card'><ul>" +
                 "".join(f"<li>{html.escape(t)}</li>" for t in dd.takeaways) + "</ul></div>")
    # 4. Góc nhìn nhà đầu tư
    P.append("<h2>Góc nhìn nhà đầu tư</h2>")
    reco = _vietcap_reco(dd)
    if reco:
        P.append("<div class='explain'>" + _line_html(reco) + "</div>")
    if dd.lenses:
        P.append("<div class='card'><strong>Theo khẩu vị nhà đầu tư</strong><ul>" +
                 "".join(f"<li>{_md_inline(ln)}</li>" for ln in dd.lenses) + "</ul></div>")
    if dd.scenarios:
        P.append("<div class='card'><strong>Ba kịch bản (điều kiện, không phải dự phóng)</strong>"
                 + "".join(_line_html(sc) for sc in dd.scenarios) + "</div>")
    # 5. Mấu chốt cần theo dõi
    if dd.watch_items:
        P.append("<h2>Mấu chốt cần theo dõi</h2>")
        P.append("<div class='card'><ul>" +
                 "".join(f"<li>{html.escape(w)}</li>" for w in dd.watch_items[:3]) + "</ul></div>")

    # 6. Phạm vi & giả định
    P.append("<div class='explain'><span class='lbl'>Phạm vi &amp; giả định</span>")
    for s in _SCOPE:
        P.append(_line_html(s))
    P.append("</div>")

    # Biểu đồ tổng quan
    charts = _overview_charts(dd)
    if charts:
        P.append("<div class='card charts'>" + charts + "</div>")

    P.append("<h2 style='border-top:3px solid var(--accent);padding-top:16px;margin-top:38px'>"
             "Phân tích chi tiết <span class='note'>(bằng chứng cho luận điểm trên)</span></h2>")

    order = ["group", "business", "quality", "cashflow", "balance", "distress", "valuation", "conclusion", "bank"]
    for key in order:
        sec = dd.sections.get(key)
        if not sec:
            continue
        P.append(f"<h2>{html.escape(sec.title)}</h2>")
        P.append("<div class='card'>")
        for ln in sec.lines:
            P.append(_line_html(ln))
        if sec.table is not None and not sec.table.empty:
            P.append(_df_to_html(sec.table))
        if key == "quality" and getattr(dd, "_beneish_comps", None):
            comp = dd._beneish_comps
            P.append("<p class='note'>Thành phần Beneish M-score (chỉ số &gt;1 ở DSRI/SGI/AQI/TATA "
                     "nghiêng về hướng nghi ngờ):</p>")
            P.append(_df_to_html(pd.DataFrame({k: [f"{v:.2f}" if v is not None else "—"]
                                               for k, v in comp.items()})))
        if sec.explain:
            P.append("<div class='explain'><span class='lbl'>💡 Đọc hiểu</span>")
            for ex in sec.explain:
                P.append(_line_html(ex))
            P.append("</div>")
        P.append("</div>")

    P.append("<div class='foot'>Báo cáo tất định, sinh tự động từ báo cáo tài chính công bố (VCI). "
             "Beneish M-score và Altman Z hiệu chỉnh cho thị trường Mỹ — chỉ là cờ tham khảo, KHÔNG "
             "phải khuyến nghị đầu tư. Luôn đối chiếu thuyết minh BCTC và báo cáo kiểm toán trước khi "
             "ra quyết định.</div>")
    P.append("</div>")
    return _html_shell(title, "".join(P))


def _overview_charts(dd: DeepDive) -> str:
    biz = dd.sections.get("business")
    qual = dd.sections.get("quality")
    blocks = []
    if biz is not None and biz.table is not None and not biz.table.empty:
        t = biz.table.tail(5)
        yrs = [str(int(y)) for y in t["Năm"]]
        blocks.append("<div class='chart'><h4>Doanh thu (tỷ đồng)</h4>" +
                      _svg_bars(list(zip(yrs, t["Doanh thu"]))) + "</div>")
        if "LN sau thuế" in t.columns:
            blocks.append("<div class='chart'><h4>Lợi nhuận sau thuế (tỷ)</h4>" +
                          _svg_bars(list(zip(yrs, t["LN sau thuế"])), color="var(--green)") + "</div>")
    if qual is not None and qual.table is not None and not qual.table.empty:
        t = qual.table.tail(5)
        yrs = [str(int(y)) for y in t["Năm"]]
        series = [("LN sau thuế", "var(--accent)", [v/1e9 if v is not None else None for v in t["LN sau thuế"]]),
                  ("CFO", "var(--green)", [v/1e9 if v is not None else None for v in t["CFO"]])]
        blocks.append("<div class='chart'><h4>Lợi nhuận vs Dòng tiền HĐKD (tỷ)</h4>" +
                      _svg_grouped(yrs, series) + "</div>")
    return "".join(blocks)


def _html_shell(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)} — Phân tích forensic</title>"
            f"<style>{_CSS}</style></head><body>{body}"
            f"<script>{_TOGGLE_JS}</script></body></html>")


# ============================================================================
# Tóm tắt Telegram gọn (khác báo cáo đầy đủ)
# ============================================================================
def telegram_summary(dd: DeepDive) -> str:
    if dd.error:
        return f"❌ {dd.symbol}: lỗi tải dữ liệu."
    title = f"{dd.symbol}" + (f" ({dd.name})" if dd.name and dd.name != dd.symbol else "")
    lines = [f"📑 <b>Soi BCTC: {title}</b>"]
    if dd.is_bank:
        lines.append("Ngân hàng — đánh giá bằng khung CAMELS (xem báo cáo riêng).")
        return "\n".join(lines)
    lines.append(dd.verdict.replace("⚠️", "").strip())
    if dd.red_flags:
        lines.append("")
        lines.append("🔻 <b>Cờ đỏ:</b>")
        for f in dd.red_flags[:5]:
            lines.append("• " + f.replace("🔻", "").strip())
    if dd.positives:
        lines.append("")
        for p in dd.positives[:2]:
            lines.append(p)
    return "\n".join(lines)


# ============================================================================
# Build + CLI
# ============================================================================
def build(symbol: str, with_valuation: bool = True, with_group: bool = True) -> DeepDive:
    fx = VCIFundamentals()
    sectors = valuation = group = None
    try:
        from vn_sectors import VCISectors
        sectors = VCISectors()
    except Exception as e:  # noqa: BLE001
        logger.warning("Không nạp được vn_sectors: %s", e)
    if with_valuation:
        try:
            from vn_valuation import VNValuation
            valuation = VNValuation(fx=fx, sx=sectors)
        except Exception as e:  # noqa: BLE001
            logger.warning("Không nạp được vn_valuation: %s", e)
    if with_group:
        try:
            from vn_group import VNGroup
            group = VNGroup()
        except Exception as e:  # noqa: BLE001
            logger.warning("Không nạp được vn_group: %s", e)
    engine = VNDeepDive(fx=fx, sectors=sectors, valuation=valuation, group=group)
    return engine.analyze(symbol)


def main() -> None:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser(description="Báo cáo forensic chuyên sâu một mã (VCI, keyless).")
    ap.add_argument("symbol", help="Mã cổ phiếu, vd FPT")
    ap.add_argument("--no-html", action="store_true", help="Không xuất HTML")
    ap.add_argument("--no-md", action="store_true", help="Không xuất Markdown")
    ap.add_argument("--no-valuation", action="store_true", help="Bỏ tầng định giá (nhanh hơn)")
    ap.add_argument("--no-group", action="store_true", help="Bỏ danh sách công ty con (CafeF)")
    ap.add_argument("--telegram", action="store_true", help="Gửi tóm tắt gọn qua Telegram")
    ap.add_argument("--out", default=REPORTS_DIR, help="Thư mục xuất")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    sym = args.symbol.upper().strip()
    print(f"⏳ Đang soi báo cáo tài chính {sym} ...")
    dd = build(sym, with_valuation=not args.no_valuation, with_group=not args.no_group)
    if dd.error:
        print(f"❌ Lỗi: {dd.error}")
        return
    os.makedirs(args.out, exist_ok=True)

    if not args.no_md:
        p = os.path.join(args.out, f"{sym}_deepdive.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(render_markdown(dd))
        print(f"✅ Markdown: {p}")
    if not args.no_html:
        p = os.path.join(args.out, f"{sym}_deepdive.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(render_html(dd))
        print(f"✅ HTML: {p}")

    print(f"\n{dd.verdict}")
    for fl in dd.red_flags:
        print("  ", fl)

    if args.telegram:
        try:
            from vn_telegram import send_message
            send_message(telegram_summary(dd))
            print("📨 Đã gửi tóm tắt Telegram.")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Không gửi được Telegram: {e}")


if __name__ == "__main__":
    main()
