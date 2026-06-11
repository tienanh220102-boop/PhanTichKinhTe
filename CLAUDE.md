# Phân tích Kinh tế — Hướng dẫn vận hành cho Agent

Dự án tích hợp 2 mảng: **Giao Dịch Hàng Hóa Quốc Tế** + **Ngân Hàng & BĐS Phía Nam VN** — cùng kênh Telegram, báo cáo tách biệt.

---

## §0. Bảng vận hành nhanh

| User muốn | Agent làm gì |
|---|---|
| "chạy agent / lấy tin mới" | `python scripts/main_agent.py` |
| "xem pending hàng hóa" | Đọc `data/last_commodity_news.json` → trường `pending_articles` |
| "xem pending ngân hàng" | Đọc `data/last_banking_news.json` → trường `pending_articles` |
| "xem báo cáo hàng hóa" | `outputs/report_YYYY-MM-DD_morning.txt` hoặc `_evening.txt` |
| "xem báo cáo ngân hàng" | `outputs/banking_YYYY-MM-DD.txt` hoặc `.html` |
| "thay đổi giờ báo cáo" | Sửa các hằng số `*_HOUR` ở đầu `scripts/main_agent.py` |
| "thay đổi prompt" | Sửa hàm `_commodity_report_prompt()` hoặc `_banking_report_prompt()` |
| "thêm nguồn RSS" | Sửa `COMMODITY_FEEDS` hoặc `BANKING_FEEDS` trong `main_agent.py` |
| "chạy test" | `pytest tests/` |
| "permissions Claude Code" | `.claude/settings.json` |

**Quy tắc cho agent:**
- API key từ `.env`, không hardcode.
- State files trong `data/`, báo cáo trong `outputs/`, không ghi đè `raw/`.

---

## Kiến trúc pipeline

```
┌── RSS Quốc tế (8 nguồn) ───────────────────────────────────────────────┐
│   MarketWatch, BBC, AP, Guardian, Al Jazeera, CNBC, OilPrice, Mining   │
└────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌── RSS Việt Nam (5 nguồn) ──────────────────────────────────────────────┐
│   VnExpress KT, VnExpress BĐS, Thanh Niên, VietnamNet, VOV            │
└────────────────────────────────────────────────────────────────────────┘
         │
         ▼
   scripts/main_agent.py   (chạy mỗi 30 phút)
         │
         ├── Thu thập → pending_articles (KHÔNG gọi Gemini)
         │
         ├── 07:00 VN ── 🌅 Hàng hóa: Báo cáo Phiên Á     → Telegram + txt
         ├── 17:00 VN ── 🏦 Ngân hàng: Báo cáo Ngày        → Telegram + html + txt
         ├── 20:00 VN ── 🌆 Hàng hóa: Báo cáo Phiên Mỹ    → Telegram + txt
         └── Thứ 6 sau 20:00:
                 ├── 🗓 Hàng hóa: Tổng kết tuần            → Telegram + txt
                 └── 🗓 Ngân hàng: Tổng kết tuần           → Telegram + txt
```

**Lý do thiết kế:** Thu thập tin trước (không tốn Gemini) → đến giờ báo cáo: 1 Gemini call tổng hợp toàn bộ → chất lượng cao hơn, tiết kiệm quota (≈3 calls/ngày, ≈5 calls thứ 6).

---

## Nội dung báo cáo

| Báo cáo | Nội dung |
|---|---|
| 🌅🌆 Hàng hóa (Phiên Á / Phiên Mỹ) | Vĩ mô · Tín hiệu MUA/BÁN/GIỮ · Ngưỡng giá · Rủi ro — 4 nhóm: Năng lượng / Kim loại quý / Nông sản / Kim loại CN |
| 🏦 Ngân hàng & BĐS | Xu hướng lãi suất · Tín dụng BĐS · Điểm ngân hàng nổi bật · Khuyến nghị NĐT phía Nam |
| 🗓 Tổng kết tuần | Cả 2 mảng — gửi riêng biệt, thứ 6 sau 20:00 |

---

## Cấu trúc thư mục

| Thư mục/File | Mục đích |
|---|---|
| `scripts/main_agent.py` | **Entry point chính** — chạy cả 2 mảng |
| `scripts/market_data.py` | Dữ liệu thị trường có cấu trúc: CFTC COT, EIA, FRED |
| `scripts/commodity_agent.py` | Script hàng hóa đơn lẻ (đã thay bởi main_agent.py) |
| `data/last_commodity_news.json` | State hàng hóa: seen, pending, report timestamps |
| `data/last_banking_news.json` | State ngân hàng: seen, pending, report timestamps |
| `outputs/report_DATE_morning.txt` | Báo cáo hàng hóa phiên sáng |
| `outputs/report_DATE_evening.txt` | Báo cáo hàng hóa phiên chiều |
| `outputs/banking_DATE.html` | Báo cáo ngân hàng dạng HTML |
| `outputs/banking_DATE.txt` | Báo cáo ngân hàng dạng text |
| `prompts/` | Prompt templates (tham chiếu) |
| `raw/` | Dữ liệu thô gốc (bất biến) |
| `.env` | API keys (không commit) |

## Nguồn dữ liệu thẩm quyền (khung phân tích 4 tầng)

| Tầng | Tổ chức | Dữ liệu | Cách tích hợp |
|---|---|---|---|
| Vĩ mô & Dòng tiền | CFTC | COT Report — vị thế đầu cơ | `market_data.fetch_cftc_cot()` — tự động, không cần key |
| Vĩ mô & Dòng tiền | FRED (St. Louis Fed) | DXY, lãi suất Treasury | `FRED_API_KEY` tùy chọn |
| Năng lượng | EIA (.gov) | Tồn kho dầu thô, sản lượng | RSS feed + `EIA_API_KEY` tùy chọn |
| Nông sản | USDA (.gov) | WASDE, tiến độ mùa vụ | RSS feed (keyword: `wasde`) |
| Kim loại quý | WGC (.org) | Cầu vàng, ETF flows, NHTW | RSS feed `WGC Gold Insights` |
| Kim loại CN | ICSG/INSG/ILZSG | Cán cân cung-cầu đồng/niken/kẽm | Theo dõi qua Mining.com RSS |

**Nguyên tắc phân tích tồn kho:** Khi mức tồn kho thực tế lệch khỏi trung bình 5 năm >2 độ lệch chuẩn → tín hiệu trading lớn. Prompt Gemini đã được hướng dẫn nguyên tắc này.

---

## Quy tắc làm việc

1. **Secrets trong `.env`** — không commit, không hardcode.
2. **Entry point duy nhất** — luôn chạy `main_agent.py`, không chạy `commodity_agent.py` trong production.
3. **Workshop trước production** — thử nghiệm prompt mới trong `workshop/` trước khi sửa main_agent.
4. **Kế thừa, không đập lại** — mọi thay đổi phải build trên code đang chạy.
