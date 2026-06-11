#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commodity Market Report Agent
- Đọc RSS tin tức thế giới mỗi 30 phút, thu thập bài liên quan hàng hóa
- Tạo báo cáo tổng hợp 2 lần/ngày: 7:00 (phiên Á) và 20:00 (phiên Mỹ)
- Báo cáo: phân tích vĩ mô, tín hiệu giao dịch, mức giá, rủi ro
- Tổng kết tuần vào thứ 6 sau 20:00
"""
import json, os, sys, time, hashlib, logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from market_data import fetch_cftc_cot_structured

_ROOT               = Path(__file__).parent.parent
TELEGRAM_TOKEN      = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT       = os.environ.get('TELEGRAM_CHAT', '')
GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY', '')
ALPHAVANTAGE_KEY    = os.environ.get('ALPHAVANTAGE_API_KEY', '')
TWELVEDATA_KEY      = os.environ.get('TWELVEDATA_API_KEY', '')
FRED_API_KEY        = os.environ.get('FRED_API_KEY', '')
STATE_FILE          = str(_ROOT / 'data' / 'last_commodity_news.json')
OUTPUT_DIR          = _ROOT / 'outputs'
VN_TZ               = timezone(timedelta(hours=7))

MORNING_REPORT_HOUR = 7   # 7:00 VN — trước phiên Á
EVENING_REPORT_HOUR = 20  # 20:00 VN — trước phiên Mỹ
MAX_ARTICLES        = 20  # tối đa bài đưa vào một báo cáo (chọn lọc theo điểm liên quan)


_log = logging.getLogger('commodity')
_log.setLevel(logging.INFO)
_log.propagate = False
# FileHandler được khởi tạo trong main() sau khi data/ đã được đảm bảo tồn tại

RSS_FEEDS = [
    ('MarketWatch',       'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ('BBC Business',      'http://feeds.bbci.co.uk/news/business/rss.xml'),
    ('AP Business',       'https://feeds.apnews.com/rss/apf-business'),
    ('The Guardian Biz',  'https://www.theguardian.com/business/rss'),
    ('Al Jazeera',        'https://www.aljazeera.com/xml/rss/all.xml'),
    ('CNBC Commodities',  'https://www.cnbc.com/id/10000664/device/rss/rss.html'),
    ('OilPrice.com',      'https://oilprice.com/rss/main'),
    ('Mining.com',        'https://www.mining.com/feed/'),
    # Sputnik: state media Nga — them de doi chieu goc nhin (Nga = nha cung
    # dau/khi/kim loai lon). Tin tu day la TIN HIEU LAP TRUONG cua Nga,
    # khong phai su that khach quan — prompt se doi chieu xung dot nguon.
    ('Sputnik (Nga)',     'https://sputnikglobe.com/export/rss2/archive/index.xml'),
]

# Xuat xu / goc nhin cua tung nguon — dua vao prompt de LLM danh gia xung dot
SOURCE_ORIGIN = {
    'MarketWatch':      'Mỹ',
    'BBC Business':     'Anh',
    'AP Business':      'Mỹ',
    'The Guardian Biz': 'Anh',
    'Al Jazeera':       'Trung Đông',
    'CNBC Commodities': 'Mỹ',
    'OilPrice.com':     'báo ngành năng lượng',
    'Mining.com':       'báo ngành khai khoáng',
    'Sputnik (Nga)':    'Nga — state media',
}

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
        # timeout 20s: feed Sputnik ~120KB phan hoi cham, 10s hay bi timeout
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
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

def _matched_kw(title, desc):
    text = (title + ' ' + desc).lower()
    return [kw for kw in COMMODITY_KEYWORDS if kw in text]

# ── Market Data: 4 nguồn giá ──────────────────────────────────

YFINANCE_SYMBOLS = {
    'WTI':     'CL=F',
    'Brent':   'BZ=F',
    'NatGas':  'NG=F',
    'Gold':    'GC=F',
    'Silver':  'SI=F',
    'Copper':  'HG=F',
    'Corn':    'ZC=F',
    'Wheat':   'ZW=F',
    'Soybean': 'ZS=F',
    'DXY':     'DX-Y.NYB',
}

AV_COMMODITY_FUNCS = {
    'WTI':    'WTI',
    'Brent':  'BRENT',
    'NatGas': 'NATURAL_GAS',
    'Copper': 'COPPER',
    'Wheat':  'WHEAT',
    'Corn':   'CORN',
}

TD_SYMBOLS = {
    'WTI':    'WTI/USD',
    'Gold':   'XAU/USD',
    'Silver': 'XAG/USD',
    'Copper': 'XCU/USD',
}

FRED_MACRO_SERIES = {
    'DGS10':    '10Y Treasury Yield (%)',
    'DFII10':   'Real Yield 10Y TIPS (%)',    # lợi suất thực — biến số quan trọng nhất với vàng
    'T5YIE':    '5Y Breakeven Inflation (%)',  # kỳ vọng lạm phát
    'VIXCLS':   'VIX',                         # risk-on/off, đối chiếu tỷ lệ Đồng/Vàng
    'CPIAUCSL': 'CPI (US)',
    'DEXUSEU':  'USD/EUR',
}

SEASONAL_CONTEXT = {
    1: [
        "Năng lượng: Nhu cầu sưởi ấm đỉnh điểm (Đông Bắc Á, Đông Âu) → hỗ trợ NatGas/heating oil",
        "Kim loại: Trung Quốc pre-stocking trước Tết Nguyên Đán → đồng/thép có thể tăng cầu",
        "Nông sản: Nam Mỹ (soy/corn) đang giai đoạn sinh trưởng → thời tiết La Niña là rủi ro chính",
    ],
    2: [
        "Năng lượng: Cuối mùa sưởi ấm → NatGas dần yếu; refinery maintenance bắt đầu",
        "Kim loại: Tuần Tết Nguyên Đán → cầu kim loại Trung Quốc chậm lại 1-2 tuần",
        "Nông sản: Brazil soybean harvest bắt đầu → áp lực giá đậu tương; Argentina corn thu hoạch",
    ],
    3: [
        "Năng lượng: Shoulder season NatGas (nhu cầu sưởi giảm, chưa vào điều hòa) → NatGas yếu nhất năm",
        "Nông sản: Brazil soybean harvest đỉnh điểm → áp lực cung lớn nhất; USDA Prospective Plantings report",
        "Kim loại: Trung Quốc mở cửa sau Tết → cầu đồng/thép phục hồi; mùa xây dựng bắt đầu",
    ],
    4: [
        "Năng lượng: US driving season bắt đầu (Memorial Day build-up) → nhu cầu xăng/WTI tăng dần",
        "Nông sản: US planting season bắt đầu → weather premium vào corn/soy; theo dõi tiến độ gieo trồng USDA",
        "Kim loại: Mùa xây dựng Trung Quốc peak → đồng/thép/nickel hưởng lợi",
    ],
    5: [
        "Năng lượng: Driving season tăng tốc; refinery runs tối đa để tích xăng hè",
        "Nông sản: US planting đỉnh điểm → mưa/lũ miền Trung Tây là rủi ro lớn nhất; Brazil safrinha corn thu hoạch",
        "Kim loại: Mùa xây dựng tiếp tục; nhu cầu đồng từ lưới điện tái tạo thường tăng Q2",
    ],
    6: [
        "Năng lượng: US driving season peak; OPEC+ thường họp tháng 6 để quyết định quota H2",
        "Nông sản: US corn pollination bắt đầu (critical weather window); USDA WASDE tháng 6 quan trọng",
        "Kim loại: Nhu cầu điện điều hòa Trung Quốc → đồng hưởng lợi; mùa mưa Ấn Độ ảnh hưởng nhu cầu nông nghiệp",
    ],
    7: [
        "Năng lượng: Driving season peak; hurricane season Gulf of Mexico — rủi ro gián đoạn sản xuất",
        "Nông sản: US corn pollination đỉnh điểm → 'weather market' volatile nhất năm; lúa mì Bắc Bán Cầu thu hoạch",
        "Kim loại: Nhu cầu điều hòa Trung Quốc cao → đồng tích cực; mùa xây dựng vẫn mạnh",
    ],
    8: [
        "Năng lượng: Driving season kết thúc cuối tháng → gasoline crack spread yếu dần; hurricane risk cao nhất",
        "Nông sản: US corn/soy filling → cửa sổ thời tiết cuối cùng; USDA August WASDE cập nhật yield quan trọng",
        "Kim loại: Trung Quốc kiểm tra môi trường mùa hè → sản xuất thép/nhôm có thể bị cắt giảm",
    ],
    9: [
        "Năng lượng: Driving season kết thúc → gasoline demand giảm; bắt đầu tích NatGas cho mùa đông",
        "Nông sản: US corn/soy harvest bắt đầu → áp lực cung; Brazil soybean planting bắt đầu",
        "Kim loại: Trung Quốc Golden Week cuối tháng → cầu giảm 1 tuần trước kỳ nghỉ",
    ],
    10: [
        "Năng lượng: Heating season bắt đầu Bắc Bán Cầu → NatGas/heating oil tăng cầu; refinery switch sang heating oil",
        "Nông sản: US harvest đỉnh điểm (corn, soy) → áp lực giá lớn nhất; Brazil planting tiến độ là focus mới",
        "Kim loại: Sau Golden Week → cầu Trung Quốc phục hồi; mùa xây dựng bắt đầu chậm lại",
    ],
    11: [
        "Năng lượng: Heating season build-up; OPEC+ họp thường niên → quyết định quota năm tới",
        "Nông sản: Brazil soybean planting đỉnh điểm → thời tiết Nam Mỹ là rủi ro chính; US harvest gần xong",
        "Kim loại: Nhu cầu xây dựng Trung Quốc chậm lại theo mùa đông; đồng thường yếu tháng 11-12",
    ],
    12: [
        "Năng lượng: Đỉnh nhu cầu sưởi ấm; thin liquidity cuối năm → volatility tăng đột biến có thể xảy ra",
        "Nông sản: Brazil soybean growth stage → La Niña/El Niño là yếu tố quyết định vụ năm sau",
        "Kim loại: Year-end position squaring → fund outflows tạo áp lực; Trung Quốc thường công bố kích thích kinh tế Q1",
    ],
}

# Yếu tố mùa vụ đặc thù ảnh hưởng tới thị trường Việt Nam
# Cấu trúc mỗi tháng: [xuất khẩu chính, nhập khẩu/đầu vào, nội địa/thời tiết]
VIETNAM_SEASONAL_CONTEXT = {
    1: [
        "Xuất khẩu: Cà phê Robusta (Tây Nguyên) đang thu hoạch → nếu giá ICE London cao, nhà xuất khẩu đẩy bán; theo dõi lượng tồn kho tại cảng TP.HCM",
        "Nhập khẩu: Giá dầu thô ảnh hưởng trực tiếp giá xăng trong nước (điều chỉnh 2 tuần/lần); LPG tăng do nhu cầu nấu ăn cuối năm",
        "Nội địa: Vụ Đông Xuân đang sinh trưởng ở ĐBSCL → hạn hán, xâm nhập mặn (El Niño) là rủi ro chính; xây dựng chạy nước rút trước Tết → cầu thép tốt",
    ],
    2: [
        "Xuất khẩu: Cà phê xuất khẩu gián đoạn tuần Tết; sau Tết nhà xuất khẩu quay lại thị trường cùng lúc → có thể tạo áp lực giá ngắn hạn",
        "Nhập khẩu: LPG/gas nấu ăn tăng đột biến dịp Tết; ngô + đậu tương nhập khẩu cho thức ăn chăn nuôi (chuẩn bị nguồn thịt Tết)",
        "Nội địa: Tết Nguyên Đán — xây dựng dừng hoàn toàn ~2 tuần → cầu thép, xi măng giảm; sau Tết mùa xây dựng bật lại mạnh",
    ],
    3: [
        "Xuất khẩu: Gạo vụ Đông Xuân bắt đầu thu hoạch (Mar-May) → cung gạo XK tăng; hạt điều harvest bắt đầu (Bình Phước, Đắk Lắk) — VN là XK điều #1 thế giới",
        "Nhập khẩu: Phân bón (urea từ Trung Đông/Nga) cho vụ Hè Thu sắp tới; giá urea thế giới ảnh hưởng chi phí nông dân ĐBSCL",
        "Nội địa: Cao su bắt đầu mùa cạo mủ (Mar-Nov) → sản lượng VN tăng; cầu đồng từ Trung Quốc quyết định giá cao su thiên nhiên; mùa xây dựng phục hồi sau Tết → thép tăng cầu",
    ],
    4: [
        "Xuất khẩu: Gạo Đông Xuân thu hoạch đỉnh điểm → cung dồi dào, giá gạo XK VN thường cạnh tranh nhất Q2; hồ tiêu harvest bắt đầu — VN là XK hồ tiêu #1 thế giới",
        "Nhập khẩu: Than nhiệt điện nhập khẩu tăng (bắt đầu mùa nóng, nhu cầu điện tăng); giá than Indonesia/Australia ảnh hưởng chi phí điện",
        "Nội địa: Nhu cầu xăng tăng dịp lễ 30/4–1/5; miền Nam bắt đầu nóng → cầu điện tăng; xây dựng peak trước mùa mưa",
    ],
    5: [
        "Xuất khẩu: Hồ tiêu thu hoạch đỉnh điểm; gạo Hè Thu bắt đầu gieo cấy → nhu cầu phân bón, thuốc BVTV tăng",
        "Nhập khẩu: Ngô + đậu tương nhập mạnh cho thức ăn chăn nuôi (vụ nuôi tôm hè); urea chuẩn bị vụ Hè Thu",
        "Nội địa: Mùa mưa Nam Bộ bắt đầu → xây dựng chậm lại ở phía Nam; miền Bắc mưa giông → cầu điện cao; cao su cạo mủ chính vụ",
    ],
    6: [
        "Xuất khẩu: Tôm hè bắt đầu thu hoạch (ĐBSCL) → xuất khẩu thủy sản tăng; giá thức ăn tôm (đậu tương, bột cá) ảnh hưởng lợi nhuận người nuôi",
        "Nhập khẩu: Than nhiệt điện nhập khẩu cao nhất năm (điều hòa mùa hè); dầu DO cho máy phát điện khu công nghiệp",
        "Nội địa: Mưa đầy đủ Nam Bộ → xây dựng chậm, cầu thép/xi măng giảm theo mùa; miền Bắc nắng nóng → nguy cơ thiếu điện, cầu than tăng đột biến",
    ],
    7: [
        "Xuất khẩu: Gạo Hè Thu bắt đầu thu hoạch (Jul-Sep) ở ĐBSCL → đỉnh xuất khẩu gạo năm; tôm vụ 1 thu hoạch → xuất khẩu thủy sản peak",
        "Nhập khẩu: Cầu than nhiệt điện cực đại (điều hòa); ngô/đậu tương cho thức ăn chăn nuôi vụ 2",
        "Nội địa: Mùa bão bắt đầu (Jun-Nov) → rủi ro gián đoạn cảng biển miền Trung, thiệt hại nông nghiệp; cao su cạo mủ chính vụ",
    ],
    8: [
        "Xuất khẩu: Gạo Hè Thu thu hoạch đỉnh → VN tăng cung ra thị trường thế giới tháng 8-9, ảnh hưởng giá gạo Thái Lan/Ấn Độ cạnh tranh",
        "Nhập khẩu: Phân bón chuẩn bị vụ Thu Đông và Đông Xuân (nhập trước 2-3 tháng); giá urea/DAP thế giới là chi phí trực tiếp",
        "Nội địa: Bão miền Trung rủi ro cao → thiệt hại nông nghiệp, nuôi trồng thủy sản; xây dựng Nam Bộ vẫn chậm do mưa",
    ],
    9: [
        "Xuất khẩu: Gạo cung dồi dào nhất năm (Hè Thu xong) → nếu giá quốc tế tốt, VN đẩy mạnh xuất khẩu; cao su xuất khẩu ổn định",
        "Nhập khẩu: Nhập khẩu ngô/đậu tương cho vụ nuôi tôm vụ 2; than nhiệt điện bắt đầu giảm (cuối mùa hè)",
        "Nội địa: Vụ Thu Đông ĐBSCL gieo cấy (Sep-Oct) → cần phân bón; lũ miền Trung bắt đầu (Sep-Nov) → rủi ro nông nghiệp, giao thông",
    ],
    10: [
        "Xuất khẩu: Cà phê Robusta bắt đầu thu hoạch (Oct-Jan) → giá ICE London Robusta là chỉ số theo dõi trực tiếp; nếu El Niño → hạn hán Tây Nguyên, sản lượng giảm → giá tăng",
        "Nhập khẩu: Than nhập khẩu chuẩn bị cho mùa đông miền Bắc; dầu heating oil tăng theo mùa sưởi toàn cầu → chi phí nhập khẩu năng lượng tăng",
        "Nội địa: Lũ miền Trung đỉnh điểm (Oct-Nov) → thiệt hại nông nghiệp, cảng biển Đà Nẵng/Quy Nhơn có thể gián đoạn; Nam Bộ cuối mùa mưa → xây dựng chuẩn bị bật lại",
    ],
    11: [
        "Xuất khẩu: Cà phê thu hoạch đỉnh điểm → xuất khẩu Robusta tăng mạnh; VN cung cấp chủ yếu cho Nestlé, JDE — nếu tồn kho thấp, giá ICE tăng mạnh",
        "Nhập khẩu: Phân bón nhập cho vụ Đông Xuân (vụ chính năm sau); ngô/đậu tương cho chuỗi chăn nuôi lợn/gà Tết",
        "Nội địa: Nam Bộ mùa khô bắt đầu → xây dựng bật lại mạnh, cầu thép/xi măng tăng; miền Trung vẫn còn lũ",
    ],
    12: [
        "Xuất khẩu: Cà phê xuất khẩu đỉnh (nhà thu mua quốc tế đẩy mạnh mua trước năm mới); gạo Đông Xuân chuẩn bị gieo cấy",
        "Nhập khẩu: LPG tăng mạnh chuẩn bị Tết; ngô/đậu tương nhập khẩu tăng để đảm bảo nguồn thịt dịp Tết",
        "Nội địa: Cao điểm xây dựng trước Tết → cầu thép nội địa tốt nhất năm; miền Bắc lạnh → cầu than sưởi tăng; thin liquidity cuối năm trên sàn hàng hóa VN",
    ],
}


def get_seasonal_context(month):
    global_factors = SEASONAL_CONTEXT.get(month, [])
    vn_factors = VIETNAM_SEASONAL_CONTEXT.get(month, [])
    if not global_factors and not vn_factors:
        return ''
    month_name = {
        1:'Tháng 1',2:'Tháng 2',3:'Tháng 3',4:'Tháng 4',
        5:'Tháng 5',6:'Tháng 6',7:'Tháng 7',8:'Tháng 8',
        9:'Tháng 9',10:'Tháng 10',11:'Tháng 11',12:'Tháng 12',
    }[month]
    lines = [f'[NGỮ CẢNH MÙA VỤ — {month_name.upper()}]']
    for f in global_factors:
        lines.append(f'• {f}')
    lines.append('→ Tích hợp các yếu tố mùa vụ trên vào phân tích khi liên quan đến nhóm hàng hóa tương ứng.')
    if vn_factors:
        lines.append(f'[ẢNH HƯỞNG TỚI VIỆT NAM — {month_name.upper()}]')
        for f in vn_factors:
            lines.append(f'• {f}')
        lines.append('→ Liên hệ tác động của giá hàng hóa thế giới tới xuất khẩu, nhập khẩu và nội địa Việt Nam khi phân tích.')
    return '\n'.join(lines)


def fetch_prices_yfinance():
    """Giá + chỉ báo kỹ thuật từ Yahoo Finance (1 năm dữ liệu daily).

    Mỗi symbol: value, chg_pct (1D), chg_5d, chg_1m, low5d/high5d, ma20, ma50,
    rsi14 (Wilder), atr_pct (ATR14/giá), low52w/high52w, pos52w (% vị trí trong dải 52 tuần).
    """
    try:
        import yfinance as yf
        import pandas as pd
        symbols = list(YFINANCE_SYMBOLS.values())
        raw = yf.download(symbols, period='1y', progress=False, auto_adjust=True)
        prices = {}
        for name, sym in YFINANCE_SYMBOLS.items():
            try:
                def _col(field):
                    return raw[(field, sym)].dropna() if (field, sym) in raw.columns else raw[field].dropna()
                close = _col('Close')
                high  = _col('High')
                low   = _col('Low')
                if len(close) < 2:
                    continue
                cur  = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                n5   = min(5, len(close))
                n20  = min(20, len(close))
                n50  = min(50, len(close))
                e = {
                    'value':   round(cur, 4),
                    'chg_pct': round((cur - prev) / prev * 100, 2),
                    'low5d':   round(float(low.iloc[-n5:].min()), 4),
                    'high5d':  round(float(high.iloc[-n5:].max()), 4),
                    'ma20':    round(float(close.iloc[-n20:].mean()), 4),
                    'ma50':    round(float(close.iloc[-n50:].mean()), 4),
                }
                if len(close) >= 6:
                    e['chg_5d'] = round((cur / float(close.iloc[-6]) - 1) * 100, 2)
                if len(close) >= 22:
                    e['chg_1m']     = round((cur / float(close.iloc[-22]) - 1) * 100, 2)
                    e['val_1m_ago'] = round(float(close.iloc[-22]), 4)

                # RSI14 — Wilder smoothing (ewm alpha=1/14)
                delta = close.diff()
                gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                rs    = gain / loss.replace(0, float('nan'))
                rsi   = (100 - 100 / (1 + rs)).iloc[-1]
                if pd.notna(rsi):
                    e['rsi14'] = round(float(rsi), 1)

                # ATR14 dưới dạng % giá — đo biến động trung bình ngày
                prev_close = close.shift(1)
                tr = pd.concat([
                    high - low,
                    (high - prev_close).abs(),
                    (low - prev_close).abs(),
                ], axis=1).max(axis=1)
                atr = tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1]
                if pd.notna(atr) and cur:
                    e['atr_pct'] = round(float(atr) / cur * 100, 2)

                # Dải 52 tuần
                lo52, hi52 = float(low.min()), float(high.max())
                e['low52w'], e['high52w'] = round(lo52, 4), round(hi52, 4)
                if hi52 > lo52:
                    e['pos52w'] = round((cur - lo52) / (hi52 - lo52) * 100, 1)

                # Volume phiên ĐÃ ĐÓNG gần nhất so với median 20 phiên trước đó.
                # Bar cuối của yfinance là phiên đang chạy (volume chưa đủ) nên dùng iloc[-2];
                # median + lọc ngày volume=0 để tránh nhiễu do contract roll của futures.
                try:
                    vol = _col('Volume')
                    if len(vol) >= 25:
                        last_closed = float(vol.iloc[-2])
                        base = [float(x) for x in vol.iloc[-22:-2] if float(x) > 0]
                        if last_closed > 0 and len(base) >= 10:
                            base.sort()
                            med = base[len(base) // 2]
                            if med > 0:
                                e['vol_ratio'] = round(min(last_closed / med, 99.0), 2)
                except Exception:
                    pass

                prices[name] = e
            except Exception:
                pass
        print(f'  yfinance: {len(prices)}/{len(YFINANCE_SYMBOLS)} symbols OK')
        return prices
    except ImportError:
        print('  yfinance chưa install — pip install yfinance')
        return {}
    except Exception as e:
        print(f'  yfinance lỗi: {e}')
        return {}


# ── Quant engine: tín hiệu rule-based (deterministic) ─────────

VN_NAMES = {
    'WTI': 'WTI', 'Brent': 'Brent', 'NatGas': 'Khí TN', 'Gold': 'Vàng',
    'Silver': 'Bạc', 'Copper': 'Đồng', 'Corn': 'Ngô', 'Wheat': 'Lúa mì',
    'Soybean': 'Đậu t.', 'DXY': 'DXY',
}

SYMBOL_GROUPS = {
    'energy':     [('WTI', 'WTI'), ('Brent', 'Brent'), ('NatGas', 'Khí TN')],
    'precious':   [('Gold', 'Vàng'), ('Silver', 'Bạc')],
    'agri':       [('Corn', 'Ngô'), ('Wheat', 'Lúa mì'), ('Soybean', 'Đậu tương')],
    'industrial': [('Copper', 'Đồng')],
}


def classify_trend_signal(e):
    """Quy tắc cố định — cùng dữ liệu luôn ra cùng tín hiệu:
    Xu hướng: close>MA20>MA50 → TĂNG; close<MA20<MA50 → GIẢM; còn lại SIDEWAY
    Tín hiệu: TĂNG + RSI<70 → MUA; TĂNG + RSI≥70 → GIỮ (quá mua)
              GIẢM + RSI>30 → BÁN; GIẢM + RSI≤30 → GIỮ (quá bán); SIDEWAY → GIỮ
    """
    v, ma20, ma50 = e.get('value'), e.get('ma20'), e.get('ma50')
    rsi = e.get('rsi14')
    if not (v and ma20 and ma50):
        return 'SIDEWAY', 'GIỮ'
    if v > ma20 > ma50:
        trend = 'TĂNG'
    elif v < ma20 < ma50:
        trend = 'GIẢM'
    else:
        trend = 'SIDEWAY'
    if trend == 'TĂNG':
        signal = 'MUA' if (rsi is None or rsi < 70) else 'GIỮ (quá mua)'
    elif trend == 'GIẢM':
        signal = 'BÁN' if (rsi is None or rsi > 30) else 'GIỮ (quá bán)'
    else:
        signal = 'GIỮ'
    return trend, signal


def support_resistance(e):
    """Hỗ trợ = max(đáy 5D, MA20 nếu MA20 < giá); Kháng cự = đỉnh 5D."""
    v, lo5, hi5, ma20 = e.get('value'), e.get('low5d'), e.get('high5d'), e.get('ma20')
    if not (v and lo5 and hi5):
        return None, None
    sup = max(lo5, ma20) if (ma20 and ma20 < v) else lo5
    return sup, hi5


def _fmt_price(v):
    return f'{v:,.2f}' if abs(v) >= 10 else f'{v:,.3f}'


def build_group_signals(prices):
    """Tín hiệu tính sẵn theo nhóm cho prompt: {group: (xu hướng, tín hiệu, ngưỡng giá)}."""
    out = {}
    for group, syms in SYMBOL_GROUPS.items():
        trends, signals, levels = [], [], []
        for key, label in syms:
            e = prices.get(key)
            if not e:
                continue
            t, s = classify_trend_signal(e)
            trends.append(f'{label} {t}')
            signals.append(f'{label} {s}')
            sup, res = support_resistance(e)
            if sup and res:
                levels.append(f'{label} {_fmt_price(sup)}–{_fmt_price(res)}')
        out[group] = (
            ' | '.join(trends)  or 'N/A',
            ' | '.join(signals) or 'N/A',
            ' | '.join(levels)  or 'N/A',
        )
    return out


def build_quant_table(prices):
    """Bảng số liệu thuần (không qua LLM) cho Telegram <pre> và file báo cáo."""
    rows = [f'{"":7}{"Giá":>9}{"1D%":>7}{"5D%":>7}{"RSI":>5}']
    for name in YFINANCE_SYMBOLS:
        e = prices.get(name)
        if not e:
            continue
        label = VN_NAMES.get(name, name)[:7]
        v  = _fmt_price(e['value'])
        c1 = f'{e["chg_pct"]:+.1f}' if e.get('chg_pct') is not None else '-'
        c5 = f'{e["chg_5d"]:+.1f}' if e.get('chg_5d') is not None else '-'
        ri = f'{e["rsi14"]:.0f}'   if e.get('rsi14')   is not None else '-'
        rows.append(f'{label:7}{v:>9}{c1:>7}{c5:>7}{ri:>5}')
    return '\n'.join(rows) if len(rows) > 1 else ''


def build_cross_asset_lines(prices):
    """Chỉ số liên thị trường: Brent−WTI spread, tỷ lệ Vàng/Bạc, Đồng/Vàng."""
    lines = []
    wti, brent = prices.get('WTI'), prices.get('Brent')
    if wti and brent:
        spread = brent['value'] - wti['value']
        s = f'Brent−WTI: ${spread:.2f}'
        if wti.get('val_1m_ago') and brent.get('val_1m_ago'):
            s += f' (1 tháng trước: ${brent["val_1m_ago"] - wti["val_1m_ago"]:.2f})'
        lines.append(s + ' — spread rộng = cung WTI dồi dào tương đối')
    gold, silver = prices.get('Gold'), prices.get('Silver')
    if gold and silver and silver['value']:
        ratio = gold['value'] / silver['value']
        s = f'Vàng/Bạc: {ratio:.1f}'
        if gold.get('val_1m_ago') and silver.get('val_1m_ago'):
            s += f' (1 tháng trước: {gold["val_1m_ago"] / silver["val_1m_ago"]:.1f})'
        lines.append(s + ' — tỷ lệ cao = bạc rẻ tương đối so với vàng')
    copper = prices.get('Copper')
    if copper and gold and gold['value']:
        ratio = copper['value'] / gold['value'] * 1000
        s = f'Đồng/Vàng (×1000): {ratio:.2f}'
        if copper.get('val_1m_ago') and gold.get('val_1m_ago'):
            s += f' (1 tháng trước: {copper["val_1m_ago"] / gold["val_1m_ago"] * 1000:.2f})'
        lines.append(s + ' — tăng = risk-on/kỳ vọng tăng trưởng')
    return lines


def build_volume_alert_line(prices):
    """Liệt kê symbols có volume phiên đóng gần nhất ≥1.5× median 20 phiên.
    Chỉ cảnh báo phía cao — volume cao xác nhận biến động giá là thật;
    phía thấp không dùng vì volume futures Yahoo hay thiếu/trễ."""
    hot = []
    for name in YFINANCE_SYMBOLS:
        e = prices.get(name)
        if not e or e.get('vol_ratio') is None:
            continue
        if e['vol_ratio'] >= 1.5:
            hot.append(f'{VN_NAMES.get(name, name)} {e["vol_ratio"]:.1f}×')
    if not hot:
        return None
    return '📊 Volume cao bất thường (phiên đóng gần nhất so median 20 phiên): ' + ', '.join(hot)


def build_cot_block(state):
    """Vị thế quỹ đầu cơ CFTC COT + thay đổi so với tuần trước (lưu trong state)."""
    cot = fetch_cftc_cot_structured()
    hist = state.get('cot_history', [])
    if cot:
        if not hist or hist[-1].get('date') != cot['date']:
            hist.append(cot)
            state['cot_history'] = hist[-4:]
    elif hist:
        cot = hist[-1]  # fallback: dùng dữ liệu tuần gần nhất đã lưu
    if not cot:
        return None
    prev = next((h for h in reversed(hist) if h.get('date', '') < cot['date']), None)
    lines = [f'[VỊ THẾ QUỸ ĐẦU CƠ — CFTC COT tuần {cot["date"]}]']
    for mk, net in cot['markets'].items():
        s = f'  {mk}: {"NET LONG" if net > 0 else "NET SHORT"} {net:+,}'
        if prev and mk in prev.get('markets', {}):
            s += f' (Δ tuần: {net - prev["markets"][mk]:+,})'
        lines.append(s)
    lines.append('→ NET LONG = quỹ đặt cược giá tăng; Δ dương = dòng tiền đầu cơ đang vào')
    return '\n'.join(lines)


def build_weekly_perf_block(prices):
    """Bảng hiệu suất tuần thực (% thay đổi 5 phiên), sắp xếp giảm dần."""
    entries = [
        (VN_NAMES.get(n, n), e['chg_5d'])
        for n, e in prices.items() if e.get('chg_5d') is not None
    ]
    if not entries:
        return None
    entries.sort(key=lambda x: -x[1])
    lines = ['[HIỆU SUẤT TUẦN — % thay đổi 5 phiên]']
    for label, c in entries:
        lines.append(f'  {label}: {c:+.1f}%')
    lines.append(f'→ Tốt nhất: {entries[0][0]} {entries[0][1]:+.1f}% | Kém nhất: {entries[-1][0]} {entries[-1][1]:+.1f}%')
    return '\n'.join(lines)


def fetch_prices_alphavantage():
    """Giá daily chính thức từ Alpha Vantage (25 req/ngày free). Chỉ fill gap của yfinance."""
    if not ALPHAVANTAGE_KEY:
        return {}
    prices = {}
    for name, func in AV_COMMODITY_FUNCS.items():
        try:
            r = requests.get(
                f'https://www.alphavantage.co/query?function={func}&interval=daily&apikey={ALPHAVANTAGE_KEY}',
                timeout=10,
            )
            series = r.json().get('data', [])
            if series:
                prices[name] = round(float(series[0]['value']), 4)
        except Exception:
            pass
        time.sleep(0.3)
    print(f'  Alpha Vantage: {len(prices)}/{len(AV_COMMODITY_FUNCS)} symbols OK')
    return prices


def fetch_prices_twelvedata():
    """Giá near-realtime từ Twelve Data (~1 min delay, 800 req/ngày free). Chỉ fill gap."""
    if not TWELVEDATA_KEY:
        return {}
    try:
        symbols_str = ','.join(TD_SYMBOLS.values())
        r = requests.get(
            f'https://api.twelvedata.com/price?symbol={symbols_str}&apikey={TWELVEDATA_KEY}',
            timeout=10,
        )
        data = r.json()
        sym_to_name = {v: k for k, v in TD_SYMBOLS.items()}
        prices = {}
        for sym, val in data.items():
            if isinstance(val, dict) and 'price' in val:
                name = sym_to_name.get(sym, sym)
                prices[name] = round(float(val['price']), 4)
        print(f'  Twelve Data: {len(prices)}/{len(TD_SYMBOLS)} symbols OK')
        return prices
    except Exception as e:
        print(f'  Twelve Data lỗi: {e}')
        return {}


def fetch_macro_fred():
    """Macro indicators từ FRED (miễn phí, không cần key).
    Keyless dùng fredgraph.csv giới hạn 90 ngày (cosd) — tải full history dễ timeout."""
    macro = {}
    start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime('%Y-%m-%d')
    for series_id, label in FRED_MACRO_SERIES.items():
        try:
            if FRED_API_KEY:
                r = requests.get(
                    f'https://api.stlouisfed.org/fred/series/observations'
                    f'?series_id={series_id}&sort_order=desc&limit=3'
                    f'&file_type=json&api_key={FRED_API_KEY}',
                    timeout=10,
                )
                obs = [o for o in r.json().get('observations', []) if o['value'] != '.']
            else:
                r = requests.get(
                    f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}',
                    timeout=30,
                )
                rows = r.text.strip().split('\n')[1:]
                valid = [l for l in rows if ',' in l and not l.split(',')[1].strip() == '.']
                obs = [{'date': l.split(',')[0], 'value': l.split(',')[1].strip()} for l in valid[-3:]]
                obs.reverse()
                time.sleep(0.5)  # tránh bị FRED throttle khi gọi nhiều series liên tiếp
            if obs:
                macro[series_id] = {'label': label, 'value': obs[0]['value'], 'date': obs[0]['date']}
        except Exception as e:
            print(f'  FRED {series_id} lỗi: {e}')
    print(f'  FRED: {len(macro)}/{len(FRED_MACRO_SERIES)} series OK')
    return macro


_PRICE_CACHE = {}

def build_price_snapshot():
    """
    Gộp giá từ 4 nguồn. Thứ tự ưu tiên: yfinance → twelvedata → alphavantage.
    FRED là additive (macro, không trùng với giá futures).
    Returns (prices_dict, macro_dict). Cache trong 1 lần chạy (báo cáo tối + tuần dùng chung).
    """
    if 'prices' in _PRICE_CACHE:
        return _PRICE_CACHE['prices'], _PRICE_CACHE['macro']
    print('Fetching giá thị trường (4 nguồn)...')
    yf_prices = fetch_prices_yfinance()
    av_prices  = fetch_prices_alphavantage()
    td_prices  = fetch_prices_twelvedata()
    macro      = fetch_macro_fred()

    combined = {}
    seen = set()
    for name in list(YFINANCE_SYMBOLS.keys()) + list(AV_COMMODITY_FUNCS.keys()) + list(TD_SYMBOLS.keys()):
        if name in seen:
            continue
        seen.add(name)
        if name in yf_prices:
            combined[name] = {**yf_prices[name], 'src': 'yf'}  # rich: value+chg_pct+5D+ma20
        elif name in td_prices:
            combined[name] = {'value': td_prices[name], 'src': 'td'}
        elif name in av_prices:
            combined[name] = {'value': av_prices[name], 'src': 'av'}

    print(f'  Tổng hợp: {len(combined)} symbols | {len(macro)} macro series')
    _PRICE_CACHE['prices'], _PRICE_CACHE['macro'] = combined, macro
    return combined, macro


def format_price_for_prompt(prices, macro, cot_block=None):
    """Block giá + chỉ báo kỹ thuật + liên thị trường + COT đầy đủ cho Gemini prompt."""

    def line(name, label, pfmt='.2f', unit='', cur='$'):
        e = prices.get(name)
        if not e:
            return f'  {label}: N/A'
        v   = e['value']
        chg = e.get('chg_pct')
        l5, h5, ma = e.get('low5d'), e.get('high5d'), e.get('ma20')
        s = f'  {label}: {cur}{v:{pfmt}}{unit}'
        if chg is not None:
            s += f' ({chg:+.2f}%)'
        if e.get('chg_5d') is not None:
            s += f'  |  5 phiên: {e["chg_5d"]:+.1f}%'
        if l5 and h5:
            s += f'  |  5D: {l5:{pfmt}}–{h5:{pfmt}}'
        if ma:
            arrow = '↑' if v > ma else '↓'
            s += f'  |  MA20: {ma:{pfmt}} {arrow}'
        if e.get('ma50'):
            s += f'  |  MA50: {e["ma50"]:{pfmt}}'
        if e.get('rsi14') is not None:
            s += f'  |  RSI14: {e["rsi14"]:.0f}'
        if e.get('atr_pct') is not None:
            s += f'  |  ATR: {e["atr_pct"]:.1f}%/ngày'
        if e.get('pos52w') is not None:
            s += f'  |  52W: {e["pos52w"]:.0f}% ({e["low52w"]:{pfmt}}–{e["high52w"]:{pfmt}})'
        if e.get('vol_ratio') is not None:
            s += f'  |  Vol: {e["vol_ratio"]:.1f}× median20'
        return s

    out = ['--- GIÁ THỊ TRƯỜNG THỰC TẾ ---']
    out.append('[NĂNG LƯỢNG]')
    out.append(line('WTI',    'Dầu WTI    ', '.2f', '/bbl'))
    out.append(line('Brent',  'Dầu Brent  ', '.2f', '/bbl'))
    out.append(line('NatGas', 'Khí TN     ', '.3f', '/MMBtu'))
    out.append('[KIM LOẠI QUÝ]')
    out.append(line('Gold',   'Vàng       ', '.2f', '/oz'))
    out.append(line('Silver', 'Bạc        ', '.3f', '/oz'))
    out.append('[KIM LOẠI CÔNG NGHIỆP]')
    out.append(line('Copper', 'Đồng       ', '.4f', '/lb'))
    out.append('[NÔNG SẢN]  (giá CME tính bằng cent/bushel)')
    out.append(line('Corn',    'Ngô        ', '.2f', '¢/bushel', cur=''))
    out.append(line('Wheat',   'Lúa mì     ', '.2f', '¢/bushel', cur=''))
    out.append(line('Soybean', 'Đậu tương  ', '.2f', '¢/bushel', cur=''))
    out.append('[VĨ MÔ]')
    dxy = prices.get('DXY')
    if dxy:
        v, chg, ma = dxy['value'], dxy.get('chg_pct'), dxy.get('ma20')
        s = f'  DXY: {v:.2f}'
        if chg is not None:
            s += f' ({chg:+.2f}%)'
        if ma:
            s += f'  |  MA20: {ma:.2f} {"↑" if v > ma else "↓"}'
        if dxy.get('rsi14') is not None:
            s += f'  |  RSI14: {dxy["rsi14"]:.0f}'
        out.append(s)
    for sid in FRED_MACRO_SERIES:
        if sid in macro:
            d = macro[sid]
            out.append(f'  {d["label"]}: {d["value"]} ({d["date"]})')

    cross = build_cross_asset_lines(prices)
    if cross:
        out.append('[LIÊN THỊ TRƯỜNG]')
        out.extend(f'  {c}' for c in cross)

    if cot_block:
        out.append(cot_block)

    out.append('→ ↑/↓ = trên/dưới MA20; RSI>70 quá mua, RSI<30 quá bán; 52W = vị trí % trong dải 52 tuần; '
               'Vol ≥1.5× median20 = động lượng được volume xác nhận; real yield giảm = hỗ trợ vàng; VIX cao = risk-off')
    out.append('---')
    return '\n'.join(out)


def format_price_for_telegram(prices, macro):
    """Dòng tóm tắt giá + % thay đổi ngắn gọn cho Telegram header."""
    parts = []
    for name, emoji, pfmt in [('WTI','🛢',',.1f'), ('Gold','🥇',',.0f'), ('Copper','🔩','.3f')]:
        e = prices.get(name)
        if not e:
            continue
        chg = e.get('chg_pct')
        s = f'{emoji}{name}:${e["value"]:{pfmt}}'
        if chg is not None:
            s += f'({chg:+.1f}%)'
        parts.append(s)
    if 'DGS10' in macro:
        parts.append(f'📈10Y:{macro["DGS10"]["value"]}%')
    return '  '.join(parts)


# ── Giá vàng Việt Nam (SJC) ───────────────────────────────────
def get_vn_gold_price():
    """
    Fetch giá vàng nhẫn tức thời từ SJC XML.
    Returns {'name': str, 'buy_tr': float, 'sell_tr': float} triệu VND/lượng, hoặc None.
    """
    try:
        r = requests.get('https://sjc.com.vn/xml/tygia.xml', timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(r.content)
        for item in root.iter('item'):
            name = item.findtext('n', '').strip()
            if 'nhẫn' in name.lower():
                buy_raw  = item.findtext('m', '').replace(',', '').strip()
                sell_raw = item.findtext('h', '').replace(',', '').strip()
                if buy_raw and sell_raw:
                    buy  = float(buy_raw)
                    sell = float(sell_raw)
                    # SJC XML: giá trong nghìn VND (vd: 120000 = 120 tr/lượng)
                    factor = 1_000_000 if buy > 1_000_000 else 1_000
                    return {'name': name, 'buy_tr': buy / factor, 'sell_tr': sell / factor}
        return None
    except Exception:
        return None

def build_gold_vnd_line(vn_gold):
    if not vn_gold:
        return None
    buy, sell  = vn_gold['buy_tr'], vn_gold['sell_tr']
    return (
        f"🇻🇳 Vàng nhẫn SJC — Mua {buy:.2f} tr | Bán {sell:.2f} tr /lượng "
        f"({buy/10:.2f} tr | {sell/10:.2f} tr /chỉ)"
    )

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
                _log.info('GEMINI QUOTA_EXCEEDED')
                return 'QUOTA_EXCEEDED'
            print(f'  Lỗi Gemini API: {data}')
            _log.info('GEMINI ERROR %s', data.get('error', {}).get('message', 'unknown'))
            return None
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f'  Lỗi Gemini: {e}')
        return None

def select_top_articles(articles, limit=MAX_ARTICLES):
    """Chọn bài liên quan nhất theo điểm keyword (deterministic):
    keyword trong title = 3 điểm, trong desc = 1 điểm; hòa điểm → bài mới hơn trước."""
    def score(a):
        title = a.get('title', '').lower()
        desc  = a.get('desc', '').lower()
        s = 0
        for kw in COMMODITY_KEYWORDS:
            if kw in title:
                s += 3
            elif kw in desc:
                s += 1
        return s
    ranked = sorted(articles, key=lambda a: a.get('collected_at', ''), reverse=True)
    ranked.sort(key=score, reverse=True)  # stable sort: giữ thứ tự mới-trước khi hòa điểm
    return ranked[:limit]


def build_session_report_prompt(articles, session, date_str, month, gold_vnd_line=None, price_block=None, prices=None):
    articles_text = '\n'.join([
        f'{i+1}. [{a["source"]} — {SOURCE_ORIGIN.get(a["source"], "?")}] {a["title"]}\n   {a["desc"][:300]}'
        for i, a in enumerate(articles[:MAX_ARTICLES])
    ])
    context = 'tin tức qua đêm và đầu phiên Á' if session == 'morning' else 'tin tức trong ngày và đầu phiên Mỹ'
    session_vn = 'PHIÊN SÁNG (07:00 VN)' if session == 'morning' else 'PHIÊN MỸ (20:00 VN)'

    price_note = f'\n{price_block}\n' if price_block else ''

    vnd_note = ''
    if gold_vnd_line:
        vnd_note = (
            f"\nGIÁ VÀNG VIỆT NAM HIỆN TẠI: {gold_vnd_line}\n"
            "→ Khi phân tích mục KIM LOẠI QUÝ, đề cập thêm giá vàng nhẫn trong nước để người đọc dễ hình dung.\n"
        )

    seasonal = get_seasonal_context(month)
    seasonal_note = f'\n{seasonal}\n' if seasonal else ''

    # Tín hiệu đã tính sẵn bằng quy tắc định lượng — LLM không được tự quyết
    sig = build_group_signals(prices or {})
    na3 = ('N/A', 'N/A', 'N/A')
    energy, precious = sig.get('energy', na3), sig.get('precious', na3)
    agri, industrial = sig.get('agri', na3),   sig.get('industrial', na3)

    return f"""Bạn là chuyên gia phân tích thị trường hàng hóa toàn cầu với kinh nghiệm giao dịch thực tế.
