# Claude Notes — Giao Dịch Hàng Hóa

## Kiến trúc script

- **Entry point**: `scripts/commodity_agent.py` — agent chính, không có .bat (chạy tay: `python scripts/commodity_agent.py`)
- **State file**: `data/last_commodity_news.json` — lưu bài đã xử lý + lịch sử summary ngày/tuần
- **Kế thừa kiến trúc**: `banking_realestate_agent.py` được viết dựa trên codebase này

## Biến môi trường bắt buộc

- `GEMINI_API_KEY` — phân tích tin tức hàng hóa
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT` — gửi thông báo (tùy chọn nhưng là mục đích chính)

## Quirks quan trọng

- **Không có .bat file** — người dùng chạy tay hoặc qua GitHub Actions (mỗi 30 phút)
- **`MAX_ARTICLES = 40`** — tối đa bài đưa vào một báo cáo
- **RSS feeds tiếng Anh** (MarketWatch, BBC, AP, Guardian, Al Jazeera, CNBC, OilPrice, Mining.com) — khác với banking dùng RSS tiếng Việt
- **Thực tế khả dụng**: CNBC (403), AP Business (blocked), The Guardian (blocked) thường không fetch được; OilPrice + Mining.com + BBC là nguồn chính
- **Summary tuần**: có logic `last_weekly_summary` để gửi tổng kết cuối tuần
- **`from pathlib import Path` được thêm** vào khi chuyển sang scripts/ (ban đầu không có)

## GitHub Actions workflow

File: `.github/workflows/main.yml` — chạy mỗi 30 phút.

**Lưu ý quan trọng về paths:**
- Chạy: `python scripts/commodity_agent.py` (KHÔNG phải `python commodity_agent.py` ở root)
- Save state: `git add data/last_commodity_news.json` (KHÔNG phải root)
- `commodity_agent.py` dùng `_ROOT = Path(__file__).parent.parent` — từ `scripts/` → repo root ✓
- `data/` được tạo tự động bằng `mkdir(parents=True, exist_ok=True)` trong `save_state()`

## Lịch sử thay đổi

- 2026-06: Chuyển `commodity_agent.py` từ root sang `scripts/`; `STATE_FILE` → `data/`; thêm `from pathlib import Path`
- 2026-06: Thêm `mkdir(parents=True, exist_ok=True)` vào `save_state()` để tránh lỗi khi `data/` chưa tồn tại
- 2026-06: commit e7a8c2d — fix workflow: `python scripts/commodity_agent.py` + `git add data/last_commodity_news.json` (sau refactor commit 1094437 làm fail toàn bộ Actions runs)
