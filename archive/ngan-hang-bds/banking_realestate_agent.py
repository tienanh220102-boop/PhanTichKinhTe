#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Banking & Real Estate Intelligence Agent — Phía Nam Việt Nam
Kế thừa kiến trúc từ Giao Dịch Hàng Hóa/commodity_agent.py

- Thu thập RSS từ CafeF, VnExpress, Thanh Niên, VietnamNet
- Phân tích Gemini AI: lãi suất, tín dụng BĐS, tác động thị trường phía Nam
- Xuất báo cáo HTML hàng ngày cho nhà đầu tư BĐS

Biến môi trường cần thiết:
  GEMINI_API_KEY   — Bắt buộc
  TELEGRAM_TOKEN   — Tuỳ chọn (gửi tóm tắt qua Telegram)
  TELEGRAM_CHAT    — Tuỳ chọn (chat_id Telegram)
"""
import json, os, time, hashlib, html
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Cấu hình ──────────────────────────────────────────────────
_ROOT           = Path(__file__).parent.parent          # project root (scripts/ → ..)
GEMINI_API_KEY  = os.environ.get('GEMINI_API_KEY', '')
TELEGRAM_TOKEN  = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT   = os.environ.get('TELEGRAM_CHAT', '')
STATE_FILE      = str(_ROOT / 'data' / 'last_banking_news.json')
REPORT_DIR      = _ROOT / 'outputs'
VN_TZ           = timezone(timedelta(hours=7))
MAX_ARTICLES    = 5   # Gemini free tier: 20 RPD
DAILY_REPORT_HOUR = 17  # Tạo báo cáo tổng quan lúc 17:00 VN

RSS_FEEDS = [
    # Đã kiểm tra hoạt động 06/2026
    ('VnExpress Kinh tế', 'https://vnexpress.net/rss/kinh-doanh.rss'),
    ('VnExpress BĐS',     'https://vnexpress.net/rss/bat-dong-san.rss'),
    ('Thanh Niên KT',     'https://thanhnien.vn/rss/kinh-te.rss'),
    ('VietnamNet KT',     'https://vietnamnet.vn/rss/kinh-doanh.rss'),
    ('VOV Kinh tế',       'https://vov.vn/rss/kinh-te.rss'),
]

BANKING_KEYWORDS = [
    # Lãi suất
    'lãi suất', 'lai suat', 'lãi vay', 'tiền gửi', 'huy động vốn',
    'kỳ hạn', 'lãi huy động', 'lãi tiền gửi', 'lãi cho vay',
    # Tín dụng & chính sách
    'tín dụng', 'tin dung', 'room', 'hạn mức', 'tăng trưởng tín dụng',
    'siết tín dụng', 'nới tín dụng', 'thắt chặt', 'nới lỏng',
    'chính sách tiền tệ', 'nhnn', 'ngân hàng nhà nước',
    # Ngân hàng thương mại
    'ngân hàng', 'ngan hang', 'bidv', 'vietcombank', 'vietinbank',
    'agribank', 'techcombank', 'vpbank', 'mbbank', 'acb', 'sacombank',
    'tpbank', 'shb', 'hdbank', 'ocb', 'seabank', 'vib', 'lpbank',
    'msb', 'nam a bank', 'eximbank', 'kienlongbank',
    # Thanh khoản & rủi ro
    'thanh khoản', 'nợ xấu', 'tỷ giá', 'dự trữ bắt buộc',
    # BĐS
    'bất động sản', 'bat dong san', 'bds', 'nhà đất', 'căn hộ', 'chung cư',
    'đất nền', 'khu công nghiệp', 'nhà ở xã hội', 'vay mua nhà',
    'vay bất động sản', 'thị trường nhà', 'phân khúc',
    # Khu vực phía Nam
    'tp.hcm', 'tp hcm', 'hồ chí minh', 'bình dương', 'đồng nai',
    'long an', 'bà rịa', 'vũng tàu', 'phía nam', 'tây ninh',
]

# ── State ──────────────────────────────────────────────────────
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
        'last_daily_report': '',
    }

def save_state(state):
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def article_id(title, link):
    return hashlib.md5(f'{title}{link}'.encode()).hexdigest()[:12]

# ── RSS ────────────────────────────────────────────────────────
def fetch_rss(url):
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(r.content)
        articles = []
        for item in list(root.iter('item'))[:100]:  # giới hạn 100 bài mới nhất mỗi nguồn
            title = html.unescape(item.findtext('title', '')).strip()
            link  = item.findtext('link', '').strip()
            desc  = html.unescape(item.findtext('description', '')).strip()
            if title:
                articles.append({'title': title, 'link': link, 'desc': desc[:400]})
        return articles
    except Exception as e:
        print(f'  Loi RSS {url}: {e}')
        return []

def is_relevant(title, desc):
    text = (title + ' ' + desc).lower()
    return any(kw in text for kw in BANKING_KEYWORDS)

# ── Gemini ─────────────────────────────────────────────────────
def call_gemini(prompt, max_tokens=300):
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
                print('  Gemini het quota hom nay (429).')
                return 'QUOTA_EXCEEDED'
            print(f'  Loi Gemini: {data}')
            return None
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f'  Loi Gemini: {e}')
        return None

def analyze_article(title, desc):
    prompt = f"""Bạn là chuyên gia phân tích ngân hàng và bất động sản Việt Nam.
