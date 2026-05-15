#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commodity Supply Chain Agent
- Doc RSS tin tuc the gioi moi 30 phut
- Dung Gemini API phan tich tac dong len hang hoa
- Gui canh bao ngan gon qua Telegram
"""
import json, os, time, hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT',  '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
STATE_FILE     = 'last_commodity_news.json'
VN_TZ          = timezone(timedelta(hours=7))
MAX_ARTICLES   = 2   # So bai phan tich toi da moi lan chay (Gemini free tier: 20 RPD)

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
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {'seen': []}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

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
def analyze_with_gemini(title, desc):
    url = (
        'https://generativelanguage.googleapis.com/v1beta/models/'
        f'gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}'
    )
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

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 250},
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
        if 'candidates' not in data:
            err = data.get('error', {})
            if err.get('code') == 429:
                print(f'  Gemini het quota hom nay (429), dung goi them.')
                return 'QUOTA_EXCEEDED'
            print(f'  Loi Gemini API: {data}')
            return None
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f'  Loi Gemini: {e}')
        return None

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

    # Phan tich va gui canh bao
    sent = 0
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

        huong        = parsed.get('HUONG', 'KHONG_RO')
        huong_emoji  = '📈' if huong == 'TANG' else ('📉' if huong == 'GIAM' else '〰️')
        muc_do_emoji = '🔴' if muc_do == 'CAO' else '🟡'

        msg = '\n'.join([
            f'{muc_do_emoji} <b>CẢNH BÁO HÀNG HÓA — {muc_do}</b>',
            '',
            f'📰 <b>{a["source"]}</b>: {parsed.get("TIEU_DE", a["title"])}',
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

    state['seen'] = list(seen)
    save_state(state)
    print(f'\n=== Hoan thanh. Da gui {sent} canh bao ===')

if __name__ == '__main__':
    main()
