# -*- coding: utf-8 -*-
"""
Gửi bản tin chứng khoán VN sang Telegram — viết cho NGƯỜI MỚI, dễ hiểu.

Thu thập kết quả pipeline (báo cáo phân tích + bản tin dịch chuyển giá + vài tin thị
trường), rồi nhờ Gemini viết một bản tin tiếng Việt đơn giản, thân thiện cho người
chưa có kinh nghiệm và không thuộc tên mã. Nếu không có GEMINI_API_KEY thì gửi bản
rút gọn theo mẫu cố định.

Nhãn "PHÂN TÍCH CHỨNG KHOÁN VN" để tách với nhóm hàng hóa / ngân hàng trong cùng repo.
Secret dùng: TELEGRAM_TOKEN + TELEGRAM_CHAT (+ GEMINI_API_KEY nếu có).
"""

import os
import re
import sys
import glob
import time
import html
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT", "").strip()
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY", "") or "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
REPORTS = os.environ.get("REPORTS_DIR", "reports")


def run_url():
    s = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    r = os.environ.get("GITHUB_REPOSITORY", "")
    rid = os.environ.get("GITHUB_RUN_ID", "")
    return f"{s}/{r}/actions/runs/{rid}" if r and rid else ""


def read_latest_report():
    files = sorted(glob.glob(os.path.join(REPORTS, "report_*.md")))
    if not files:
        files = [f for f in sorted(glob.glob(os.path.join(REPORTS, "*.md"))) if "dich-chuyen" not in f]
    return files[-1] if files else None


def extract_summary(md_path):
    if not md_path or not os.path.exists(md_path):
        return []
    lines = open(md_path, encoding="utf-8").read().splitlines()
    out, grab = [], False
    for ln in lines:
        if re.match(r"^#+\s*.*Summary", ln) or "分析结果摘要" in ln or "Tóm tắt" in ln:
            grab = True
            continue
        if grab:
            if ln.startswith("---") or re.match(r"^#+\s", ln):
                break
            if ln.strip():
                out.append(ln.strip().replace("**", ""))
    return out


def extract_one_liners(md_path):
    """Lấy 'One-line Decision' / '一句话决策' cho từng mã (câu chốt dễ hiểu nhất)."""
    if not md_path or not os.path.exists(md_path):
        return []
    txt = open(md_path, encoding="utf-8").read()
    out = []
    for m in re.finditer(r"(One-line Decision|一句话决策|Một câu)\**\s*[:：]\s*(.+)", txt):
        s = m.group(2).strip().strip("*").strip()
        if s:
            out.append(s)
    return out


def read_movers_raw():
    p = os.path.join(REPORTS, "dich-chuyen-gia.md")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def read_topdown_digest():
    """Digest top-down (định lượng, keyless) do vn_report.py ghi ra reports/topdown_digest.txt.

    Là TEXT THUẦN, có ký tự < > & (vd 'P/B>1', 'ROE < r') → phải HTML-escape cho
    parse_mode=HTML; in đậm dòng tiêu đề đầu. Trả '' nếu chưa có file.
    """
    p = os.path.join(REPORTS, "topdown_digest.txt")
    if not os.path.exists(p):
        return ""
    raw = open(p, encoding="utf-8").read().strip()
    if not raw:
        return ""
    lines = [html.escape(ln) for ln in raw.split("\n")]
    if lines:
        lines[0] = f"<b>{lines[0]}</b>"
    return "\n".join(lines)


def extract_movers(md_path, section, top=6):
    """Lấy 'MÃ +x.xx%' từ một mục của bản tin dịch chuyển giá."""
    if not md_path or not os.path.exists(md_path):
        return []
    txt = open(md_path, encoding="utf-8").read()
    rows = []
    for b in re.split(r"\n##\s+", txt):
        if section in b:
            for ln in b.splitlines():
                m = re.match(r"\|\s*([A-Z0-9]{2,5})\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([+-][\d.]+%)", ln)
                if m:
                    rows.append(f"{m.group(1)} {m.group(2).strip()}")
                if len(rows) >= top:
                    break
    return rows


