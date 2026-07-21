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
def render_markdown(dd: DeepDive) -> str:
    today = _dt.date.today().isoformat()
    out: List[str] = []
    title = f"{dd.symbol}" + (f" — {dd.name}" if dd.name and dd.name != dd.symbol else "")
    out.append(f"# Báo cáo phân tích chuyên sâu: {title}")
    out.append(f"> Ngành: {dd.sector or 'n/a'} · Lập ngày {today} · Nguồn: BCTC VCI (Vietcap)")
    out.append("")
    if dd.error:
        out.append(f"**Lỗi tải dữ liệu:** {dd.error}")
        return "\n".join(out)

    # Kết luận đặt LÊN ĐẦU (form chuyên gia: executive summary)
    out.append("## Kết luận nhanh")
    out.append(dd.verdict)
    out.append("")
    if dd.red_flags:
        out.append("**🔻 Cờ đỏ forensic:**")
        for f in dd.red_flags:
            out.append(f"- {f}")
        out.append("")
    if dd.positives:
        out.append("**✅ Điểm cộng:**")
        for p in dd.positives:
            out.append(f"- {p}")
        out.append("")

    # Các phần theo thứ tự
    order = ["group", "business", "quality", "cashflow", "balance", "distress", "valuation", "bank"]
    for key in order:
        sec = dd.sections.get(key)
        if not sec:
            continue
        out.append(f"## {sec.title}")
        for ln in sec.lines:
            out.append(ln + "  ")
        if sec.explain:
            out.append("")
            for ex in sec.explain:
                out.append(f"> 💡 {ex}")
            out.append("")
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


def _line_html(ln: str) -> str:
    """Thoát HTML rồi khôi phục **đậm** → <strong>, *nghiêng* → <em>."""
    import re as _re
    esc = html.escape(ln)
    esc = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
    esc = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc)
    return f"<p class='line'>{esc}</p>"


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
             f"Nguồn: BCTC VCI (Vietcap) · Báo cáo forensic tất định</div>")
    if dd.error:
        P.append(f"<div class='flag'>Lỗi tải dữ liệu: {html.escape(dd.error)}</div></div>")
        return _html_shell(title, "".join(P))

    # Executive summary
    P.append("<div class='card'>")
    P.append(f"<div class='verdict'>{html.escape(dd.verdict)}</div>")
    for f in dd.red_flags:
        P.append(f"<div class='flag'>{html.escape(f)}</div>")
    for p in dd.positives:
        P.append(f"<div class='pos'>{html.escape(p)}</div>")
    P.append("</div>")

    # Biểu đồ tổng quan (nếu có dữ liệu business + quality)
    charts = _overview_charts(dd)
    if charts:
        P.append("<div class='card charts'>" + charts + "</div>")

    order = ["group", "business", "quality", "cashflow", "balance", "distress", "valuation", "bank"]
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
        if sec.explain:
            P.append("<div class='explain'><span class='lbl'>💡 Đọc hiểu</span>")
            for ex in sec.explain:
                P.append(_line_html(ex))
            P.append("</div>")
        if key == "quality" and getattr(dd, "_beneish_comps", None):
            comp = dd._beneish_comps
            dfc = pd.DataFrame([comp])
            P.append("<p class='note'>Thành phần Beneish M-score (chỉ số &gt;1 ở DSRI/SGI/AQI/TATA "
                     "nghiêng về hướng nghi ngờ):</p>")
            P.append(_df_to_html(pd.DataFrame({k: [f"{v:.2f}" if v is not None else "—"]
                                               for k, v in comp.items()})))
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
def build(symbol: str, with_valuation: bool = True) -> DeepDive:
    fx = VCIFundamentals()
    sectors = valuation = None
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
    engine = VNDeepDive(fx=fx, sectors=sectors, valuation=valuation)
    return engine.analyze(symbol)


def main() -> None:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser(description="Báo cáo forensic chuyên sâu một mã (VCI, keyless).")
    ap.add_argument("symbol", help="Mã cổ phiếu, vd FPT")
    ap.add_argument("--no-html", action="store_true", help="Không xuất HTML")
    ap.add_argument("--no-md", action="store_true", help="Không xuất Markdown")
    ap.add_argument("--no-valuation", action="store_true", help="Bỏ tầng định giá (nhanh hơn)")
    ap.add_argument("--telegram", action="store_true", help="Gửi tóm tắt gọn qua Telegram")
    ap.add_argument("--out", default=REPORTS_DIR, help="Thư mục xuất")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    sym = args.symbol.upper().strip()
    print(f"⏳ Đang soi báo cáo tài chính {sym} ...")
    dd = build(sym, with_valuation=not args.no_valuation)
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
