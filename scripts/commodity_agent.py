#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commodity Market Report Agent
- Đọc RSS tin tức thế giới mỗi 30 phút, thu thập bài liên quan hàng hóa
- Tạo báo cáo tổng hợp 2 lần/ngày: 7:00 (phiên Á) và 20:00 (phiên Mỹ)
- Báo cáo: phân tích vĩ mô, tín hiệu giao dịch, mức giá, rủi ro
- Tổng kết tuần vào thứ 6 sau 20:00
"""
import json, os, time, hashlib, logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
MAX_ARTICLES        = 40  # tối đa bài đưa vào một báo cáo


_log = logging.getLogger('commodity')
_log.setLevel(logging.INFO)
_log.propagate = False
_fh = logging.FileHandler(str(_ROOT / 'data' / 'decisions.log'), encoding='utf-8')
_fh.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M'))
_log.addHandler(_fh)

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
    """Giá + kỹ thuật từ Yahoo Finance: current price, Δ1D%, 5D range (High/Low), MA20."""
    try:
        import yfinance as yf
        symbols = list(YFINANCE_SYMBOLS.values())
        raw = yf.download(symbols, period='1mo', progress=False, auto_adjust=True)
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
                prices[name] = {
                    'value':   round(cur, 4),
                    'chg_pct': round((cur - prev) / prev * 100, 2),
                    'low5d':   round(float(low.iloc[-n5:].min()), 4),
                    'high5d':  round(float(high.iloc[-n5:].max()), 4),
                    'ma20':    round(float(close.iloc[-n20:].mean()), 4),
                }
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
    """Macro indicators từ FRED (miễn phí, không cần key)."""
    macro = {}
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
                    f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}',
                    timeout=15,
                )
                rows = r.text.strip().split('\n')[1:]
                valid = [l for l in rows if ',' in l and not l.split(',')[1].strip() == '.']
                obs = [{'date': l.split(',')[0], 'value': l.split(',')[1].strip()} for l in valid[-3:]]
                obs.reverse()
            if obs:
                macro[series_id] = {'label': label, 'value': obs[0]['value'], 'date': obs[0]['date']}
        except Exception as e:
            print(f'  FRED {series_id} lỗi: {e}')
    print(f'  FRED: {len(macro)}/{len(FRED_MACRO_SERIES)} series OK')
    return macro


def build_price_snapshot():
    """
    Gộp giá từ 4 nguồn. Thứ tự ưu tiên: yfinance → twelvedata → alphavantage.
    FRED là additive (macro, không trùng với giá futures).
    Returns (prices_dict, macro_dict).
    """
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
    return combined, macro


def format_price_for_prompt(prices, macro):
    """Block giá kỹ thuật + EIA supply chain đầy đủ cho Gemini prompt."""

    def line(name, label, pfmt='.2f', unit=''):
        e = prices.get(name)
        if not e:
            return f'  {label}: N/A'
        v   = e['value']
        chg = e.get('chg_pct')
        l5, h5, ma = e.get('low5d'), e.get('high5d'), e.get('ma20')
        s = f'  {label}: ${v:{pfmt}}{unit}'
        if chg is not None:
            s += f' ({chg:+.2f}%)'
        if l5 and h5:
            s += f'  |  5D: ${l5:{pfmt}}–${h5:{pfmt}}'
        if ma:
            arrow = '↑' if v > ma else '↓'
            s += f'  |  MA20: ${ma:{pfmt}} {arrow}'
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
    out.append('[NÔNG SẢN]')
    out.append(line('Corn',    'Ngô        ', '.2f', '/bushel'))
    out.append(line('Wheat',   'Lúa mì     ', '.2f', '/bushel'))
    out.append(line('Soybean', 'Đậu tương  ', '.2f', '/bushel'))
    out.append('[VĨ MÔ]')
    dxy = prices.get('DXY')
    if dxy:
        v, chg, ma = dxy['value'], dxy.get('chg_pct'), dxy.get('ma20')
        s = f'  DXY: {v:.2f}'
        if chg is not None:
            s += f' ({chg:+.2f}%)'
        if ma:
            s += f'  |  MA20: {ma:.2f} {"↑" if v > ma else "↓"}'
        out.append(s)
    for sid in ['DGS10', 'CPIAUCSL', 'DEXUSEU']:
        if sid in macro:
            d = macro[sid]
            out.append(f'  {d["label"]}: {d["value"]} ({d["date"]})')

    out.append('→ Hỗ trợ = đáy 5D hoặc MA20 (lấy số cao hơn); Kháng cự = đỉnh 5D; ↑ = trên MA20, ↓ = dưới MA20')
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

def build_session_report_prompt(articles, session, date_str, month, gold_vnd_line=None, price_block=None):
    articles_text = '\n'.join([
        f'{i+1}. [{a["source"]}] {a["title"]}\n   {a["desc"][:300]}'
        for i, a in enumerate(articles[:MAX_ARTICLES])
    ])
    context = 'tin tức qua đêm và đầu phiên Á' if session == 'morning' else 'tin tức trong ngày và đầu phiên Mỹ'
    session_vn = 'PHIÊN SÁ (07:00 VN)' if session == 'morning' else 'PHIÊN MỸ (20:00 VN)'

    price_note = f'\n{price_block}\n' if price_block else ''

    vnd_note = ''
    if gold_vnd_line:
        vnd_note = (
            f"\nGIÁ VÀNG VIỆT NAM HIỆN TẠI: {gold_vnd_line}\n"
            "→ Khi phân tích mục KIM LOẠI QUÝ, đề cập thêm giá vàng nhẫn trong nước để người đọc dễ hình dung.\n"
        )

    seasonal = get_seasonal_context(month)
    seasonal_note = f'\n{seasonal}\n' if seasonal else ''

    return f"""Bạn là chuyên gia phân tích thị trường hàng hóa toàn cầu với kinh nghiệm giao dịch thực tế.
