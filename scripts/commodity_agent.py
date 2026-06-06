#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commodity Market Report Agent
- Đọc RSS tin tức thế giới mỗi 30 phút, thu thập bài liên quan hàng hóa
- Tạo báo cáo tổng hợp 2 lần/ngày: 7:00 (phiên Á) và 20:00 (phiên Mỹ)
- Báo cáo: phân tích vĩ mô, tín hiệu giao dịch, mức giá, rủi ro
- Tổng kết tuần vào thứ 6 sau 20:00
"""
import json, os, time, hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT               = Path(__file__).parent.parent
TELEGRAM_TOKEN      = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT       = os.environ.get('TELEGRAM_CHAT', '')
GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY', '')
STATE_FILE          = str(_ROOT / 'data' / 'last_commodity_news.json')
OUTPUT_DIR          = _ROOT / 'outputs'
VN_TZ               = timezone(timedelta(hours=7))

MORNING_REPORT_HOUR = 7   # 7:00 VN — trước phiên Á
EVENING_REPORT_HOUR = 20  # 20:00 VN — trước phiên Mỹ
MAX_ARTICLES        = 40  # tối đa bài đưa vào một báo cáo

RSS_FEEDS = [
    ('MarketWatch',       'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ('BBC Business',      'http://feeds.bbci.co.uk/news/business/rss.xml'),
    ('AP Business',       'https://feeds.apnews.com/rss/apf-business'),
    ('The Guardian Biz',  'https://www.theguardian.com/business/rss'),
    ('Al Jazeera',        'https://www.aljazeera.com/xml/rss/all.xml'),
    ('CNBC Commodities',  'https://www.cnbc.com/id/10000664/device/rss/rss.html'),
    ('OilPrice.com',      'https://oilprice.com/rss/main'),
    ('Mining.com',        'https://www.mining.com/feed/'),
]

COMMODITY_KEYWORDS = [
    'oil', 'crude', 'opec', 'petroleum', 'gas', 'lng', 'fuel', 'brent', 'wti',
    'gold', 'silver', 'copper', 'aluminum', 'steel', 'iron', 'nickel', 'zinc',
    'wheat', 'corn', 'soybean', 'rice', 'coffee', 'sugar', 'cotton', 'cocoa',
    'commodity', 'commodities', 'supply chain', 'tariff', 'sanction',
    'trade war', 'shortage', 'export ban', 'freight', 'shipping',
    'harvest', 'drought', 'flood', 'embargo', 'inflation', 'fed rate',
    'dollar index', 'treasury', 'china economy', 'gdp',
]

# ── State ─────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'seen': [],
        'pending_articles': [],
        'last_morning_report': '',
        'last_evening_report': '',
        'last_weekly_summary': '',
        'weekly_reports': [],
    }

def save_state(state):
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def article_id(title, link):
    return hashlib.md5(f'{title}{link}'.encode()).hexdigest()[:12]

# ── RSS ───────────────────────────────────────────────────────
def fetch_rss(url):
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(r.content)
        articles = []
        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            link  = item.findtext('link', '').strip()
            desc  = item.findtext('description', '').strip()
            if title:
                articles.append({'title': title, 'link': link, 'desc': desc[:400]})
        return articles
    except Exception as e:
        print(f'  Lỗi RSS {url}: {e}')
        return []

def is_commodity_related(title, desc):
    text = (title + ' ' + desc).lower()
    return any(kw in text for kw in COMMODITY_KEYWORDS)

# ── Gemini ────────────────────────────────────────────────────
def call_gemini(prompt, max_tokens=1500):
    url = (
        'https://generativelanguage.googleapis.com/v1beta/models/'
        f'gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.2, 'maxOutputTokens': max_tokens},
    }
    try:
        r = requests.post(url, json=payload, timeout=60)
        data = r.json()
        if 'candidates' not in data:
            err = data.get('error', {})
            if err.get('code') == 429:
                print('  Gemini hết quota hôm nay (429).')
                return 'QUOTA_EXCEEDED'
            print(f'  Lỗi Gemini API: {data}')
            return None
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f'  Lỗi Gemini: {e}')
        return None

def build_session_report_prompt(articles, session, date_str):
    articles_text = '\n'.join([
        f'{i+1}. [{a["source"]}] {a["title"]}\n   {a["desc"][:300]}'
        for i, a in enumerate(articles[:MAX_ARTICLES])
    ])
    context = 'tin tức qua đêm và đầu phiên Á' if session == 'morning' else 'tin tức trong ngày và đầu phiên Mỹ'
    session_vn = 'PHIÊN SÁ (07:00 VN)' if session == 'morning' else 'PHIÊN MỸ (20:00 VN)'

    return f"""Bạn là chuyên gia phân tích thị trường hàng hóa toàn cầu với kinh nghiệm giao dịch thực tế.
Dưới đây là {len(articles)} {context} ngày {date_str}:

{articles_text}

Hãy viết BÁO CÁO PHÂN TÍCH {session_vn} bằng TIẾNG VIỆT theo đúng cấu trúc sau (không thêm gì ngoài cấu trúc này):

🌍 VĨ MÔ & TIN TỨC NỔI BẬT
[Tóm tắt 2-3 yếu tố vĩ mô/địa chính trị quan trọng nhất tác động đến thị trường hàng hóa hôm nay]

🛢️ NĂNG LƯỢNG — Dầu WTI/Brent, Khí tự nhiên
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: Hỗ trợ [...] | Kháng cự [...]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

🥇 KIM LOẠI QUÝ — Vàng (XAU/USD), Bạc
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: Hỗ trợ [...] | Kháng cự [...]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

🌾 NÔNG SẢN — Ngô, Đậu tương, Lúa mì
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: [mức giá quan trọng nếu có trong tin, nếu không ghi "N/A"]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

🔩 KIM LOẠI CÔNG NGHIỆP — Đồng, Nhôm, Niken
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: [mức giá quan trọng nếu có trong tin, nếu không ghi "N/A"]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

📋 KHUYẾN NGHỊ PHIÊN
[2-3 khuyến nghị cụ thể, actionable cho phiên giao dịch này — ưu tiên thực tế]

⚠️ THEO DÕI PHIÊN
[2-3 sự kiện/dữ liệu quan trọng cần theo dõi trong phiên]

Lưu ý: Nếu không đủ tin về một nhóm, đánh giá dựa trên bối cảnh thị trường chung. Viết ngắn gọn, rõ ràng, chuyên nghiệp."""

def generate_session_report(articles, session, date_str):
    if not articles:
        return None
    prompt = build_session_report_prompt(articles, session, date_str)
    return call_gemini(prompt, max_tokens=1600)

def generate_weekly_report(weekly_reports, week_str):
    if not weekly_reports:
        return None
    reports_text = '\n\n'.join([
        f'--- {r["date"]} ({r["session"]}) ---\n{r["summary"]}'
        for r in weekly_reports[-14:]
    ])
    prompt = f"""Bạn là chuyên gia phân tích thị trường hàng hóa toàn cầu.
Dưới đây là các báo cáo phiên trong tuần {week_str}:

{reports_text}

Viết BÁO CÁO TỔNG KẾT TUẦN thị trường hàng hóa bằng TIẾNG VIỆT, gồm:
1. Sự kiện & xu hướng nổi bật nhất tuần (3-4 điểm)
2. Hiệu suất từng nhóm: Năng lượng, Kim loại quý, Nông sản, Kim loại công nghiệp
3. Yếu tố rủi ro lớn nhất tuần tới
4. Dự báo xu hướng ngắn hạn theo nhóm

