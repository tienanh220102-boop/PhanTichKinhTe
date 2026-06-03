#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commodity Supply Chain Agent
- Doc RSS tin tuc the gioi moi 30 phut
- Dung Gemini API phan tich tac dong len hang hoa
- Gui phan tich ngan gon qua Telegram
- Gui phan tich tong quan cuoi ngay va cuoi tuan
"""
import json, os, time, hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN      = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT       = os.environ.get('TELEGRAM_CHAT',  '')
GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY', '')
STATE_FILE          = 'last_commodity_news.json'
VN_TZ               = timezone(timedelta(hours=7))
MAX_ARTICLES        = 2   # So bai phan tich toi da moi lan chay (Gemini free tier: 20 RPD)
DAILY_SUMMARY_HOUR  = 17  # Gui tong quan ngay luc 17:00 VN

RSS_FEEDS = [
    # Tin tuc kinh te tong hop
    ('MarketWatch',       'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ('BBC Business',      'http://feeds.bbci.co.uk/news/business/rss.xml'),
    ('AP Business',       'https://feeds.apnews.com/rss/apf-business'),
    ('The Guardian Biz',  'https://www.theguardian.com/business/rss'),
    ('Al Jazeera',        'https://www.aljazeera.com/xml/rss/all.xml'),
    # Chuyen sau ve hang hoa
    ('CNBC Commodities',  'https://www.cnbc.com/id/10000664/device/rss/rss.html'),
    ('OilPrice.com',      'https://oilprice.com/rss/main'),
    ('Mining.com',        'https://www.mining.com/feed/'),
]

COMMODITY_KEYWORDS = [
    'oil', 'crude', 'opec', 'petroleum', 'gas', 'lng', 'fuel',
    'gold', 'silver', 'copper', 'aluminum', 'steel', 'iron', 'nickel', 'zinc',
    'wheat', 'corn', 'soybean', 'rice', 'coffee', 'sugar', 'cotton', 'cocoa',
    'commodity', 'commodities', 'supply chain', 'tariff', 'sanction',
    'trade war', 'shortage', 'export ban', 'import', 'freight', 'shipping',
    'harvest', 'drought', 'flood', 'embargo',
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
        'daily_articles': [],
        'last_daily_summary': '',
        'last_weekly_summary': '',
    }

def save_state(state):
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
                articles.append({'title': title, 'link': link, 'desc': desc[:300]})
        return articles
    except Exception as e:
        print(f'  Loi RSS {url}: {e}')
        return []

def is_commodity_related(title, desc):
    text = (title + ' ' + desc).lower()
    return any(kw in text for kw in COMMODITY_KEYWORDS)

# ── Gemini ────────────────────────────────────────────────────
def call_gemini(prompt, max_tokens=250):
    url = (
        'https://generativelanguage.googleapis.com/v1beta/models/'
        f'gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.2, 'maxOutputTokens': max_tokens},
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        data = r.json()
        if 'candidates' not in data:
            err = data.get('error', {})
            if err.get('code') == 429:
                print('  Gemini het quota hom nay (429), dung goi them.')
                return 'QUOTA_EXCEEDED'
            print(f'  Loi Gemini API: {data}')
            return None
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f'  Loi Gemini: {e}')
        return None

def analyze_with_gemini(title, desc):
    prompt = f"""Ban la chuyen gia phan tich chuoi cung ung hang hoa toan cau.
Phan tich su kien sau va danh gia tac dong len hang hoa the gioi:

Tieu de: {title}
Mo ta: {desc}

Tra loi NGAN GON theo dung dinh dang nay (khong them bat cu thu gi ngoai 5 dong, viet bang TIENG VIET):
TIEU_DE: [dich tieu de bai bao sang tieng Viet]
HANG_HOA: [ten hang hoa bi anh huong, cach nhau bang dau phay]
MUC_DO: [CAO / TRUNG_BINH / THAP]
TAC_DONG: [1 cau ngan gon mo ta tac dong thuc te bang tieng Viet]
HUONG: [TANG / GIAM / KHONG_RO]

Neu su kien KHONG co lien quan gi den hang hoa, chi tra loi mot dong: KHONG_LIEN_QUAN"""
    return call_gemini(prompt, max_tokens=250)

def generate_daily_summary_text(articles_today, date_str):
    if not articles_today:
        return None
    news_list = '\n'.join([
        f'- {a["tieu_de"]} | {a["hang_hoa"]} | {a["huong"]} | {a["tac_dong"]}'
        for a in articles_today
    ])
    prompt = f"""Ban la chuyen gia phan tich thi truong hang hoa toan cau.