Dưới đây là {len(articles)} {context} ngày {date_str}:{price_note}{vnd_note}{seasonal_note}

{articles_text}

Hãy viết BÁO CÁO PHÂN TÍCH {session_vn} bằng TIẾNG VIỆT theo đúng cấu trúc sau (không thêm gì ngoài cấu trúc này):

🌍 VĨ MÔ & TIN TỨC NỔI BẬT
[Tóm tắt 2-3 yếu tố vĩ mô/địa chính trị quan trọng nhất tác động đến thị trường hàng hóa hôm nay]

🛢️ NĂNG LƯỢNG — Dầu WTI/Brent, Khí tự nhiên
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: Hỗ trợ [đáy 5D hoặc MA20 từ bảng giá — dùng số cụ thể] | Kháng cự [đỉnh 5D từ bảng giá — dùng số cụ thể]
Phân tích: [2-3 câu phân tích dựa trên tin tức và dữ liệu kỹ thuật]
Rủi ro: [rủi ro chính cần theo dõi]

🥇 KIM LOẠI QUÝ — Vàng (XAU/USD), Bạc
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: Hỗ trợ [đáy 5D hoặc MA20 từ bảng giá — dùng số cụ thể] | Kháng cự [đỉnh 5D từ bảng giá — dùng số cụ thể]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

🌾 NÔNG SẢN — Ngô, Đậu tương, Lúa mì
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: [đáy/đỉnh 5D từ bảng giá nếu có, nếu không có dữ liệu ghi "N/A"]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

🔩 KIM LOẠI CÔNG NGHIỆP — Đồng, Nhôm, Niken
Xu hướng: [TĂNG / GIẢM / SIDEWAY]
Tín hiệu: [MUA / BÁN / GIỮ]
Ngưỡng giá: [đáy/đỉnh 5D từ bảng giá nếu có, nếu không có dữ liệu ghi "N/A"]
Phân tích: [2-3 câu phân tích dựa trên tin tức]
Rủi ro: [rủi ro chính cần theo dõi]

📋 KHUYẾN NGHỊ PHIÊN
[2-3 khuyến nghị cụ thể, actionable cho phiên giao dịch này — ưu tiên thực tế]

⚠️ THEO DÕI PHIÊN
[2-3 sự kiện/dữ liệu quan trọng cần theo dõi trong phiên]

Lưu ý: Nếu không đủ tin về một nhóm, đánh giá dựa trên bối cảnh thị trường chung. Viết ngắn gọn, rõ ràng, chuyên nghiệp."""

def generate_session_report(articles, session, date_str, month, gold_vnd_line=None, price_block=None):
    if not articles:
        return None
    prompt = build_session_report_prompt(articles, session, date_str, month, gold_vnd_line, price_block)
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
        _log.info('SKIP_%s already_sent date=%s', session.upper(), today_str)
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
        _log.info('SKIP_%s no_articles date=%s', session.upper(), today_str)
        state[state_key] = today_str
        return

    # Fetch giá thị trường (4 nguồn) + vàng nhẫn SJC
    prices, macro = build_price_snapshot()
    price_block   = format_price_for_prompt(prices, macro) if prices or macro else None
    price_line    = format_price_for_telegram(prices, macro)
    gold_vnd      = build_gold_vnd_line(get_vn_gold_price())
    if gold_vnd:
        print(f'  {gold_vnd}')

    text = generate_session_report(articles, session, today_str, now_vn.month, gold_vnd, price_block)
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
    header = (
        f'{emoji} <b>BÁO CÁO {session_vn.upper()} — {now_vn.strftime("%d/%m/%Y")}</b>\n'
        f'📰 Tổng hợp {min(len(articles), MAX_ARTICLES)} tin tức | '
        f'⏱ {now_vn.strftime("%H:%M")} (Giờ VN){gold_line_html}{price_line_html}\n\n'
    )
    msg = header + text

    if send_telegram(msg):
        print(f'Gửi báo cáo {session_vn} OK')
        _log.info('SENT_%s articles=%d date=%s', session.upper(), min(len(articles), MAX_ARTICLES), today_str)
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