Phân tích tin tức sau và đánh giá tác động đến nhà đầu tư BĐS khu vực phía Nam
(TP.HCM, Bình Dương, Đồng Nai, Long An, Bà Rịa-Vũng Tàu):

Tiêu đề: {title}
Nội dung: {desc}

Trả lời ĐÚNG định dạng sau (không thêm gì khác ngoài 7 dòng):
TIEU_DE: [tóm tắt tiêu đề rõ ràng bằng tiếng Việt]
LOAI: [NGAN_HANG / BAT_DONG_SAN / CHINH_SACH / KINH_TE]
LAI_SUAT: [TANG / GIAM / ON_DINH / KHONG_LIEN_QUAN]
TIN_DUNG_BDS: [NOI_LONG / THAT_CHAT / KHONG_DOI / KHONG_LIEN_QUAN]
MUC_DO: [CAO / TRUNG_BINH / THAP]
TAC_DONG: [1 câu ngắn: tác động thực tế đến NĐT BĐS phía Nam]
KHUYEN_NGHI: [MUA_VE / GIU_CHO / CHO_DOI / KHONG_RO]

Nếu tin KHÔNG liên quan đến ngân hàng hoặc BĐS Việt Nam, chỉ trả lời: KHONG_LIEN_QUAN"""
    return call_gemini(prompt, max_tokens=300)

def parse_article_response(text):
    if not text or 'KHONG_LIEN_QUAN' in text:
        return None
    result = {}
    for line in text.split('\n'):
        if ':' in line:
            key, _, val = line.partition(':')
            result[key.strip()] = val.strip()
    required = ('TIEU_DE', 'LOAI', 'LAI_SUAT', 'TIN_DUNG_BDS', 'MUC_DO', 'TAC_DONG', 'KHUYEN_NGHI')
    if not all(k in result for k in required):
        return None
    return result

def generate_daily_analysis(articles_today, date_str):
    if not articles_today:
        return None
    news_list = '\n'.join([
        f'- {a["tieu_de"]} | LS:{a["lai_suat"]} | TD:{a["tin_dung_bds"]} | {a["tac_dong"]}'
        for a in articles_today
    ])
    prompt = f"""Bạn là chuyên gia phân tích thị trường ngân hàng và BĐS Việt Nam.
Dưới đây là các tin tức quan trọng ngày {date_str}:

{news_list}

Viết BÁO CÁO PHÂN TÍCH NGÀY bằng tiếng Việt, gồm 4 mục rõ ràng:
1. XU HƯỚNG LÃI SUẤT: Lãi suất huy động/cho vay đang đi đâu? Ý nghĩa với NĐT?
2. TÍN DỤNG BĐS: Chính sách tín dụng BĐS có gì đáng chú ý? Room có nới ra không?
3. THỊ TRƯỜNG PHÍA NAM: Tác động cụ thể đến TP.HCM, Bình Dương, Đồng Nai, Long An?
4. KHUYẾN NGHỊ: 2-3 điểm hành động thực tiễn cho NĐT BĐS phía Nam hôm nay.