Dưới đây là {len(articles)} {context} ngày {date_str}:{price_note}{vnd_note}{seasonal_note}

{articles_text}

Hãy viết BÁO CÁO PHÂN TÍCH {session_vn} bằng TIẾNG VIỆT theo đúng cấu trúc sau (không thêm gì ngoài cấu trúc này).
QUAN TRỌNG:
- Các dòng "Xu hướng / Tín hiệu / Ngưỡng giá" ĐÃ ĐƯỢC TÍNH SẴN bằng quy tắc định lượng (giá so MA20/MA50 + RSI14) — GIỮ NGUYÊN Y HỆT, không sửa, không thêm bớt.
- Phần "Phân tích" BẮT BUỘC trích dẫn số liệu cụ thể từ bảng dữ liệu phía trên (% thay đổi, RSI, vị trí 52W, spread, vị thế COT) và giải thích tín hiệu định lượng bằng tin tức. KHÔNG viết chung chung kiểu "giá chịu áp lực" mà không có con số.
- Nếu tín hiệu định lượng mâu thuẫn với tin tức, nêu rõ mâu thuẫn đó trong phần Rủi ro.
- ĐỐI CHIẾU NGUỒN: mỗi tin có ghi xuất xứ trong ngoặc [nguồn — góc nhìn]. "Sputnik (Nga)" là state media của Nga — coi tin từ đó là TÍN HIỆU LẬP TRƯỜNG của Nga (điều Nga muốn thị trường tin, nhất là về dầu khí/cấm vận/OPEC+), KHÔNG mặc định là sự thật khách quan. Khi Sputnik và nguồn phương Tây đưa tin TRÁI NGƯỢC về cùng chủ đề, đó chính là thông tin có giá trị — nêu rõ trong mục 🔀.