Khoảng 250-300 từ, rõ ràng, chuyên nghiệp. KHÔNG thêm lời dẫn hay kết luận thừa."""
    return call_gemini(prompt, max_tokens=1200)

# ── Output ────────────────────────────────────────────────────
def save_report_file(text, session, date_str):
    OUTPUT_DIR.mkdir(exist_ok=True)
    filename = f'report_{date_str}_{session}.txt'
    (OUTPUT_DIR / filename).write_text(text, encoding='utf-8')
    print(f'Lưu báo cáo → outputs/{filename}')

# ── Telegram ──────────────────────────────────────────────────
def send_telegram(msg):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    if len(msg) > 4000:
        msg = msg[:3950] + '\n\n[...báo cáo đầy đủ trong outputs/]'
    payload = {'chat_id': TELEGRAM_CHAT, 'text': msg, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get('ok', False)
    except Exception:
        return False

# ── Report logic ──────────────────────────────────────────────
def try_send_session_report(state, now_vn, session):
    today_str = now_vn.strftime('%Y-%m-%d')
    state_key = f'last_{session}_report'

    if state.get(state_key) == today_str:
        return
    hour = now_vn.hour
    if session == 'morning' and hour < MORNING_REPORT_HOUR:
        return
    if session == 'evening' and hour < EVENING_REPORT_HOUR:
        return

    articles = state.get('pending_articles', [])
    session_vn = 'SÁNG (Phiên Á)' if session == 'morning' else 'CHIỀU (Phiên Mỹ)'
    emoji = '🌅' if session == 'morning' else '🌆'

    print(f'Tạo báo cáo {session_vn} {today_str} ({len(articles)} tin tích lũy)...')

    if not articles:
        print('Không có tin tức tích lũy, bỏ qua.')
        state[state_key] = today_str
        return

    text = generate_session_report(articles, session, today_str)
    if text == 'QUOTA_EXCEEDED':
        print('Hết quota Gemini, bỏ qua báo cáo.')
        return
    if not text:
        print('Gemini không trả về kết quả.')
        return

    header = (
        f'{emoji} <b>BÁO CÁO {session_vn.upper()} — {now_vn.strftime("%d/%m/%Y")}</b>\n'
        f'📰 Tổng hợp {min(len(articles), MAX_ARTICLES)} tin tức | '
        f'⏱ {now_vn.strftime("%H:%M")} (Giờ VN)\n\n'
    )
    msg = header + text

    if send_telegram(msg):
        print(f'Gửi báo cáo {session_vn} OK')
        state[state_key] = today_str
        save_report_file(text, session, today_str)

        # Lưu tóm tắt để dùng cho báo cáo tuần
        if 'weekly_reports' not in state:
            state['weekly_reports'] = []
        state['weekly_reports'].append({
            'date':    today_str,
            'session': session,
            'summary': text[:700],
        })
        state['weekly_reports'] = state['weekly_reports'][-14:]

        # Xóa pending sau khi cả hai báo cáo trong ngày đã gửi
        other_key = 'last_evening_report' if session == 'morning' else 'last_morning_report'
        if state.get(other_key) == today_str:
            state['pending_articles'] = []
            print('Cả hai báo cáo hôm nay đã gửi → xóa pending_articles')
    else:
        print(f'Lỗi gửi báo cáo {session_vn}')

def try_send_weekly_summary(state, now_vn):
    if now_vn.weekday() != 4:  # Thứ 6
        return
    week_str = now_vn.strftime('%Y-W%W')
    if state.get('last_weekly_summary') == week_str:
        return
    if now_vn.hour < EVENING_REPORT_HOUR:
        return

    weekly_reports = state.get('weekly_reports', [])
    print(f'Tạo tổng kết tuần {week_str} ({len(weekly_reports)} báo cáo phiên)...')

    if not weekly_reports:
        state['last_weekly_summary'] = week_str
        return

    text = generate_weekly_report(weekly_reports, week_str)
    if text == 'QUOTA_EXCEEDED':
        print('Hết quota Gemini, bỏ qua tổng kết tuần.')
        return
    if text:
        msg = (
            f'🗓 <b>TỔNG KẾT THỊ TRƯỜNG HÀNG HÓA TUẦN {week_str}</b>\n\n'
            f'{text}\n\n'
            f'⏱ {now_vn.strftime("%d/%m/%Y %H:%M")} (Giờ VN)'
        )
        if send_telegram(msg):
            print('Gửi tổng kết tuần OK')
            state['last_weekly_summary'] = week_str
            save_report_file(text, 'weekly', now_vn.strftime('%Y-%m-%d'))
        else:
            print('Lỗi gửi tổng kết tuần')

# ── Main ──────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT or not GEMINI_API_KEY:
        print('Thiếu biến môi trường: TELEGRAM_TOKEN / TELEGRAM_CHAT / GEMINI_API_KEY')
        return

    now_vn = datetime.now(timezone.utc).astimezone(VN_TZ)
    state  = load_state()
    seen   = set(state.get('seen', []))

    if len(seen) > 500:
        seen = set(list(seen)[-300:])

    # Giữ pending_articles trong 48 giờ gần nhất
    cutoff_str = (now_vn - timedelta(hours=48)).strftime('%Y-%m-%d %H:%M')
    state['pending_articles'] = [
        a for a in state.get('pending_articles', [])
        if a.get('collected_at', '') >= cutoff_str
    ]
    state['weekly_reports'] = state.get('weekly_reports', [])[-14:]

    print(f'=== Commodity Report Agent — {now_vn.strftime("%Y-%m-%d %H:%M")} (Giờ VN) ===')
    print(f'Pending articles hiện tại: {len(state["pending_articles"])}')

    # Thu thập bài mới (không gọi Gemini — chỉ thu thập)
    new_count = 0
    for source, feed_url in RSS_FEEDS:
        print(f'Đọc RSS: {source}...', end=' ', flush=True)
        articles = fetch_rss(feed_url)
        count = 0
        for a in articles:
            aid = article_id(a['title'], a['link'])
            if aid in seen:
                continue
            if not is_commodity_related(a['title'], a['desc']):
                continue
            seen.add(aid)
            state['pending_articles'].append({
                'id':           aid,
                'source':       source,
                'title':        a['title'],
                'desc':         a['desc'],
                'collected_at': now_vn.strftime('%Y-%m-%d %H:%M'),
            })
            count += 1
            new_count += 1
        print(f'{count} bài mới')

    print(f'Thu thập xong: +{new_count} bài mới | Tổng pending: {len(state["pending_articles"])}')

    # Kiểm tra và gửi báo cáo phiên
    try_send_session_report(state, now_vn, 'morning')
    try_send_session_report(state, now_vn, 'evening')

    # Tổng kết tuần (thứ 6 sau 20:00)
    try_send_weekly_summary(state, now_vn)

    state['seen'] = list(seen)
    save_state(state)
    print('=== Hoàn thành ===')

if __name__ == '__main__':
    main()
