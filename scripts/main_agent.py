#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Market Intelligence Agent
Kết hợp 2 mảng trong cùng 1 kênh Telegram — báo cáo tách biệt, cùng env:

  🛢️  Giao Dịch Hàng Hóa  : 07:00 (Phiên Á) + 20:00 (Phiên Mỹ)
  🏦  Ngân Hàng & BĐS VN  : 17:00 (sau phiên giao dịch Việt Nam)
  🗓  Tổng kết tuần        : Thứ 6 sau 20:00 (cả 2 mảng)

Biến môi trường cần thiết (đặt trong .env):
  GEMINI_API_KEY   — bắt buộc
  TELEGRAM_TOKEN   — bắt buộc
  TELEGRAM_CHAT    — bắt buộc
"""
import html as _html
import json, os, hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from market_data import fetch_cftc_cot

# ── Cấu hình chung ────────────────────────────────────────────────────────────
_ROOT          = Path(__file__).parent.parent
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT', '')
OUTPUT_DIR     = _ROOT / 'outputs'
VN_TZ          = timezone(timedelta(hours=7))

COMMODITY_STATE_FILE = str(_ROOT / 'data' / 'last_commodity_news.json')
BANKING_STATE_FILE   = str(_ROOT / 'data' / 'last_banking_news.json')

# Giờ gửi báo cáo (giờ VN)
COMMODITY_MORNING_HOUR = 7   # 07:00 — trước phiên Á
COMMODITY_EVENING_HOUR = 20  # 20:00 — trước phiên Mỹ
BANKING_DAILY_HOUR     = 17  # 17:00 — sau phiên giao dịch VN
MAX_ARTICLES           = 40  # tối đa bài đưa vào mỗi báo cáo

# ══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def article_id(title, link):
    return hashlib.md5(f'{title}{link}'.encode()).hexdigest()[:12]

def fetch_rss(url, unescape=False):
    try:
        # timeout 20s: feed Sputnik VN ~140KB phan hoi cham, 10s hay bi timeout
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(r.content)
        items = []
        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            link  = item.findtext('link',  '').strip()
            desc  = item.findtext('description', '').strip()
            if unescape:
                title = _html.unescape(title)
                desc  = _html.unescape(desc)
            if title:
                items.append({'title': title, 'link': link, 'desc': desc[:400]})
        return items
    except Exception as e:
        print(f'  Lỗi RSS {url}: {e}')
        return []

def call_gemini(prompt, max_tokens=1600):
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

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    if len(msg) > 4000:
        msg = msg[:3950] + '\n\n[...xem đầy đủ trong outputs/]'
    try:
        r = requests.post(
            url,
            json={'chat_id': TELEGRAM_CHAT, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10,
        )
        return r.json().get('ok', False)
    except Exception:
        return False

def save_output(content, filename):
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    path.write_text(content, encoding='utf-8')
    print(f'  Lưu → outputs/{filename}')
    return path

def load_state(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {k: (v.copy() if isinstance(v, list) else v) for k, v in default.items()}

def save_state(filepath, state):
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# ══════════════════════════════════════════════════════════════════════════════
# MẢNG 1 — GIAO DỊCH HÀNG HÓA QUỐC TẾ
# ══════════════════════════════════════════════════════════════════════════════

COMMODITY_FEEDS = [
    # ── Tin tức tổng hợp ──────────────────────────────────────────────────────
    ('MarketWatch',         'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ('BBC Business',        'http://feeds.bbci.co.uk/news/business/rss.xml'),
    ('AP Business',         'https://feeds.apnews.com/rss/apf-business'),
    ('The Guardian Biz',    'https://www.theguardian.com/business/rss'),
    ('Al Jazeera',          'https://www.aljazeera.com/xml/rss/all.xml'),
    ('CNBC Commodities',    'https://www.cnbc.com/id/10000664/device/rss/rss.html'),
    ('OilPrice.com',        'https://oilprice.com/rss/main'),
    ('Mining.com',          'https://www.mining.com/feed/'),
    # ── Nguồn thẩm quyền (EIA / IMF / WGC) ──────────────────────────────────
    # EIA Today in Energy: phân tích tồn kho dầu, sản lượng, rig count hàng ngày
    ('EIA Today in Energy', 'https://www.eia.gov/todayinenergy/rss/todayinenergy.xml'),
    # IMF Blog: vĩ mô toàn cầu ảnh hưởng đến dòng tiền và giá hàng hóa
    ('IMF Blog',            'https://www.imf.org/en/blogs/rss'),
    # World Gold Council: cầu vàng, ETF flows, mua vàng của NHTW
    ('WGC Gold Insights',   'https://www.gold.org/goldhub/rss/research'),
]

COMMODITY_KEYWORDS = [
    # ── Năng lượng (EIA / IEA / OPEC) ────────────────────────────────────────
    'oil', 'crude', 'opec', 'petroleum', 'gas', 'lng', 'fuel', 'brent', 'wti',
    'eia report', 'petroleum status', 'crude inventory', 'crude stocks', 'oil stocks',
    'refinery', 'rig count', 'production cut', 'output quota', 'iea', 'opec+',
    'natural gas storage', 'heating oil', 'gasoline',
    # ── Kim loại quý (WGC / LBMA) ─────────────────────────────────────────────
    'gold', 'silver', 'platinum', 'palladium',
    'gold demand', 'central bank gold', 'etf flows', 'etf inflow', 'etf outflow',
    'safe haven', 'xau', 'comex gold',
    # ── Kim loại công nghiệp (ICSG / LME) ────────────────────────────────────
    'copper', 'aluminum', 'steel', 'iron', 'nickel', 'zinc', 'lead', 'tin',
    'copper deficit', 'copper surplus', 'base metals', 'lme',
    # ── Nông sản (USDA WASDE / FAO / AMIS) ───────────────────────────────────
    'wheat', 'corn', 'soybean', 'rice', 'coffee', 'sugar', 'cotton', 'cocoa',
    'wasde', 'crop progress', 'ending stocks', 'world supply', 'crop condition',
    'planting progress', 'harvest progress', 'usda report', 'crop yield',
    'la nina', 'el nino', 'drought', 'flood', 'growing season',
    # ── Vĩ mô & Dòng tiền (CFTC / FRED / IMF / World Bank) ──────────────────
    'commodity', 'commodities', 'supply chain', 'tariff', 'sanction',
    'trade war', 'shortage', 'export ban', 'freight', 'shipping', 'embargo',
    'inflation', 'fed rate', 'dollar index', 'dxy', 'treasury', 'china economy', 'gdp',
    'fomc', 'real yield', 'treasury yield', 'risk off', 'risk on',
    'cot report', 'speculative position', 'net long', 'net short',
    'imf', 'world bank', 'inventory build', 'inventory draw', 'stockpile',
]

COMMODITY_STATE_DEFAULT = {
    'seen': [],
    'pending_articles': [],
    'last_morning_report': '',
    'last_evening_report': '',
    'last_weekly_summary': '',
    'weekly_reports': [],
}

def collect_commodity(state, now_vn):
    seen = set(state.get('seen', []))
    if len(seen) > 500:
        seen = set(list(seen)[-300:])

    cutoff = (now_vn - timedelta(hours=48)).strftime('%Y-%m-%d %H:%M')
    state['pending_articles'] = [
        a for a in state.get('pending_articles', [])
        if a.get('collected_at', '') >= cutoff
    ]

    new_count = 0
    for source, url in COMMODITY_FEEDS:
        print(f'  [Hàng hóa] {source}...', end=' ', flush=True)
        articles = fetch_rss(url)
        count = 0
        for a in articles:
            aid = article_id(a['title'], a['link'])
            if aid in seen:
                continue
            text = (a['title'] + ' ' + a['desc']).lower()
            if not any(kw in text for kw in COMMODITY_KEYWORDS):
                continue
            seen.add(aid)
            state['pending_articles'].append({
                'id': aid, 'source': source,
                'title': a['title'], 'desc': a['desc'],
                'collected_at': now_vn.strftime('%Y-%m-%d %H:%M'),
            })
            count += 1
            new_count += 1
        print(f'{count} mới')

    state['seen'] = list(seen)
    print(f'  [Hàng hóa] +{new_count} mới | Tổng pending: {len(state["pending_articles"])}')
    return state

def _commodity_report_prompt(articles, session, date_str, market_context=None):
    articles_text = '\n'.join([
        f'{i+1}. [{a["source"]}] {a["title"]}\n   {a["desc"][:300]}'
        for i, a in enumerate(articles[:MAX_ARTICLES])
    ])
    context    = 'tin tức qua đêm và đầu phiên Á' if session == 'morning' else 'tin tức trong ngày và đầu phiên Mỹ'
    session_vn = 'PHIÊN SÁ (07:00 VN)' if session == 'morning' else 'PHIÊN MỸ (20:00 VN)'

    # Khối dữ liệu CFTC COT (nếu có) — inject trước articles để Gemini dùng làm context
    cot_block = f'\n{market_context}\n' if market_context else ''

    return f"""Bạn là chuyên gia phân tích thị trường hàng hóa toàn cầu với kinh nghiệm giao dịch thực tế.
{cot_block}
Dưới đây là {len(articles)} {context} ngày {date_str}:

{articles_text}

Khi phân tích, áp dụng khung đa tầng:
• Dòng tiền & Vị thế: nếu có dữ liệu COT, kiểm tra xem vị thế đầu cơ xác nhận hay phản bác xu hướng tin tức. NET LONG tăng mạnh = dòng tiền vào, NET SHORT tăng = phân phối.
• Tồn kho: khi bài viết đề cập inventory/stockpile, so sánh ngầm với mức bình thường theo mùa vụ — lệch hơn 2 độ lệch chuẩn so với trung bình 5 năm thường là cơ hội trading lớn.
• Cung-Cầu thực: ưu tiên số liệu từ EIA (dầu), USDA WASDE (nông sản), WGC (vàng) hơn ý kiến chuyên gia.

Viết BÁO CÁO PHÂN TÍCH {session_vn} bằng TIẾNG VIỆT theo đúng cấu trúc sau (không thêm gì ngoài cấu trúc):

🌍 VĨ MÔ & DÒNG TIỀN
[Tóm tắt 2-3 yếu tố vĩ mô/địa chính trị quan trọng nhất; nếu có dữ liệu COT thì tích hợp nhận xét về vị thế đầu cơ]

🛢️ NĂNG LƯỢNG — Dầu WTI/Brent, Khí tự nhiên
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: Hỗ trợ [...] | Kháng cự [...]
Phân tích: [2-3 câu dựa trên tin tức; đề cập tồn kho EIA nếu có]
Rủi ro: [rủi ro chính]

