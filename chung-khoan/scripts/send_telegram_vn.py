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


def gemini_brief(data_block):
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

    rep = read_latest_report()
    summary = extract_summary(rep)
    one_liners = extract_one_liners(rep)
    movers = read_movers_raw()
    mkt_news = market_news()
    stocks = parse_stocks_from_summary(summary)
    stock_insights = build_stock_insights(stocks) if stocks else ""

    # Khối dữ liệu thô đưa cho Gemini
    data_block = "TIN THỊ TRƯỜNG CHUNG (tiêu đề):\n" + "\n".join(f"- {t}" for t in mkt_news) + "\n\n"
    if stock_insights:
        data_block += ("TỪNG MÃ NỔI BẬT (tên, mã, tín hiệu kỹ thuật, tin tức riêng của mã "
                       "— nguồn để rút insight doanh nghiệp):\n" + stock_insights + "\n\n")
    data_block += "TOÀN BỘ KẾT QUẢ PHÂN TÍCH (mã | tín hiệu | điểm):\n" + "\n".join(summary) + "\n\n"
    if one_liners:
        data_block += "CÂU CHỐT KỸ THUẬT TỪNG MÃ:\n" + "\n".join(f"- {s}" for s in one_liners) + "\n\n"
    data_block += "DỊCH CHUYỂN GIÁ NỔI BẬT:\n" + movers[:2200]

    header = f"📈 <b>PHÂN TÍCH CHỨNG KHOÁN VN</b> — {datetime.now():%d/%m/%Y}\n"
    body = gemini_brief(data_block)
    u = run_url()

    if body:
        text = header + "\n" + body
        if u:
            text += f'\n\n📄 <a href="{u}">Xem báo cáo kỹ thuật đầy đủ</a>'
    else:
        # Fallback: bản rút gọn theo mẫu (khi không có Gemini)
        lines = [header, "<i>Tự động, tham khảo — không phải khuyến nghị.</i>", "", "🎯 <b>Mã đáng chú ý</b>"]
        lines += [html.escape(s) for s in summary[:32]]
        lines.append("")
        lines.append("📊 <b>Giá biến động mạnh</b> — xem báo cáo đầy đủ.")
        if u:
            lines.append(f'\n📄 <a href="{u}">Mở báo cáo</a>')
        text = "\n".join(lines)

    print(text, file=sys.stderr)
    ok = send(text)
    print("[telegram] gửi " + ("OK" if ok else "THẤT BẠI"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