Duoi day la cac su kien hang hoa noi bat trong ngay {date_str}:

{news_list}

Viet mot BAI PHAN TICH TONG QUAN NGAY ve thi truong hang hoa the gioi bang TIENG VIET, gom:
1. Tom tat xu huong chinh trong ngay
2. Cac hang hoa duoc chu y nhat va ly do
3. Rui ro va co hoi noi bat
4. Nhan dinh ngan han

Viet ro rang, chuyen nghiep, khoang 150-200 tu. KHONG them loi dan hay ket luan thua."""
    return call_gemini(prompt, max_tokens=800)

def generate_weekly_summary_text(articles_week, week_str):
    if not articles_week:
        return None
    news_list = '\n'.join([
        f'- [{a.get("date","")}] {a["tieu_de"]} | {a["hang_hoa"]} | {a["huong"]} | {a["tac_dong"]}'
        for a in articles_week
    ])
    prompt = f"""Ban la chuyen gia phan tich thi truong hang hoa toan cau.
Duoi day la cac su kien hang hoa noi bat trong tuan {week_str}:

{news_list}

Viet mot BAI PHAN TICH TONG QUAN TUAN ve thi truong hang hoa the gioi bang TIENG VIET, gom:
1. Nhung su kien chinh trong tuan anh huong den hang hoa
2. Xu huong gia cac hang hoa tieu bieu (dau, vang, ngu coc, kim loai)
3. Cac yeu to rui ro lon nhat tuan toi
4. Du bao xu huong ngan han