🥇 KIM LOẠI QUÝ — Vàng (XAU/USD), Bạc
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: Hỗ trợ [...] | Kháng cự [...]
Phân tích: [2-3 câu; đề cập ETF flows/NHTW mua vàng nếu có]
Rủi ro: [rủi ro chính]

🌾 NÔNG SẢN — Ngô, Đậu tương, Lúa mì
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: [mức giá quan trọng nếu có trong tin]
Phân tích: [2-3 câu; đề cập WASDE/tiến độ mùa vụ nếu có]
Rủi ro: [rủi ro chính]

🔩 KIM LOẠI CÔNG NGHIỆP — Đồng, Nhôm, Niken
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: [mức giá quan trọng nếu có trong tin]
Phân tích: [2-3 câu; đề cập cán cân cung-cầu LME nếu có]
Rủi ro: [rủi ro chính]

📋 KHUYẾN NGHỊ PHIÊN
[2-3 khuyến nghị cụ thể, actionable cho phiên giao dịch này]

⚠️ THEO DÕI PHIÊN
[2-3 sự kiện/dữ liệu quan trọng cần theo dõi — ưu tiên lịch phát hành EIA/USDA/OPEC nếu có]

Lưu ý: Nếu không đủ tin về một nhóm, đánh giá dựa trên bối cảnh thị trường chung."""

def send_commodity_session_report(state, now_vn, session):
    today = now_vn.strftime('%Y-%m-%d')
    key   = f'last_{session}_report'
    if state.get(key) == today:
        return
    if session == 'morning' and now_vn.hour < COMMODITY_MORNING_HOUR:
        return
    if session == 'evening' and now_vn.hour < COMMODITY_EVENING_HOUR:
        return

    articles   = state.get('pending_articles', [])
    session_vn = 'SÁNG (Phiên Á)' if session == 'morning' else 'CHIỀU (Phiên Mỹ)'
    emoji      = '🌅' if session == 'morning' else '🌆'

    print(f'\n[Hàng hóa] Tạo báo cáo {session_vn} ({len(articles)} tin tích lũy)...')
    if not articles:
        print('[Hàng hóa] Không có tin, đánh dấu đã gửi.')
        state[key] = today
        return

    # Lấy dữ liệu CFTC COT để enrichment prompt (graceful fallback nếu lỗi)
    print('  [COT] Đang lấy dữ liệu vị thế CFTC...', end=' ', flush=True)
    cot_context = fetch_cftc_cot()
    print('OK' if cot_context else 'Bỏ qua (không kết nối được)')

    text = call_gemini(_commodity_report_prompt(articles, session, today, cot_context))
    if text == 'QUOTA_EXCEEDED':
        return
    if not text:
        return

    header = (
        f'{emoji} <b>HÀNG HÓA — BÁO CÁO {session_vn.upper()}</b>\n'
        f'{now_vn.strftime("%d/%m/%Y")} | 📰 {min(len(articles), MAX_ARTICLES)} tin | '
        f'⏱ {now_vn.strftime("%H:%M")} (Giờ VN)\n'
        f'{"─" * 35}\n\n'
    )
    if send_telegram(header + text):
        print(f'[Hàng hóa] Telegram OK — báo cáo {session_vn}')
        state[key] = today
        save_output(text, f'report_{today}_{session}.txt')
        state.setdefault('weekly_reports', []).append(
            {'date': today, 'session': session, 'summary': text[:700]}
        )
        state['weekly_reports'] = state['weekly_reports'][-14:]
        # Xóa pending khi cả 2 báo cáo trong ngày đã gửi
        other = 'last_evening_report' if session == 'morning' else 'last_morning_report'
        if state.get(other) == today:
            state['pending_articles'] = []
            print('[Hàng hóa] Cả 2 báo cáo đã gửi → xóa pending')
    else:
        print(f'[Hàng hóa] Lỗi Telegram')

def send_commodity_weekly(state, now_vn):
    if now_vn.weekday() != 4 or now_vn.hour < COMMODITY_EVENING_HOUR:
        return
    week = now_vn.strftime('%Y-W%W')
    if state.get('last_weekly_summary') == week:
        return
    reports = state.get('weekly_reports', [])
    if not reports:
        state['last_weekly_summary'] = week
        return

    reports_text = '\n\n'.join([
        f'--- {r["date"]} ({r["session"]}) ---\n{r["summary"]}'
        for r in reports[-14:]
    ])
    prompt = f"""Tổng kết thị trường hàng hóa quốc tế tuần {week} từ các báo cáo phiên:

{reports_text}

Viết BÁO CÁO TỔNG KẾT TUẦN HÀNG HÓA bằng TIẾNG VIỆT:
1. Sự kiện & xu hướng nổi bật nhất tuần (3-4 điểm)
2. Hiệu suất từng nhóm: Năng lượng, Kim loại quý, Nông sản, Kim loại công nghiệp
3. Yếu tố rủi ro lớn nhất tuần tới
4. Dự báo xu hướng ngắn hạn theo nhóm

Khoảng 250-300 từ, chuyên nghiệp. KHÔNG thêm lời dẫn hay kết luận thừa."""
    print('\n[Hàng hóa] Tạo tổng kết tuần...')
    text = call_gemini(prompt, max_tokens=1200)
    if text and text != 'QUOTA_EXCEEDED':
        msg = (
            f'🗓 <b>HÀNG HÓA — TỔNG KẾT TUẦN {week}</b>\n\n'
            f'{text}\n\n'
            f'⏱ {now_vn.strftime("%d/%m/%Y %H:%M")} (Giờ VN)'
        )
        if send_telegram(msg):
            print('[Hàng hóa] Tổng kết tuần OK')
            state['last_weekly_summary'] = week
            save_output(text, f'report_{now_vn.strftime("%Y-%m-%d")}_weekly_commodity.txt')

# ══════════════════════════════════════════════════════════════════════════════
# MẢNG 2 — NGÂN HÀNG & BĐS PHÍA NAM VIỆT NAM
# ══════════════════════════════════════════════════════════════════════════════

BANKING_FEEDS = [
    ('VnExpress Kinh tế', 'https://vnexpress.net/rss/kinh-doanh.rss'),
    ('VnExpress BĐS',     'https://vnexpress.net/rss/bat-dong-san.rss'),
    ('Thanh Niên KT',     'https://thanhnien.vn/rss/kinh-te.rss'),
    ('VietnamNet KT',     'https://vietnamnet.vn/rss/kinh-doanh.rss'),
    ('VOV Kinh tế',       'https://vov.vn/rss/kinh-te.rss'),
    # Sputnik VN: state media Nga ban tieng Viet — goc nhin ben ngoai de doi
    # chieu voi bao trong nuoc; prompt bao cao se danh gia xung dot nguon
    ('Sputnik VN (Nga)',  'https://sputniknews.vn/export/rss2/archive/index.xml'),
]

BANKING_KEYWORDS = [
    # Lãi suất & tín dụng
    'lãi suất', 'lãi vay', 'tiền gửi', 'huy động vốn', 'kỳ hạn',
    'lãi huy động', 'lãi cho vay', 'tín dụng', 'room tín dụng', 'hạn mức',
    'tăng trưởng tín dụng', 'siết tín dụng', 'nới tín dụng',
    'chính sách tiền tệ', 'nhnn', 'ngân hàng nhà nước',
    # Ngân hàng thương mại
    'ngân hàng', 'bidv', 'vietcombank', 'vietinbank', 'agribank',
    'techcombank', 'vpbank', 'mbbank', 'acb', 'sacombank', 'tpbank',
    'shb', 'hdbank', 'ocb', 'seabank', 'vib', 'lpbank', 'msb',
    'nam a bank', 'eximbank', 'kienlongbank',
    # Rủi ro tài chính
    'thanh khoản', 'nợ xấu', 'tỷ giá', 'dự trữ bắt buộc',
    # BĐS
    'bất động sản', 'bds', 'nhà đất', 'căn hộ', 'chung cư',
    'đất nền', 'khu công nghiệp', 'nhà ở xã hội',
    'vay mua nhà', 'vay bất động sản', 'thị trường nhà', 'phân khúc',
    # Khu vực phía Nam
    'tp.hcm', 'tp hcm', 'hồ chí minh', 'bình dương', 'đồng nai',
    'long an', 'bà rịa', 'vũng tàu', 'phía nam',
]

BANKING_STATE_DEFAULT = {
    'seen': [],
    'pending_articles': [],
    'last_daily_report': '',
    'last_weekly_summary': '',
    'weekly_reports': [],
}

def collect_banking(state, now_vn):
    seen = set(state.get('seen', []))
    if len(seen) > 500:
        seen = set(list(seen)[-300:])

    cutoff = (now_vn - timedelta(hours=48)).strftime('%Y-%m-%d %H:%M')
    state['pending_articles'] = [
        a for a in state.get('pending_articles', [])
        if a.get('collected_at', '') >= cutoff
    ]

    new_count = 0
    for source, url in BANKING_FEEDS:
        print(f'  [Ngân hàng] {source}...', end=' ', flush=True)
        articles = fetch_rss(url, unescape=True)
        count = 0
        for a in articles:
            aid = article_id(a['title'], a['link'])
            if aid in seen:
                continue
            text = (a['title'] + ' ' + a['desc']).lower()
            if not any(kw in text for kw in BANKING_KEYWORDS):
                continue
            seen.add(aid)
            state['pending_articles'].append({
                'id': aid, 'source': source,
                'title': a['title'], 'desc': a['desc'],
                'link': a.get('link', ''),
                'collected_at': now_vn.strftime('%Y-%m-%d %H:%M'),
            })
            count += 1
            new_count += 1
        print(f'{count} mới')

    state['seen'] = list(seen)
    print(f'  [Ngân hàng] +{new_count} mới | Tổng pending: {len(state["pending_articles"])}')
    return state

def _banking_report_prompt(articles, date_str):
    articles_text = '\n'.join([
        f'{i+1}. [{a["source"]}] {a["title"]}\n   {a["desc"][:300]}'
        for i, a in enumerate(articles[:MAX_ARTICLES])
    ])
    return f"""Bạn là chuyên gia phân tích thị trường ngân hàng và bất động sản Việt Nam, tập trung khu vực phía Nam (TP.HCM, Bình Dương, Đồng Nai, Long An, Bà Rịa-Vũng Tàu).

