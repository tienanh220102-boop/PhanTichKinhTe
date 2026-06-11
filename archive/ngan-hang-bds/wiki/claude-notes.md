# Claude Notes — Ngân Hàng BĐS

## Kiến trúc script

- **Entry point**: `scripts/banking_realestate_agent.py` — agent chính, chạy bằng `run.bat` hoặc `python scripts/banking_realestate_agent.py`
- **State file**: `data/last_banking_news.json` — lưu danh sách bài đã thấy để tránh gửi lại
- **Reports**: `outputs/banking_bds_YYYYMMDD.html` — báo cáo HTML hàng ngày
- **Word reports**: `outputs/BaoCao_NganHang_BDS_*.docx` — tạo bằng `scripts/tao_bao_cao_word.py` (template) và `scripts/tao_bao_cao_thuc.py` (bản thực)

## Biến môi trường bắt buộc

- `GEMINI_API_KEY` — nếu thiếu script thoát ngay, không chạy được
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT` — tùy chọn, dùng để gửi thông báo

## Quirks quan trọng

- **`GEMINI_API_KEY` free tier**: giới hạn 20 request/ngày → `MAX_ARTICLES = 5` (an toàn)
- **RSS feeds đã kiểm tra hoạt động 06/2026**: VnExpress BĐS/Kinh tế, Thanh Niên, VietnamNet, VOV
- **Báo cáo giờ 17:00 VN**: `DAILY_REPORT_HOUR = 17` — nếu script chạy liên tục, nó tự trigger lúc 17h
- **Script tự tạo `outputs/` nếu chưa có** (`.mkdir(exist_ok=True)`) — không cần tạo tay

## Lịch sử thay đổi

- 2026-06: Chuyển từ root sang `scripts/`; `reports/` → `outputs/`; state file → `data/`
- 2026-06: Tạo template Word (`tao_bao_cao_word.py`) và bản thực (`tao_bao_cao_thuc.py`) với dữ liệu RSS + WebSearch thực tế

## Dữ liệu thực tế đã thu thập (05/06/2026)

- Lãi suất huy động: BIDV/VCB/CTG ~5.9%; MB 7%; Cake/VPBank online 7.4%; HLBank 7.3%
- Lãi suất vay BĐS: Vietcombank 9.6% (6T), BIDV 9.7%, Techcombank 8.5–9.5%, NƠXH 4.6%
- Thị trường: căn hộ TP.HCM chạm 190 triệu/m²; nhà phố/nhà riêng giảm
- Sacombank thu hồi 500+ sổ đỏ Viva City (LDG, Đồng Nai)