Viet ro rang, chuyen nghiep, khoang 200-250 tu. KHONG them loi dan hay ket luan thua."""
    return call_gemini(prompt, max_tokens=1000)

def parse_response(text):
    if not text or 'KHONG_LIEN_QUAN' in text:
        return None
    result = {}
    for line in text.split('\n'):
        if ':' in line:
            key, _, val = line.partition(':')
            result[key.strip()] = val.strip()
    if not all(k in result for k in ('MUC_DO', 'TAC_DONG', 'HANG_HOA', 'TIEU_DE')):
        return None
    return result

# ── Telegram ──────────────────────────────────────────────────
def send_telegram(msg):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {'chat_id': TELEGRAM_CHAT, 'text': msg, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get('ok', False)
    except Exception:
        return False

# ── Summary senders ───────────────────────────────────────────
def try_send_daily_summary(state, now_vn):
    today_str = now_vn.strftime('%Y-%m-%d')
    if state.get('last_daily_summary') == today_str:
        return
    if now_vn.hour < DAILY_SUMMARY_HOUR:
        return

    daily_articles = [a for a in state.get('daily_articles', []) if a.get('date') == today_str]
    print(f'Tao phan tich tong quan ngay {today_str} ({len(daily_articles)} su kien)...')

    if not daily_articles:
        state['last_daily_summary'] = today_str
        return

    text = generate_daily_summary_text(daily_articles, today_str)
    if text == 'QUOTA_EXCEEDED':
        print('Het quota Gemini, bo qua tong quan ngay.')
        return
    if text:
        msg = '\n'.join([
            f'📊 <b>TỔNG QUAN THỊ TRƯỜNG HÀNG HÓA — {now_vn.strftime("%d/%m/%Y")}</b>',
            '',
            text,
            '',
            f'⏱ Cập nhật: {now_vn.strftime("%H:%M")} (Giờ VN)',
        ])
        if send_telegram(msg):
            print('Gui tong quan ngay OK')
            state['last_daily_summary'] = today_str
        else:
            print('Loi gui tong quan ngay')

def try_send_weekly_summary(state, now_vn):
    if now_vn.weekday() != 4:  # Chi gui vao Thu 6 (weekday 4 = Friday)
        return
    week_str = now_vn.strftime('%Y-W%W')
    if state.get('last_weekly_summary') == week_str:
        return
    if now_vn.hour < DAILY_SUMMARY_HOUR:
        return

    week_articles = state.get('daily_articles', [])
    print(f'Tao phan tich tong quan tuan {week_str} ({len(week_articles)} su kien)...')

    if not week_articles:
        state['last_weekly_summary'] = week_str
        return

    text = generate_weekly_summary_text(week_articles, week_str)
    if text == 'QUOTA_EXCEEDED':
        print('Het quota Gemini, bo qua tong quan tuan.')
        return
    if text:
        msg = '\n'.join([
            f'🗓 <b>TỔNG QUAN THỊ TRƯỜNG HÀNG HÓA TUẦN — {week_str}</b>',
            '',
            text,
            '',
            f'⏱ Cập nhật: {now_vn.strftime("%d/%m/%Y %H:%M")} (Giờ VN)',
        ])
        if send_telegram(msg):
            print('Gui tong quan tuan OK')
            state['last_weekly_summary'] = week_str
        else:
            print('Loi gui tong quan tuan')

# ── Main ──────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT or not GEMINI_API_KEY:
        print('Thieu bien moi truong: TELEGRAM_TOKEN / TELEGRAM_CHAT / GEMINI_API_KEY')
        return

    now_vn = datetime.now(timezone.utc).astimezone(VN_TZ)
    state  = load_state()
    seen   = set(state.get('seen', []))

    # Gioi han kich thuoc seen (tranh file phong to mai mai)
    if len(seen) > 500:
        seen = set(list(seen)[-300:])

    # Gioi han daily_articles: chi giu 7 ngay gan nhat
    cutoff = (now_vn - timedelta(days=7)).strftime('%Y-%m-%d')
    state['daily_articles'] = [
        a for a in state.get('daily_articles', [])
        if a.get('date', '') >= cutoff
    ]

    print(f'=== Commodity Agent — {now_vn.strftime("%Y-%m-%d %H:%M")} (Gio VN) ===')

    # Thu thap bai moi tu RSS
    new_articles = []
    for source, feed_url in RSS_FEEDS:
        print(f'Doc RSS: {source}...', end=' ', flush=True)
        articles = fetch_rss(feed_url)
        count = 0
        for a in articles:
            aid = article_id(a['title'], a['link'])
            if aid in seen:
                continue
            if not is_commodity_related(a['title'], a['desc']):
                continue
            new_articles.append({**a, 'id': aid, 'source': source})
            count += 1
        print(f'{count} bai moi')

    print(f'Tong cong {len(new_articles)} bai lien quan hang hoa chua xu ly')

    # Phan tich va gui tin
    sent = 0
    today_str = now_vn.strftime('%Y-%m-%d')
    for a in new_articles[:MAX_ARTICLES]:
        print(f'Phan tich: {a["title"][:70]}...', end=' ', flush=True)
        raw = analyze_with_gemini(a['title'], a['desc'])
        if raw == 'QUOTA_EXCEEDED':
            print('Dung do het quota Gemini hom nay.')
            break
        parsed = parse_response(raw)
        seen.add(a['id'])

        if not parsed:
            print('khong lien quan')
            time.sleep(1)
            continue

        muc_do = parsed.get('MUC_DO', 'THAP')
        if muc_do == 'THAP':
            print('muc do THAP, bo qua')
            time.sleep(1)
            continue

        # Luu vao daily_articles de tao tong quan cuoi ngay / cuoi tuan
        state['daily_articles'].append({
            'date':     today_str,
            'tieu_de':  parsed.get('TIEU_DE', a['title']),
            'hang_hoa': parsed.get('HANG_HOA', ''),
            'huong':    parsed.get('HUONG', 'KHONG_RO'),
            'tac_dong': parsed.get('TAC_DONG', ''),
            'muc_do':   muc_do,
        })

        huong        = parsed.get('HUONG', 'KHONG_RO')
        huong_emoji  = '📈' if huong == 'TANG' else ('📉' if huong == 'GIAM' else '〰️')
        muc_do_emoji = '🔴' if muc_do == 'CAO' else '🟡'

        msg = '\n'.join([
            f'{muc_do_emoji} <b>{a["source"]}</b>: {parsed.get("TIEU_DE", a["title"])}',
            '',
            f'🎯 Hàng hóa: <b>{parsed.get("HANG_HOA", "?")}</b>',
            f'{huong_emoji} Hướng giá: <b>{huong}</b>',
            f'📋 {parsed.get("TAC_DONG", "")}',
            '',
            f'🔗 {a["link"]}',
            f'⏱ {now_vn.strftime("%d/%m/%Y %H:%M")} (Giờ VN)',
        ])

        if send_telegram(msg):
            print(f'Telegram OK | {muc_do}')
            sent += 1
        else:
            print('Loi Telegram')
        time.sleep(2)

    # Kiem tra va gui tong quan cuoi ngay / cuoi tuan
    try_send_daily_summary(state, now_vn)
    try_send_weekly_summary(state, now_vn)

    state['seen'] = list(seen)
    save_state(state)
    print(f'\n=== Hoan thanh. Da gui {sent} tin phan tich ===')

if __name__ == '__main__':
    main()