Dưới đây là {len(articles)} tin tức ngày {date_str}:

{articles_text}

Viết BÁO CÁO NGÂN HÀNG & BĐS PHÍA NAM bằng TIẾNG VIỆT theo đúng cấu trúc (không thêm gì ngoài cấu trúc):

💰 LÃI SUẤT & CHÍNH SÁCH TIỀN TỆ
Xu hướng: [TĂNG / GIẢM / ỔN ĐỊNH]
Phân tích: [2-3 câu về diễn biến lãi suất và chính sách NHNN]
Tác động NĐT: [ý nghĩa thực tế với nhà đầu tư BĐS phía Nam]

🏗️ BĐS PHÍA NAM — TP.HCM, Bình Dương, Đồng Nai, Long An
Tín dụng BĐS: [NỚI LỎNG / THẮT CHẶT / KHÔNG ĐỔI]
Tín hiệu: [MUA VỀ / GIỮ/CHỜ / CHỜ ĐỢI]
Phân tích: [2-3 câu về thị trường BĐS phía Nam hôm nay]
Rủi ro: [rủi ro chính cần theo dõi]

🏦 CÁC NGÂN HÀNG NỔI BẬT
[3-4 điểm cụ thể: lãi suất ghi nhận, chính sách tín dụng mới, thay đổi đáng chú ý]