Viết chuyên nghiệp, súc tích, khoảng 200-250 từ. KHÔNG viết lời dẫn hay kết luận thừa."""
    return call_gemini(prompt, max_tokens=1000)

# ── Telegram ───────────────────────────────────────────────────
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    try:
        r = requests.post(url, json={'chat_id': TELEGRAM_CHAT, 'text': msg, 'parse_mode': 'HTML'}, timeout=10)
        return r.json().get('ok', False)
    except Exception:
        return False

# ── HTML Report ────────────────────────────────────────────────
def _rate_badge(val):
    if val == 'TANG':    return '<span class="badge red">▲ TĂNG</span>'
    if val == 'GIAM':    return '<span class="badge green">▼ GIẢM</span>'
    if val == 'ON_DINH': return '<span class="badge orange">→ ỔN ĐỊNH</span>'
    return '<span class="badge gray">—</span>'

def _credit_badge(val):
    if val == 'NOI_LONG':  return '<span class="badge green">✅ NỚI LỎNG</span>'
    if val == 'THAT_CHAT': return '<span class="badge red">🚫 THẮT CHẶT</span>'
    if val == 'KHONG_DOI': return '<span class="badge orange">→ KHÔNG ĐỔI</span>'
    return '<span class="badge gray">—</span>'

def _signal_badge(val):
    m = {
        'MUA_VE':   ('<span class="badge green">🟢 MUA VỀ</span>',   '#27ae60'),
        'GIU_CHO':  ('<span class="badge orange">🟡 GIỮ/CHỜ</span>', '#f39c12'),
        'CHO_DOI':  ('<span class="badge red">🔴 CHỜ ĐỢI</span>',    '#e74c3c'),
        'KHONG_RO': ('<span class="badge gray">⚪ CHƯA RÕ</span>',   '#95a5a6'),
    }
    return m.get(val, m['KHONG_RO'])

def generate_html_report(articles_today, daily_analysis, date_str, now_vn):
    mua_ve   = sum(1 for a in articles_today if a.get('khuyen_nghi') == 'MUA_VE')
    cho_doi  = sum(1 for a in articles_today if a.get('khuyen_nghi') == 'CHO_DOI')
    giu_cho  = sum(1 for a in articles_today if a.get('khuyen_nghi') == 'GIU_CHO')

    tang_ls = sum(1 for a in articles_today if a.get('lai_suat') == 'TANG')
    giam_ls = sum(1 for a in articles_today if a.get('lai_suat') == 'GIAM')
    ls_val  = 'TANG' if tang_ls > giam_ls else ('GIAM' if giam_ls > tang_ls else 'ON_DINH')

    noi_td  = sum(1 for a in articles_today if a.get('tin_dung_bds') == 'NOI_LONG')
    that_td = sum(1 for a in articles_today if a.get('tin_dung_bds') == 'THAT_CHAT')
    td_val  = 'NOI_LONG' if noi_td > that_td else ('THAT_CHAT' if that_td > noi_td else 'KHONG_DOI')

    if mua_ve > cho_doi:
        market_icon, market_color, market_label, market_desc = '🟢', '#27ae60', 'TÍCH CỰC', 'Điều kiện thuận lợi — có thể xem xét vào hàng'
    elif cho_doi > mua_ve:
        market_icon, market_color, market_label, market_desc = '🔴', '#e74c3c', 'THẬN TRỌNG', 'Áp lực lãi suất cao — nên chờ đợi thêm'
    else:
        market_icon, market_color, market_label, market_desc = '🟡', '#f39c12', 'TRUNG LẬP', 'Thị trường phân hóa — chọn lọc kỹ trước khi vào'

    # Bảng tin tức — sắp xếp CAO trước
    sort_order = {'CAO': 0, 'TRUNG_BINH': 1, 'THAP': 2}
    sorted_articles = sorted(articles_today, key=lambda x: sort_order.get(x.get('muc_do', 'THAP'), 2))
    rows = ''
    for a in sorted_articles:
        badge_html, _ = _signal_badge(a.get('khuyen_nghi', 'KHONG_RO'))
        row_class = 'row-high' if a.get('muc_do') == 'CAO' else ('row-mid' if a.get('muc_do') == 'TRUNG_BINH' else '')
        rows += f"""
        <tr class="{row_class}">
          <td><a href="{a.get('link','#')}" target="_blank">{a.get('tieu_de', '')}</a>
              <div class="source-tag">{a.get('source','')}</div></td>
          <td class="center">{_rate_badge(a.get('lai_suat',''))}</td>
          <td class="center">{_credit_badge(a.get('tin_dung_bds',''))}</td>
          <td>{a.get('tac_dong', '')}</td>
          <td class="center">{badge_html}</td>
        </tr>"""

    analysis_html = (daily_analysis or 'Chưa có đủ dữ liệu để tạo phân tích tổng quan hôm nay.').replace('\n', '<br>')

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Báo cáo Ngân hàng & BĐS Phía Nam — {date_str}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', system-ui, Arial, sans-serif; background: #f0f2f5; color: #2c3e50; line-height: 1.5; }}

/* Header */
.header {{ background: linear-gradient(135deg, #1a3a5c 0%, #2471a3 100%); color: white; padding: 22px 32px; }}
.header h1 {{ font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }}
.header .sub {{ font-size: 13px; opacity: 0.80; margin-top: 5px; }}

/* Container */
.container {{ max-width: 1100px; margin: 0 auto; padding: 18px 16px; }}

/* Dashboard cards */
.dashboard {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }}
.card {{ background: white; border-radius: 10px; padding: 16px 18px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); }}
.card .clabel {{ font-size: 11px; text-transform: uppercase; color: #7f8c8d; letter-spacing: 0.6px; }}
.card .cvalue {{ font-size: 20px; font-weight: 700; margin-top: 6px; }}
.card .csub {{ font-size: 12px; color: #95a5a6; margin-top: 3px; }}
.market-card {{ border-left: 5px solid {market_color}; }}
.market-card .cvalue {{ color: {market_color}; }}

/* Section */
.section {{ background: white; border-radius: 10px; padding: 20px 22px; margin-bottom: 14px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); }}
.section h2 {{ font-size: 14px; font-weight: 700; color: #1a3a5c; border-bottom: 2px solid #eaf2fb; padding-bottom: 10px; margin-bottom: 14px; }}

/* Table */
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #eaf2fb; color: #1a3a5c; padding: 9px 11px; text-align: left; font-weight: 600; white-space: nowrap; }}
td {{ padding: 10px 11px; border-bottom: 1px solid #f2f5f8; vertical-align: middle; }}
td a {{ color: #2471a3; text-decoration: none; font-weight: 500; }}
td a:hover {{ text-decoration: underline; }}
tr:last-child td {{ border-bottom: none; }}
tr.row-high td {{ background: #fffbf0; }}
tr.row-mid td {{ background: #fafdff; }}
.center {{ text-align: center; }}
.source-tag {{ font-size: 11px; color: #95a5a6; margin-top: 3px; }}

/* Badges */
.badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; white-space: nowrap; }}
.badge.red    {{ background: #fdecea; color: #c0392b; }}
.badge.green  {{ background: #eafaf1; color: #1e8449; }}
.badge.orange {{ background: #fef9e7; color: #b7770d; }}
.badge.gray   {{ background: #f2f3f4; color: #7f8c8d; }}

/* Analysis text */
.analysis {{ line-height: 1.8; font-size: 14px; color: #34495e; }}

/* Footer */
.footer {{ text-align: center; font-size: 12px; color: #aab0b6; padding: 14px 0 20px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🏦 Báo cáo Thị trường Ngân hàng &amp; BĐS Phía Nam</h1>
  <div class="sub">
    Cập nhật: {now_vn.strftime("%H:%M")} &nbsp;|&nbsp; {now_vn.strftime("%d/%m/%Y")} &nbsp;|&nbsp;
    Khu vực: TP.HCM · Bình Dương · Đồng Nai · Long An · Bà Rịa-Vũng Tàu
  </div>
</div>

<div class="container">

  <!-- Dashboard -->
  <div class="dashboard">
    <div class="card">
      <div class="clabel">Xu hướng Lãi suất</div>
      <div class="cvalue">{_rate_badge(ls_val)}</div>
      <div class="csub">{tang_ls} tin tăng &nbsp;·&nbsp; {giam_ls} tin giảm</div>
    </div>
    <div class="card">
      <div class="clabel">Tín dụng BĐS</div>
      <div class="cvalue">{_credit_badge(td_val)}</div>
      <div class="csub">{noi_td} nới &nbsp;·&nbsp; {that_td} thắt chặt</div>
    </div>
    <div class="card">
      <div class="clabel">Tin phân tích hôm nay</div>
      <div class="cvalue" style="color:#1a3a5c">{len(articles_today)}</div>
      <div class="csub">
        <span style="color:#27ae60">{mua_ve} mua về</span> &nbsp;·&nbsp;
        <span style="color:#f39c12">{giu_cho} giữ/chờ</span> &nbsp;·&nbsp;
        <span style="color:#e74c3c">{cho_doi} chờ đợi</span>
      </div>
    </div>
    <div class="card market-card">
      <div class="clabel">Tín hiệu Thị trường Hôm nay</div>
      <div class="cvalue">{market_icon} {market_label}</div>
      <div class="csub">{market_desc}</div>
    </div>
  </div>

  <!-- Phân tích tổng quan -->
  <div class="section">
    <h2>🤖 Phân tích Tổng quan — {now_vn.strftime("%d/%m/%Y")}</h2>
    <div class="analysis">{analysis_html}</div>
  </div>

  <!-- Bảng tin tức -->
  <div class="section">
    <h2>📰 Tin tức đáng chú ý ({len(articles_today)} bài)</h2>
    {'<p style="color:#95a5a6;text-align:center;padding:20px">Chưa có tin tức phân tích cho ngày này.</p>' if not articles_today else f'''
    <table>
      <thead>
        <tr>
          <th style="width:33%">Tiêu đề</th>
          <th style="width:11%">Lãi suất</th>
          <th style="width:13%">Tín dụng BĐS</th>
          <th style="width:30%">Tác động NĐT phía Nam</th>
          <th style="width:13%">Khuyến nghị</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>'''}
  </div>

</div>
<div class="footer">
  Báo cáo tự động &nbsp;|&nbsp; Nguồn: CafeF · VnExpress · Thanh Niên · VietnamNet &nbsp;|&nbsp; Phân tích: Gemini AI<br>
  Tạo lúc {now_vn.strftime("%H:%M:%S %d/%m/%Y")} (Giờ VN)
</div>
</body>
</html>"""
    return html