🔀 ĐỐI CHIẾU NGUỒN TIN
[So sánh các nguồn về CÙNG một chủ đề: nếu có mâu thuẫn (ví dụ Sputnik nói nguồn cung ổn định nhưng Reuters/BBC nói gián đoạn), nêu rõ "Nguồn A nói X, nguồn B nói Y" + hàm ý cho trader (xung đột nguồn về nguồn cung dầu = biến động sắp tới). Nếu không có xung đột đáng kể, ghi đúng 1 câu: "Không phát hiện xung đột đáng kể giữa các nguồn trong phiên này."]

🌍 VĨ MÔ & TIN TỨC NỔI BẬT
[2-3 yếu tố vĩ mô quan trọng nhất, mỗi yếu tố gắn với số liệu từ bảng dữ liệu (DXY, 10Y yield, real yield TIPS, breakeven inflation, VIX, CPI...) nếu liên quan]

🛢️ NĂNG LƯỢNG — Dầu WTI/Brent, Khí tự nhiên
Xu hướng: {energy[0]}
Tín hiệu: {energy[1]}
Ngưỡng giá: {energy[2]}
Phân tích: [2-3 câu — bắt buộc nêu % thay đổi, RSI, vị trí 52W và liên hệ tin tức + COT]
Rủi ro: [rủi ro chính cần theo dõi]