📋 KHUYẾN NGHỊ NHÀ ĐẦU TƯ BĐS PHÍA NAM
[2-3 khuyến nghị cụ thể, actionable dựa trên tin tức hôm nay]

🔀 ĐỐI CHIẾU NGUỒN TIN
[Nguồn "Sputnik VN (Nga)" là state media Nga bản tiếng Việt — góc nhìn bên ngoài, KHÔNG mặc định là sự thật khách quan. Nếu Sputnik VN và báo trong nước (VnExpress/Thanh Niên/VietnamNet/VOV) đưa tin TRÁI NGƯỢC hoặc nhấn mạnh khác hẳn nhau về cùng chủ đề kinh tế VN, nêu rõ "Nguồn A nói X, nguồn B nói Y" + đánh giá bên nào có căn cứ hơn. Nếu không có xung đột, ghi đúng 1 câu: "Không phát hiện xung đột đáng kể giữa các nguồn."]

⚠️ THEO DÕI & RỦI RO
[2-3 điểm cần chú ý trong thời gian tới]

Viết ngắn gọn, chuyên nghiệp, thực tiễn. KHÔNG thêm lời dẫn hay kết luận thừa."""

def _generate_banking_html(synthesis_text, articles, date_str, now_vn):
    article_rows = ''.join([
        f'<li><a href="{a.get("link","#")}" target="_blank">{a.get("title","")}</a>'
        f' <span class="src">— {a.get("source","")}</span></li>\n'
        for a in articles[:MAX_ARTICLES]
    ])
    analysis_html = synthesis_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    analysis_html = analysis_html.replace('\n\n', '</p><p>').replace('\n', '<br>')

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ngân hàng &amp; BĐS Phía Nam — {date_str}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', system-ui, Arial, sans-serif; background: #f0f2f5; color: #2c3e50; line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, #1a3a5c 0%, #2471a3 100%); color: white; padding: 22px 32px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.header .sub {{ font-size: 13px; opacity: 0.8; margin-top: 5px; }}
.container {{ max-width: 900px; margin: 0 auto; padding: 18px 16px; }}
.section {{ background: white; border-radius: 10px; padding: 22px 24px; margin-bottom: 14px; box-shadow: 0 1px 6px rgba(0,0,0,.08); }}
.section h2 {{ font-size: 14px; font-weight: 700; color: #1a3a5c; border-bottom: 2px solid #eaf2fb; padding-bottom: 10px; margin-bottom: 14px; }}
.analysis p {{ margin-bottom: 10px; font-size: 14px; color: #34495e; line-height: 1.8; }}
.news-list {{ list-style: none; padding: 0; }}
.news-list li {{ padding: 8px 0; border-bottom: 1px solid #f2f5f8; font-size: 13px; }}
.news-list li:last-child {{ border-bottom: none; }}
.news-list a {{ color: #2471a3; text-decoration: none; font-weight: 500; }}
.news-list a:hover {{ text-decoration: underline; }}
.src {{ color: #95a5a6; font-size: 11px; }}
.footer {{ text-align: center; font-size: 12px; color: #aab0b6; padding: 14px 0 20px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🏦 Ngân hàng &amp; BĐS Phía Nam — {now_vn.strftime("%d/%m/%Y")}</h1>
  <div class="sub">Cập nhật: {now_vn.strftime("%H:%M")} &nbsp;|&nbsp; {len(articles)} tin tổng hợp &nbsp;|&nbsp; TP.HCM · Bình Dương · Đồng Nai · Long An · Bà Rịa-Vũng Tàu</div>
</div>
<div class="container">
  <div class="section">
    <h2>📊 Phân tích Tổng quan</h2>
    <div class="analysis"><p>{analysis_html}</p></div>
  </div>
  <div class="section">
    <h2>📰 Tin tức tổng hợp ({len(articles)} bài)</h2>
    <ul class="news-list">
{article_rows}    </ul>
  </div>
</div>
<div class="footer">
  Báo cáo tự động &nbsp;|&nbsp; Nguồn: VnExpress · Thanh Niên · VietnamNet · VOV &nbsp;|&nbsp; Phân tích: Gemini AI<br>
  {now_vn.strftime("%H:%M:%S %d/%m/%Y")} (Giờ VN)
</div>
</body>
</html>"""