_SIGNAL_VN = {
    # tiếng Việt (giá trị mới) — đặt cụm dài trước để khớp đúng
    "mua mạnh": "🟢 MUA MẠNH", "mua dần": "🟢 MUA DẦN", "cân nhắc mua": "🟢 CÂN NHẮC MUA",
    "mua": "🟢 CÂN NHẮC MUA", "quan sát": "⏸️ CHỜ / QUAN SÁT", "nắm giữ": "✋ NẮM GIỮ",
    "giảm tỷ trọng": "🔻 GIẢM TỶ TRỌNG", "bán mạnh": "🔴 BÁN MẠNH", "bán": "🔴 BÁN",
    # tiếng Anh (khi report chạy en)
    "strong buy": "🟢 MUA MẠNH", "buy": "🟢 CÂN NHẮC MUA", "accumulate": "🟢 MUA DẦN",
    "watch": "⏸️ CHỜ / QUAN SÁT", "hold": "✋ NẮM GIỮ",
    "reduce": "🔻 GIẢM TỶ TRỌNG", "sell": "🔴 BÁN", "strong sell": "🔴 BÁN MẠNH",
}
_TREND_VN = {
    "tăng mạnh": "xu hướng tăng mạnh", "giảm mạnh": "xu hướng giảm mạnh",
    "đi ngang": "đi ngang", "tăng": "xu hướng tăng", "giảm": "xu hướng giảm",
    "strongly bullish": "xu hướng tăng mạnh", "bullish": "xu hướng tăng",
    "neutral": "trung tính", "sideways": "đi ngang", "volatile": "biến động mạnh",
    "bearish": "xu hướng giảm", "strongly bearish": "xu hướng giảm mạnh",
}


def _vn_signal(sig_text):
    """'Watch | Score 59 | Bullish' -> ('⏸️ CHỜ...', 59, 'xu hướng tăng')."""
    low = sig_text.lower()
    action = next((v for k, v in _SIGNAL_VN.items() if k in low), sig_text.split("|")[0].strip())
    score = None
    m = re.search(r"score\s*(\d+)", low)
    if m:
        score = int(m.group(1))
    trend = ""
    for k in sorted(_TREND_VN, key=len, reverse=True):
        if k in low:
            trend = _TREND_VN[k]; break
    return action, score, trend


def per_stock_details(md_path):
    """Trích theo mã: câu chốt (one-liner), rủi ro chính, giá, hỗ trợ/kháng cự."""
    details = {}
    if not md_path or not os.path.exists(md_path):
        return details
    txt = open(md_path, encoding="utf-8").read()
    for sec in re.split(r"\n##\s+", txt):
        mtk = re.search(r"\(([A-Z0-9]{2,5})\.VN\)", sec)
        if not mtk:
            continue
        tk = mtk.group(1)
        d = {}
        m = re.search(r"(One-line Decision|一句话决策)\**\s*[:：]\s*(.+)", sec)
        if m:
            d["oneliner"] = m.group(2).strip().strip("*").strip()
        # rủi ro đầu tiên trong Risk Alerts
        rm = re.search(r"(Risk Alerts|风险)\**.*?\n(?:[-*]\s*(.+))", sec)
        if rm and rm.group(2) and "No specific" not in rm.group(2):
            d["risk"] = rm.group(2).strip()
        pm = re.search(r"(Support|支撑)\**\s*[:：]?\s*\|?\s*([\d,\.]+)", sec)
        if pm:
            d["support"] = pm.group(2)
        details[tk] = d
    return details


def _gnews(query, n=4, days=10):
    """Tiêu đề tin tiếng Việt qua Google News RSS."""
    from email.utils import parsedate_to_datetime
    from datetime import timezone, timedelta
    try:
        u = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
        r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        root = ET.fromstring(r.content)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out = []
        for it in root.findall(".//item"):
            t = (it.findtext("title") or "").strip()
            if not t:
                continue
            pub = it.findtext("pubDate")
            if pub:
                try:
                    dt = parsedate_to_datetime(pub)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
            out.append(t)
            if len(out) >= n:
                break
        return out
    except Exception as e:
        print(f"[news] lỗi '{query}': {e}", file=sys.stderr)
        return []


def market_news(n=5):
    return _gnews("chứng khoán VN-Index hôm nay", n=n, days=3)


def parse_stocks_from_summary(summary):
    """Từ dòng '⚪ Tên công ty(HVN.VN): Watch | Score 59 | ...' → (name, ticker, signal)."""
    out = []
    for ln in summary:
        m = re.search(r"(.*?)\(([A-Z0-9]{2,5})\.VN\)\s*[:：]\s*(.+)", ln)
        if m:
            name = re.sub(r"^[^A-Za-zÀ-ỹ0-9]+", "", m.group(1)).strip()
            out.append((name, m.group(2), m.group(3).strip()))
    return out


