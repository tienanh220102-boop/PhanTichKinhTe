# Claude Notes — Giao Dịch Hàng Hóa

## Kiến trúc script

- **Entry point**: `scripts/commodity_agent.py` — agent chính, không có .bat (chạy tay: `python scripts/commodity_agent.py`)
- **State file**: `data/last_commodity_news.json` — lưu bài đã xử lý + lịch sử summary ngày/tuần
- **Kế thừa kiến trúc**: `banking_realestate_agent.py` được viết dựa trên codebase này

## Biến môi trường bắt buộc

- `GEMINI_API_KEY` — phân tích tin tức hàng hóa
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT` — gửi thông báo (tùy chọn nhưng là mục đích chính)

## Quirks quan trọng

- **Không có .bat file** — người dùng chạy tay hoặc qua Task Scheduler Windows
- **`MAX_ARTICLES = 2`** — conservative hơn banking (2 vs 5) để tiết kiệm Gemini quota
- **RSS feeds tiếng Anh** (MarketWatch, BBC, AP, Guardian, Al Jazeera, CNBC, OilPrice, Mining.com) — khác với banking dùng RSS tiếng Việt
- **Summary tuần**: có logic `last_weekly_summary` để gửi tổng kết cuối tuần
- **`from pathlib import Path` được thêm** vào khi chuyển sang scripts/ (ban đầu không có)

## Lịch sử thay đổi

- 2026-06: Chuyển `commodity_agent.py` từ root sang `scripts/`; `STATE_FILE` → `data/`; thêm `from pathlib import Path`
- 2026-06: Thêm `mkdir(parents=True, exist_ok=True)` vào `save_state()` để tránh lỗi khi `data/` chưa tồn tại