def send_banking_daily_report(state, now_vn):
    today = now_vn.strftime('%Y-%m-%d')
    if state.get('last_daily_report') == today:
        return
    if now_vn.hour < BANKING_DAILY_HOUR:
        return

    articles = state.get('pending_articles', [])
    print(f'\n[Ngân hàng] Tạo báo cáo ngày ({len(articles)} tin tích lũy)...')
    if not articles:
        print('[Ngân hàng] Không có tin, đánh dấu đã gửi.')
        state['last_daily_report'] = today
        return

    text = call_gemini(_banking_report_prompt(articles, today))
    if text == 'QUOTA_EXCEEDED':
        return
    if not text:
        return

    header = (
        f'🏦 <b>NGÂN HÀNG &amp; BĐS PHÍA NAM — {now_vn.strftime("%d/%m/%Y")}</b>\n'
        f'📰 Tổng hợp {min(len(articles), MAX_ARTICLES)} tin | ⏱ {now_vn.strftime("%H:%M")} (Giờ VN)\n'
        f'{"─" * 35}\n\n'
    )
    if send_telegram(header + text):
        print('[Ngân hàng] Telegram OK — báo cáo ngày')
        state['last_daily_report'] = today
        # Lưu HTML và TXT
        html_content = _generate_banking_html(text, articles, today, now_vn)
        save_output(html_content, f'banking_{today}.html')
        save_output(text, f'banking_{today}.txt')
        # Lưu cho weekly
        state.setdefault('weekly_reports', []).append(
            {'date': today, 'summary': text[:700]}
        )
        state['weekly_reports'] = state['weekly_reports'][-14:]
        # Xóa pending sau khi gửi
        state['pending_articles'] = []
    else:
        print('[Ngân hàng] Lỗi Telegram')

