# Phân tích Kinh tế — Hướng dẫn vận hành cho Agent

Dự án tích hợp 2 mảng: **Giao Dịch Hàng Hóa Quốc Tế** + **Ngân Hàng & BĐS Phía Nam VN** — cùng kênh Telegram, báo cáo tách biệt.

---

## §0. Bảng vận hành nhanh

> ⚠️ **Hai entry point riêng** (theo `.github/workflows/main.yml` — nguồn chân lý):
> hàng hóa chạy `commodity_agent.py`, ngân hàng chạy `main_agent.py --banking-only`.
> Đừng sửa nhầm sang phần code hàng hóa cũ còn nằm trong `main_agent.py` (đã chết, không chạy).

| User muốn | Agent làm gì |
|---|---|
| "chạy agent hàng hóa" | `python scripts/commodity_agent.py` |
| "chạy agent ngân hàng" | `python scripts/main_agent.py --banking-only` (chạy thiếu cờ sẽ bị từ chối + nhắc dùng commodity_agent.py) |
| "xem pending hàng hóa" | Đọc `data/last_commodity_news.json` → trường `pending_articles` |
| "xem pending ngân hàng" | Đọc `data/last_banking_news.json` → trường `pending_articles` |
| "xem báo cáo hàng hóa" | `outputs/report_YYYY-MM-DD_morning.txt` hoặc `_evening.txt` |
| "xem báo cáo ngân hàng" | `outputs/banking_YYYY-MM-DD.txt` hoặc `.html` |
| "đổi giờ báo cáo hàng hóa" | `MORNING_REPORT_HOUR` / `EVENING_REPORT_HOUR` trong `commodity_agent.py` |
| "đổi giờ báo cáo ngân hàng" | `BANKING_DAILY_HOUR` trong `main_agent.py` |
| "đổi prompt hàng hóa" | `build_session_report_prompt()` trong `commodity_agent.py` |
| "đổi prompt ngân hàng" | `_banking_report_prompt()` trong `main_agent.py` |
| "đổi model Gemini" | Secret/env `GEMINI_MODEL` (mặc định `gemini-2.5-pro`); `GEMINI_FALLBACK_MODEL` (mặc định `gemini-2.5-flash`) tự dùng khi model chính lỗi/timeout/rỗng — không cần sửa code |
| "thêm nguồn RSS hàng hóa" | `RSS_FEEDS` trong `commodity_agent.py` |
| "thêm nguồn RSS ngân hàng" | `BANKING_FEEDS` trong `main_agent.py` |
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
   GitHub Actions cron */30 phút (.github/workflows/main.yml)
         │
         ├─► scripts/commodity_agent.py        ── mảng HÀNG HÓA
         │        ├── Thu thập → pending_articles (KHÔNG gọi Gemini)
         │        ├── 07:00 VN ── 🌅 Báo cáo Phiên Á       → Telegram + txt
         │        ├── 20:00 VN ── 🌆 Báo cáo Phiên Mỹ      → Telegram + txt
         │        └── Thứ 6 sau 20:00 ── 🗓 Tổng kết tuần  → Telegram + txt
         │
         └─► scripts/main_agent.py --banking-only  ── mảng NGÂN HÀNG & BĐS
                  ├── Thu thập → pending_articles (KHÔNG gọi Gemini)
                  ├── 17:00 VN ── 🏦 Báo cáo Ngày          → Telegram + html + txt
                  └── Thứ 6 sau 20:00 ── 🗓 Tổng kết tuần  → Telegram + txt
```

**Mỗi script tự gate theo giờ VN** (cron chạy 30 phút/lần nhưng chỉ tạo báo cáo đúng khung giờ).
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
| `scripts/commodity_agent.py` | **Entry point mảng HÀNG HÓA** (production) — quant engine, prompt, COT, giá yfinance |
| `scripts/main_agent.py` | **Entry point mảng NGÂN HÀNG** — luôn gọi với cờ `--banking-only`. ⚠️ Có code hàng hóa cũ (`COMMODITY_FEEDS`, `_commodity_report_prompt`) nhưng KHÔNG chạy trong production |
| `scripts/market_data.py` | Dữ liệu thị trường có cấu trúc: CFTC COT, EIA, FRED |
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
2. **Hai entry point** — hàng hóa = `commodity_agent.py`; ngân hàng = `main_agent.py --banking-only`. Khi sửa logic HÀNG HÓA phải sửa trong `commodity_agent.py` (code hàng hóa trong `main_agent.py` đã chết, sửa ở đó không có tác dụng).
3. **Workshop trước production** — thử nghiệm prompt mới trong `workshop/` trước khi sửa script production.
4. **Kế thừa, không đập lại** — mọi thay đổi phải build trên code đang chạy.