🥇 KIM LOẠI QUÝ — Vàng (XAU/USD), Bạc
Xu hướng: {precious[0]}
Tín hiệu: {precious[1]}
Ngưỡng giá: {precious[2]}
Phân tích: [2-3 câu — bắt buộc nêu số liệu (%, RSI, tỷ lệ Vàng/Bạc, DXY) và liên hệ tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

🌾 NÔNG SẢN — Ngô, Đậu tương, Lúa mì
Xu hướng: {agri[0]}
Tín hiệu: {agri[1]}
Ngưỡng giá: {agri[2]}
Phân tích: [2-3 câu — bắt buộc nêu số liệu (% thay đổi, RSI, COT) kết hợp yếu tố mùa vụ]
Rủi ro: [rủi ro chính cần theo dõi]

🔩 KIM LOẠI CÔNG NGHIỆP — Đồng, Nhôm, Niken
Xu hướng: {industrial[0]}
Tín hiệu: {industrial[1]}
Ngưỡng giá: {industrial[2]}
Phân tích: [2-3 câu — bắt buộc nêu số liệu (% thay đổi, RSI, tỷ lệ Đồng/Vàng, COT) và liên hệ tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

📋 KHUYẾN NGHỊ PHIÊN
[2-3 khuyến nghị cụ thể kèm mức giá vào lệnh/cắt lỗ tham chiếu từ ngưỡng hỗ trợ-kháng cự đã tính]

⚠️ THEO DÕI PHIÊN
[2-3 sự kiện/dữ liệu quan trọng cần theo dõi trong phiên]

Lưu ý: Nếu không đủ tin về một nhóm, phân tích dựa trên số liệu kỹ thuật và bối cảnh mùa vụ. Viết ngắn gọn, rõ ràng, chuyên nghiệp."""

def generate_session_report(articles, session, date_str, month, gold_vnd_line=None, price_block=None, prices=None):
    if not articles:
        return None
    prompt = build_session_report_prompt(articles, session, date_str, month, gold_vnd_line, price_block, prices)
    return call_gemini(prompt, max_tokens=1600)

# ── World Bank Open Data (REST, khong can key) ───────────────
# Du lieu ANNUAL (tre ~1 nam) → chi dung lam boi canh nen, cache 30 ngay.
# Goi thang REST bang requests (nhu FRED/AlphaVantage) — khong them dependency.

def _wb_fetch_series(countries, indicator, mrv=2):
    """World Bank API v2. Tra ve {iso3: (nam, gia_tri)} — gia tri non-null moi nhat."""
    c = ';'.join(countries) if isinstance(countries, list) else countries
    url = f'https://api.worldbank.org/v2/country/{c}/indicator/{indicator}?format=json&mrv={mrv}'
    r = requests.get(url, timeout=20)
    data = r.json()
    out = {}
    if len(data) < 2 or not data[1]:
        return out
    for row in data[1]:                      # rows: moi nhat truoc, theo tung nuoc
        iso = row.get('countryiso3code') or ''
        if row.get('value') is None or iso in out:
            continue
        out[iso] = (row.get('date'), row['value'])
    return out


def fetch_wb_global_context(state):
    """Khoi boi canh tang truong toan cau cho bao cao tuan — cache 30 ngay trong state."""
    cache = state.get('wb_context', {})
    now_ts = time.time()
    if cache.get('block') and (now_ts - cache.get('fetched_ts', 0)) < 30 * 86400:
        return cache['block']
    try:
        gdp = _wb_fetch_series(['CHN', 'USA', 'IND', 'EUU', 'WLD'],
                               'NY.GDP.MKTP.KD.ZG', mrv=2)
        if not gdp:
            return cache.get('block')
        names = {'CHN': 'Trung Quốc', 'USA': 'Mỹ', 'IND': 'Ấn Độ',
                 'EUU': 'EU', 'WLD': 'Thế giới'}
        parts = [f'{names[k]} {v[1]:+.1f}% ({v[0]})'
                 for k, v in gdp.items() if k in names]
        block = ('TĂNG TRƯỞNG GDP — nền cầu hàng hóa (World Bank, năm gần nhất): '
                 + ' | '.join(parts))
        state['wb_context'] = {'fetched_ts': now_ts, 'block': block}
        _log.info('WB_CONTEXT refreshed')
        return block
    except Exception as e:
        print(f'  World Bank API lỗi: {e}')
        return cache.get('block')


def generate_weekly_report(weekly_reports, week_str, perf_block=None, wb_block=None):
    if not weekly_reports:
        return None
    reports_text = '\n\n'.join([
        f'--- {r["date"]} ({r["session"]}) ---\n{r["summary"]}'
        for r in weekly_reports[-14:]
    ])
    perf_note = f'\nHIỆU SUẤT THỰC TẾ TÍNH TỪ DỮ LIỆU GIÁ (không phải ước lượng):\n{perf_block}\n' if perf_block else ''
    wb_note = (f'\n{wb_block}\n→ Dùng làm bối cảnh CẦU dài hạn khi dự báo xu hướng '
               f'(Trung Quốc/Ấn Độ là biên cầu chính của năng lượng & kim loại).\n') if wb_block else ''
    prompt = f"""Bạn là chuyên gia phân tích thị trường hàng hóa toàn cầu.
Dưới đây là các báo cáo phiên trong tuần {week_str}:{perf_note}{wb_note}

{reports_text}

Viết BÁO CÁO TỔNG KẾT TUẦN thị trường hàng hóa bằng TIẾNG VIỆT, gồm:
1. Sự kiện & xu hướng nổi bật nhất tuần (3-4 điểm)
2. Hiệu suất từng nhóm: Năng lượng, Kim loại quý, Nông sản, Kim loại công nghiệp — BẮT BUỘC dùng đúng con số % trong bảng HIỆU SUẤT THỰC TẾ ở trên, không tự bịa số
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
        _log.info('SKIP_%s already_sent date=%s', session.upper(), today_str)
        return
    hour = now_vn.hour
    if session == 'morning' and hour < MORNING_REPORT_HOUR:
        return
    if session == 'evening' and hour < EVENING_REPORT_HOUR:
        return

    all_pending = state.get('pending_articles', [])
    articles    = select_top_articles(all_pending)
    session_vn = 'SÁNG (Phiên Á)' if session == 'morning' else 'CHIỀU (Phiên Mỹ)'
    emoji = '🌅' if session == 'morning' else '🌆'

    print(f'Tạo báo cáo {session_vn} {today_str} ({len(articles)}/{len(all_pending)} tin chọn lọc)...')

    if not articles:
        print('Không có tin tức tích lũy, bỏ qua.')
        _log.info('SKIP_%s no_articles date=%s', session.upper(), today_str)
        state[state_key] = today_str
        return

    # Fetch giá thị trường (4 nguồn) + COT + vàng nhẫn SJC
    prices, macro = build_price_snapshot()
    cot_block     = build_cot_block(state)
    price_block   = format_price_for_prompt(prices, macro, cot_block) if prices or macro else None
    price_line    = format_price_for_telegram(prices, macro)
    gold_vnd      = build_gold_vnd_line(get_vn_gold_price())
    if gold_vnd:
        print(f'  {gold_vnd}')

    text = generate_session_report(articles, session, today_str, now_vn.month, gold_vnd, price_block, prices)
    if text == 'QUOTA_EXCEEDED':
        print('Hết quota Gemini, bỏ qua báo cáo.')
        _log.info('SKIP_%s quota_exceeded date=%s', session.upper(), today_str)
        return
    if not text:
        print('Gemini không trả về kết quả.')
        _log.info('SKIP_%s gemini_no_result date=%s', session.upper(), today_str)
        return

    gold_line_html = f'\n{gold_vnd}' if gold_vnd else ''
    price_line_html = f'\n💹 {price_line}' if price_line else ''

    # Bảng số liệu thuần (deterministic) — luôn đứng trước phần phân tích LLM
    quant_table = build_quant_table(prices)
    table_html  = f'<pre>{quant_table}</pre>\n\n' if quant_table else ''
    vol_alert   = build_volume_alert_line(prices)
    vol_html    = f'{vol_alert}\n\n' if vol_alert else ''

    header = (
        f'{emoji} <b>BÁO CÁO {session_vn.upper()} — {now_vn.strftime("%d/%m/%Y")}</b>\n'
        f'📰 {len(articles)}/{len(all_pending)} tin chọn lọc | '
        f'⏱ {now_vn.strftime("%H:%M")} (Giờ VN){gold_line_html}{price_line_html}\n\n'
    )
    msg = header + table_html + vol_html + text

    if send_telegram(msg):
        print(f'Gửi báo cáo {session_vn} OK')
        _log.info('SENT_%s articles=%d date=%s', session.upper(), len(articles), today_str)
        state[state_key] = today_str

        # File báo cáo đầy đủ: bảng số liệu + liên thị trường + COT + phân tích
        cross_lines = build_cross_asset_lines(prices)
        file_parts  = []
        if quant_table:
            file_parts.append('[BẢNG SỐ LIỆU]\n' + quant_table)
        if vol_alert:
            file_parts.append(vol_alert)
        if cross_lines:
            file_parts.append('[LIÊN THỊ TRƯỜNG]\n' + '\n'.join(f'  {c}' for c in cross_lines))
        if cot_block:
            file_parts.append(cot_block)
        file_parts.append(text)
        save_report_file('\n\n'.join(file_parts), session, today_str)

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
        _log.info('FAIL_%s telegram_error date=%s', session.upper(), today_str)

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

    # Hiệu suất tuần thực tính từ dữ liệu giá (cache — không fetch lại nếu đã có)
    prices, _ = build_price_snapshot()
    perf_block = build_weekly_perf_block(prices)
    wb_block   = fetch_wb_global_context(state)

    text = generate_weekly_report(weekly_reports, week_str, perf_block, wb_block)
    if text == 'QUOTA_EXCEEDED':
        print('Hết quota Gemini, bỏ qua tổng kết tuần.')
        return
    if text:
        perf_html = f'<pre>{perf_block}</pre>\n\n' if perf_block else ''
        msg = (
            f'🗓 <b>TỔNG KẾT THỊ TRƯỜNG HÀNG HÓA TUẦN {week_str}</b>\n\n'
            f'{perf_html}{text}\n\n'
            f'⏱ {now_vn.strftime("%d/%m/%Y %H:%M")} (Giờ VN)'
        )
        if send_telegram(msg):
            print('Gửi tổng kết tuần OK')
            state['last_weekly_summary'] = week_str
            file_text = (perf_block + '\n\n' + text) if perf_block else text
            save_report_file(file_text, 'weekly', now_vn.strftime('%Y-%m-%d'))
        else:
            print('Lỗi gửi tổng kết tuần')

# ── Main ──────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT or not GEMINI_API_KEY:
        print('Thiếu biến môi trường: TELEGRAM_TOKEN / TELEGRAM_CHAT / GEMINI_API_KEY')
        return

    (_ROOT / 'data').mkdir(parents=True, exist_ok=True)
    if not _log.handlers:
        _fh = logging.FileHandler(str(_ROOT / 'data' / 'decisions.log'), encoding='utf-8')
        _fh.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M'))
        _log.addHandler(_fh)

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
            matched = _matched_kw(a['title'], a['desc'])
            _log.info('ACCEPT [%s] "%s" | kw:%s', source, a['title'][:70], ','.join(matched[:3]))
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