def send_banking_weekly(state, now_vn):
    if now_vn.weekday() != 4 or now_vn.hour < COMMODITY_EVENING_HOUR:
        return
    week = now_vn.strftime('%Y-W%W')
    if state.get('last_weekly_summary') == week:
        return
    reports = state.get('weekly_reports', [])
    if not reports:
        state['last_weekly_summary'] = week
        return

    reports_text = '\n\n'.join([
        f'--- {r["date"]} ---\n{r["summary"]}'
        for r in reports[-7:]
    ])
    prompt = f"""Tổng kết thị trường ngân hàng và BĐS Việt Nam tuần {week}:

{reports_text}

Viết BÁO CÁO TỔNG KẾT TUẦN NGÂN HÀNG & BĐS bằng TIẾNG VIỆT:
1. Diễn biến lãi suất và chính sách NHNN trong tuần
2. Tình hình tín dụng BĐS và thị trường nhà đất phía Nam
3. Điểm đáng chú ý về các ngân hàng lớn
4. Triển vọng và rủi ro tuần tới

Khoảng 200-250 từ, chuyên nghiệp. KHÔNG thêm lời dẫn hay kết luận thừa."""
    print('\n[Ngân hàng] Tạo tổng kết tuần...')
    text = call_gemini(prompt, max_tokens=1000)
    if text and text != 'QUOTA_EXCEEDED':
        msg = (
            f'🗓 <b>NGÂN HÀNG &amp; BĐS — TỔNG KẾT TUẦN {week}</b>\n\n'
            f'{text}\n\n'
            f'⏱ {now_vn.strftime("%d/%m/%Y %H:%M")} (Giờ VN)'
        )
        if send_telegram(msg):
            print('[Ngân hàng] Tổng kết tuần OK')
            state['last_weekly_summary'] = week
            save_output(text, f'banking_{now_vn.strftime("%Y-%m-%d")}_weekly.txt')

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if not GEMINI_API_KEY:
        print('Thiếu GEMINI_API_KEY')
        return
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print('Thiếu TELEGRAM_TOKEN hoặc TELEGRAM_CHAT')
        return

    # --banking-only: chi chay mang Ngan Hang & BDS. Dung trong GitHub Actions
    # (workflow chay commodity_agent.py rieng — ban co FRED/quant moi hon
    # phan commodity trong file nay; chay ca hai se trung tin + hong state)
    banking_only = '--banking-only' in sys.argv

    now_vn = datetime.now(timezone.utc).astimezone(VN_TZ)
    print(f'=== Unified Market Agent — {now_vn.strftime("%Y-%m-%d %H:%M")} (Giờ VN) ===')

    if not banking_only:
        # ── Mảng 1: Giao Dịch Hàng Hóa ───────────────────────────────────────
        print('\n── Hàng Hóa Quốc Tế ─────────────────────────────────────────────')
        c_state = load_state(COMMODITY_STATE_FILE, COMMODITY_STATE_DEFAULT)
        c_state['weekly_reports'] = c_state.get('weekly_reports', [])[-14:]
        collect_commodity(c_state, now_vn)
        send_commodity_session_report(c_state, now_vn, 'morning')
        send_commodity_session_report(c_state, now_vn, 'evening')
        send_commodity_weekly(c_state, now_vn)
        save_state(COMMODITY_STATE_FILE, c_state)

    # ── Mảng 2: Ngân Hàng & BĐS ───────────────────────────────────────────────
    print('\n── Ngân Hàng & BĐS Phía Nam ─────────────────────────────────────')
    b_state = load_state(BANKING_STATE_FILE, BANKING_STATE_DEFAULT)
    b_state['weekly_reports'] = b_state.get('weekly_reports', [])[-14:]
    collect_banking(b_state, now_vn)
    send_banking_daily_report(b_state, now_vn)
    send_banking_weekly(b_state, now_vn)
    save_state(BANKING_STATE_FILE, b_state)

    print('\n=== Hoàn thành ===')

if __name__ == '__main__':
    main()