def save_html_report(html, date_str):
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f'banking_bds_{date_str}.html'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path

# ── Main ───────────────────────────────────────────────────────
def main():
    if not GEMINI_API_KEY:
        print('Thieu bien moi truong: GEMINI_API_KEY')
        print('Cach set: set GEMINI_API_KEY=your_key_here  (Windows CMD)')
        print('          $env:GEMINI_API_KEY="your_key"    (PowerShell)')
        return

    now_vn    = datetime.now(timezone.utc).astimezone(VN_TZ)
    today_str = now_vn.strftime('%Y-%m-%d')
    state     = load_state()
    seen      = set(state.get('seen', []))

    # Giới hạn kích thước seen
    if len(seen) > 500:
        seen = set(list(seen)[-300:])

    # Chỉ giữ daily_articles trong 7 ngày gần nhất
    cutoff = (now_vn - timedelta(days=7)).strftime('%Y-%m-%d')
    state['daily_articles'] = [
        a for a in state.get('daily_articles', [])
        if a.get('date', '') >= cutoff
    ]

    print(f'=== Banking & BDS Agent — {now_vn.strftime("%Y-%m-%d %H:%M")} (Gio VN) ===')

    # Thu thập bài mới từ RSS
    new_articles = []
    for source, feed_url in RSS_FEEDS:
        print(f'Doc RSS: {source}...', end=' ', flush=True)
        articles = fetch_rss(feed_url)
        count = 0
        for a in articles:
            aid = article_id(a['title'], a['link'])
            if aid in seen:
                continue
            if not is_relevant(a['title'], a['desc']):
                continue
            new_articles.append({**a, 'id': aid, 'source': source})
            count += 1
        print(f'{count} bai moi')

    print(f'Tong cong {len(new_articles)} bai lien quan chua xu ly')

    # Phân tích từng bài với Gemini
    for a in new_articles[:MAX_ARTICLES]:
        print(f'Phan tich: {a["title"][:65]}...', end=' ', flush=True)
        raw    = analyze_article(a['title'], a['desc'])
        if raw == 'QUOTA_EXCEEDED':
            print('Dung do het quota Gemini hom nay.')
            break
        parsed = parse_article_response(raw)
        seen.add(a['id'])

        if not parsed:
            print('khong lien quan / loi parse')
            time.sleep(1)
            continue

        if parsed.get('MUC_DO') == 'THAP':
            print('muc do THAP, bo qua')
            time.sleep(1)
            continue

        state['daily_articles'].append({
            'date':         today_str,
            'tieu_de':      parsed.get('TIEU_DE', a['title']),
            'loai':         parsed.get('LOAI', ''),
            'lai_suat':     parsed.get('LAI_SUAT', ''),
            'tin_dung_bds': parsed.get('TIN_DUNG_BDS', ''),
            'muc_do':       parsed.get('MUC_DO', ''),
            'tac_dong':     parsed.get('TAC_DONG', ''),
            'khuyen_nghi':  parsed.get('KHUYEN_NGHI', ''),
            'link':         a.get('link', ''),
            'source':       a.get('source', ''),
        })
        print(f"OK | {parsed.get('MUC_DO')} | {parsed.get('KHUYEN_NGHI')}")
        time.sleep(2)

    # Tạo báo cáo HTML
    articles_today = [a for a in state.get('daily_articles', []) if a.get('date') == today_str]
    print(f'\nTao bao cao HTML ({len(articles_today)} bai hom nay)...')

    daily_analysis = None
    already_reported = state.get('last_daily_report') == today_str

    if articles_today and not already_reported:
        daily_analysis = generate_daily_analysis(articles_today, today_str)
        if daily_analysis == 'QUOTA_EXCEEDED':
            daily_analysis = None

    html = generate_html_report(articles_today, daily_analysis, today_str, now_vn)
    report_path = save_html_report(html, today_str)
    print(f'Bao cao HTML: {report_path}')

    if daily_analysis:
        state['last_daily_report'] = today_str
        # Gửi tóm tắt qua Telegram nếu có cấu hình
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            mua_ve  = sum(1 for a in articles_today if a.get('khuyen_nghi') == 'MUA_VE')
            cho_doi = sum(1 for a in articles_today if a.get('khuyen_nghi') == 'CHO_DOI')
            sig = '🟢 TÍCH CỰC' if mua_ve > cho_doi else ('🔴 THẬN TRỌNG' if cho_doi > mua_ve else '🟡 TRUNG LẬP')
            msg = '\n'.join([
                f'🏦 <b>Báo cáo Ngân hàng &amp; BĐS Phía Nam — {now_vn.strftime("%d/%m/%Y")}</b>',
                f'Tín hiệu: {sig} | Tin phân tích: {len(articles_today)} bài',
                '',
                daily_analysis[:700] + ('...' if len(daily_analysis) > 700 else ''),
                f'\n⏱ Cập nhật: {now_vn.strftime("%H:%M")} (Giờ VN)',
            ])
            ok = send_telegram(msg)
            print(f'Telegram: {"OK" if ok else "Loi hoac chua cau hinh"}')

    state['seen'] = list(seen)
    save_state(state)
    print(f'=== Hoan thanh. Bao cao: {report_path} ===')

if __name__ == '__main__':
    main()
