#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market data enrichment — dữ liệu thị trường có cấu trúc từ nguồn thẩm quyền.

Khung phân tích (theo hướng dẫn dữ liệu hàng hóa quốc tế):
  Tầng 1 — Vĩ mô & Dòng tiền  : CFTC COT, FRED (DXY, lãi suất)
  Tầng 2 — Năng lượng          : EIA (tồn kho dầu, sản lượng)
  Tầng 3 — Nông sản            : USDA WASDE (cung-cầu, ending stocks)
  Tầng 4 — Kim loại            : WGC (vàng), ICSG/INSG/ILZSG

Hàm đang có:
  fetch_cftc_cot()        — vị thế đầu cơ tuần (CFTC, miễn phí, không cần key)

Placeholder (cần thêm API key vào .env):
  fetch_eia_inventory()   — EIA_API_KEY
  fetch_fred_indicators() — FRED_API_KEY
"""
import csv
import io
import os
import requests

# ── CFTC Commitments of Traders ───────────────────────────────────────────────
# Dữ liệu công khai, không cần API key, cập nhật mỗi thứ Sáu ~15:30 ET.
# File deafut.txt: Legacy futures-only (không có header row, CSV với quoted fields).
# Nguồn: https://www.cftc.gov/MarketReports/CommitmentsofTraders/
_COT_URL = 'https://www.cftc.gov/dea/newcot/deafut.txt'

# Columns (sau khi parse đúng bằng csv.reader, field 0 là tên thị trường đã unquote):
# row[0]  = Market name
# row[2]  = Report date (YYYY-MM-DD)
# row[7]  = Open Interest
# row[8]  = NonCommercial Long  ← vị thế MUA của quỹ đầu cơ
# row[9]  = NonCommercial Short ← vị thế BÁN của quỹ đầu cơ
# row[10] = NonCommercial Spreading
_COT_NC_LONG_IDX  = 8
_COT_NC_SHORT_IDX = 9
_COT_DATE_IDX     = 2

# Từ khoá trong tên thị trường CFTC → tên tiếng Việt
# Chú ý: 'WHEAT-SRW' để lấy Soft Red Winter (tham chiếu chính), bỏ qua HRW/Spring
_COT_MARKETS = {
    'CRUDE OIL':  'Dầu WTI',
    'GOLD':       'Vàng XAU',
    'SILVER':     'Bạc',
    'COPPER':     'Đồng',
    'SOYBEANS':   'Đậu tương',
    'CORN':       'Ngô',
    'WHEAT-SRW':  'Lúa mì (SRW)',
}


def fetch_cftc_cot_structured() -> 'dict | None':
    """
    Tải báo cáo COT mới nhất từ CFTC (không cần API key) và trả về dạng số:
      {'date': 'YYYY-MM-DD', 'markets': {'Dầu WTI': net, 'Vàng XAU': net, ...}}
    net = NonCommercial Long − NonCommercial Short (vị thế ròng quỹ đầu cơ).
    Trả về None nếu không kết nối được hoặc parse thất bại.

    Ý nghĩa trading:
      net > 0 (NET LONG)  → quỹ đang đặt cược giá tăng (bullish signal)
      net < 0 (NET SHORT) → quỹ đang đặt cược giá giảm (bearish signal)
    """
    try:
        r = requests.get(
            _COT_URL, timeout=20,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; MarketAgent/1.0)'}
        )
        r.raise_for_status()

        reader       = csv.reader(io.StringIO(r.text))
        markets      = {}
        report_date  = ''
        seen_markets = set()

        for row in reader:
            if len(row) <= max(_COT_NC_LONG_IDX, _COT_NC_SHORT_IDX):
                continue

            market_raw = row[0].strip().upper()

            if not report_date:
                date_str = row[_COT_DATE_IDX].strip() if len(row) > _COT_DATE_IDX else ''
                if date_str and '-' in date_str:
                    report_date = date_str

            for key, vn_name in _COT_MARKETS.items():
                if key in market_raw and key not in seen_markets:
                    seen_markets.add(key)
                    try:
                        nc_long  = int(row[_COT_NC_LONG_IDX].strip().replace(' ', ''))
                        nc_short = int(row[_COT_NC_SHORT_IDX].strip().replace(' ', ''))
                        markets[vn_name] = nc_long - nc_short
                    except (ValueError, IndexError):
                        pass
                    break

        if markets:
            return {'date': report_date, 'markets': markets}

    except Exception as e:
        print(f'  [COT] Khong lay duoc du lieu CFTC: {e}')

    return None


def fetch_cftc_cot() -> 'str | None':
    """Chuỗi tóm tắt COT (giữ tương thích với main_agent.py)."""
    cot = fetch_cftc_cot_structured()
    if not cot:
        return None
    results = []
    for vn_name, net in cot['markets'].items():
        direction = 'NET LONG ↑' if net > 0 else 'NET SHORT ↓'
        results.append(f'{vn_name}: {direction} ({net:+,.0f})')
    date_tag = f' | Tuần {cot["date"]}' if cot['date'] else ''
    return (
        f'📊 VỊ THẾ QUỸ ĐẦU CƠ — CFTC COT{date_tag}\n'
        + '\n'.join(f'  • {item}' for item in results)
    )


# ── EIA Inventory (placeholder — cần EIA_API_KEY) ────────────────────────────
# https://www.eia.gov/opendata/ — đăng ký miễn phí tại eia.gov
def fetch_eia_inventory() -> 'str | None':
    """
    Lấy tồn kho dầu thô Mỹ tuần (EIA Weekly Petroleum Status Report).
    So sánh với trung bình 5 năm — lệch >2σ là tín hiệu trading mạnh.

    Cần: EIA_API_KEY trong .env (đăng ký miễn phí tại https://www.eia.gov/opendata/)
    """
    api_key = os.environ.get('EIA_API_KEY', '')
    if not api_key:
        return None
    # TODO: implement với EIA v2 API
    # https://api.eia.gov/v2/petroleum/stoc/wstk/data/
    return None


# ── FRED Indicators (placeholder — cần FRED_API_KEY) ─────────────────────────
# https://fred.stlouisfed.org/docs/api/fred/ — đăng ký miễn phí
def fetch_fred_indicators() -> 'str | None':
    """
    Lấy các chỉ số vĩ mô ảnh hưởng trực tiếp đến hàng hóa:
      - DXY (Trade Weighted Dollar Index) — nghịch chiều giá hàng hóa USD
      - 10Y Treasury Yield — ảnh hưởng đến vàng/bạc (real yield)
      - Fed Funds Rate — tác động chi phí carry trade

    Cần: FRED_API_KEY trong .env (đăng ký miễn phí tại https://fred.stlouisfed.org/)
    """
    api_key = os.environ.get('FRED_API_KEY', '')
    if not api_key:
        return None
    # TODO: implement với FRED API
    # Series: DTWEXBGS (DXY), DGS10 (10Y yield), FEDFUNDS
    return None