def build_stock_insights(stocks, detail_n=8):
    """Với các mã nổi bật nhất, gom tin tức riêng của mã (nguồn insight doanh nghiệp)."""
    blocks = []
    for name, tk, sig in stocks[:detail_n]:
        q = f"{name} {tk} cổ phiếu"
        news = _gnews(q, n=3, days=14)
        news_txt = "\n".join(f"    · {t}" for t in news) if news else "    · (không có tin gần đây)"
        blocks.append(f"- {name} ({tk}) | tín hiệu kỹ thuật: {sig}\n  Tin gần đây:\n{news_txt}")
        time.sleep(0.2)
    return "\n".join(blocks)


def gemini_overview(data_block):
    """MỘT lần gọi Gemini (nhẹ) để viết đoạn tổng quan thị trường + ngành nổi bật.
    Có retry + ưu tiên model lite để đỡ tốn quota (đang chia sẻ với nhóm khác)."""
    if not GEMINI_KEY:
        return None
    prompt = (
        "Bạn viết cho NGƯỜI MỚI chơi chứng khoán VN. Dựa HOÀN TOÀN trên dữ liệu dưới đây "
        "(không bịa), viết 3–5 câu tiếng Việt đơn giản: (1) không khí thị trường hôm nay; "
        "(2) nhóm NGÀNH/loại cổ phiếu nào đang nổi bật (tăng/giảm) và vì sao nếu tin có nói; "
        "(3) một lời nhắc thận trọng ngắn. Dùng thẻ <b> cho vài từ khóa, KHÔNG dùng ** markdown, "
        "KHÔNG liệt kê từng mã (phần đó đã có riêng).\n\n===== DỮ LIỆU =====\n" + data_block
    )
    models = []
    for m in ("gemini-2.5-flash-lite", GEMINI_MODEL):
        if m and m not in models:
            models.append(m)
    for model in models:
        for attempt in range(2):
            try:
                url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                       f":generateContent?key={GEMINI_KEY}")
                r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
                if r.status_code == 429:
                    print(f"[gemini] {model} 429 (quota), thử lại/đổi model...", file=sys.stderr)
                    time.sleep(4)
                    continue
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                print(f"[gemini] {model} lỗi: {e}", file=sys.stderr)
                time.sleep(2)
    return None


def _unused_gemini_brief(data_block):
    if not GEMINI_KEY:
        return None
    prompt = (
        "Bạn là người hướng dẫn đầu tư thân thiện cho NGƯỜI MỚI HOÀN TOÀN — họ chưa biết gì về "
        "chứng khoán và không thuộc tên mã. Viết một bản tin ngắn bằng tiếng Việt ĐƠN GIẢN, dễ hiểu, "
        "dựa HOÀN TOÀN trên dữ liệu bên dưới (tuyệt đối không bịa số liệu, không thêm mã ngoài danh sách).\n\n"
        "Yêu cầu trình bày (dùng cho Telegram, tránh bảng, dùng emoji vừa phải):\n"
        "1) '🌐 <b>Bức tranh chung</b>': 2–3 câu về không khí thị trường hôm nay (dựa trên tin thị trường + dịch chuyển giá).\n"
        "2) '🎯 <b>Mã đáng chú ý</b>': phân tích KỸ 5–7 mã nổi bật nhất, mỗi mã một đoạn ngắn gồm 3 phần rõ ràng:\n"
        "   • <b>Tên công ty (mã)</b> — công ty làm gì.\n"
        "   • 🏭 <i>Insight ngành</i>: 1 câu về tình hình NGÀNH của mã đó (ngành đang thuận lợi/khó khăn ra sao). "
        "Chỉ nói nếu có cơ sở từ dữ liệu/tin hoặc hiểu biết chắc chắn; nếu không chắc thì nói 'chưa rõ'.\n"
        "   • 🏢 <i>Insight doanh nghiệp</i>: 1–2 câu về điều đang diễn ra với CHÍNH công ty này, DỰA TRÊN tin tức riêng "
        "của mã ở dữ liệu (kết quả kinh doanh, cổ tức, dòng tiền, sự kiện...). Nêu rõ nếu tin là tốt hay xấu.\n"
        "   • 👉 <i>Gợi ý cho người mới</i>: nên MUA DẦN / CHỜ NHỊP CHỈNH / QUAN SÁT / TRÁNH, kèm 1 rủi ro chính. "
        "Tránh thuật ngữ; nếu buộc dùng (RSI, MA...) giải thích ngay trong ngoặc.\n"
        "   Các mã còn lại (nếu có) chỉ liệt kê tên + 1 câu ngắn.\n"
        "3) '📊 <b>Giá biến động mạnh</b>': vài mã tăng/giảm mạnh nhất kèm 1 câu, NHẮC rằng biến động lớn thường đi kèm "
        "tin tức, nên tìm hiểu trước khi hành động.\n"
        "4) Kết 1 dòng: thông tin tham khảo tự động, người mới nên tìm hiểu kỹ / hỏi người có kinh nghiệm, "
        "không dồn hết tiền vào một mã.\n"
        "Quan trọng: KHÔNG bịa tin doanh nghiệp — chỉ dùng tin có trong dữ liệu. Ngắn gọn, đọc lọt điện thoại. "
        "Dùng thẻ HTML <b>/<i> (Telegram hỗ trợ), KHÔNG dùng ** markdown.\n\n"
        "===== DỮ LIỆU =====\n" + data_block
    )
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
               f":generateContent?key={GEMINI_KEY}")
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"[gemini] lỗi: {e}", file=sys.stderr)
        return None


def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            parts.append(cur); cur = ""
        cur += line + "\n"
    if cur:
        parts.append(cur)
    ok = True
    for i, p in enumerate(parts):
        r = requests.post(url, data={"chat_id": CHAT, "text": p, "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"}, timeout=30)
        if r.status_code != 200:
            print(f"[telegram] lỗi phần {i+1}: {r.status_code} {r.text[:200]}", file=sys.stderr)
            ok = False
        time.sleep(0.5)
    return ok


def main():
    if not TOKEN or not CHAT:
        print("[telegram] Thiếu TELEGRAM_TOKEN/TELEGRAM_CHAT — bỏ qua gửi.", file=sys.stderr)
        return 0

    u = run_url()
    mkt_news = market_news()  # Google News RSS — keyless
    gainers = extract_movers(os.path.join(REPORTS, "dich-chuyen-gia.md"), "Tăng mạnh nhất", top=6)
    losers = extract_movers(os.path.join(REPORTS, "dich-chuyen-gia.md"), "Giảm mạnh nhất", top=6)
    surge = extract_movers(os.path.join(REPORTS, "dich-chuyen-gia.md"), "Bùng khối lượng", top=5)

    # ---- Bản tin HOÀN TOÀN KEYLESS (không LLM/Gemini): tin thị trường + dịch chuyển giá
    #      + phần TOP-DOWN định lượng. Luôn có nội dung, không phụ thuộc quota. ----
    L = [f"📈 <b>PHÂN TÍCH CHỨNG KHOÁN VN</b> — {datetime.now():%d/%m/%Y}",
         "<i>Tự động, tham khảo — không phải khuyến nghị.</i>", ""]
    if mkt_news:
        L += ["🌐 <b>Tin thị trường</b>"] + [f"• {html.escape(t)}" for t in mkt_news[:4]] + [""]

    if gainers or losers or surge:
        L.append("📊 <b>Giá biến động mạnh trong ngày</b>")
        if gainers:
            L.append("🟢 Tăng: " + html.escape(", ".join(gainers)))
        if losers:
            L.append("🔴 Giảm: " + html.escape(", ".join(losers)))
        if surge:
            L.append("⚡ Bùng khối lượng: " + html.escape(", ".join(surge)))
        L.append("<i>Biến động lớn thường đi kèm tin — nên tìm hiểu trước khi hành động.</i>")

    # ---- Phần TOP-DOWN (định lượng theo CFA: nhịp/ngành/định giá/sự kiện) ----
    td = read_topdown_digest()
    if td:
        L.append("\n" + "━" * 18)
        L.append(td)

    L.append("\n💬 Thông tin tự động, tham khảo. Người mới nên tìm hiểu kỹ, hỏi người có "
             "kinh nghiệm, không dồn hết vốn vào một mã.")
    if u:
        L.append(f'📄 <a href="{u}">Báo cáo đầy đủ (artifact)</a>')

    text = "\n".join(L)
    print(text, file=sys.stderr)
    ok = send(text)
    print("[telegram] gửi " + ("OK" if ok else "THẤT BẠI"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
