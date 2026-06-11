# Ngân Hàng BĐS — Hướng dẫn vận hành cho Agent

Dự án này: thu thập tin tức ngân hàng & bất động sản qua RSS/API → phân tích bằng Gemini AI → sinh báo cáo HTML cho nhà đầu tư BĐS phía Nam.

---

## §0. Bảng vận hành nhanh (đọc trước khi làm)

| User muốn | Agent làm gì |
|---|---|
| "chạy / lấy tin tức mới" | `python scripts\banking_realestate_agent.py` hoặc `run.bat` |
| "xem log / lần chạy cuối" | Xem file mới nhất trong `outputs/` |
| "thêm nguồn RSS mới" | Đọc `scripts/banking_realestate_agent.py` → tìm danh sách feed → thêm URL |
| "thay đổi prompt phân tích" | Đọc/sửa file trong `prompts/` |
| "chạy test" | `pytest tests/` |
| "wiki / ghi chú dự án" | Xem `wiki/` |
| "permissions Claude Code" | `.claude/settings.json` |

**Quy tắc cho agent:**
- Không tự sửa logic phân tích AI khi chưa hỏi user.
- API key lấy từ `.env`, tuyệt đối không hardcode.

---

## Kiến trúc pipeline

```
RSS feeds / API nguồn tin
  └── scripts/banking_realestate_agent.py
        ├── Thu thập tin tức
        ├── Phân tích bằng Gemini AI  ← prompt trong prompts/
        └── Sinh báo cáo HTML → outputs/
```

---

## Cấu trúc thư mục

| Thư mục/File | Mục đích |
|---|---|
| `banking_realestate_agent.py` | Script chính — toàn bộ pipeline |
| `run.bat` | Launcher Windows |
| `prompts/` | Prompt template cho Gemini AI (hiện rỗng) |
| `data/` | Dữ liệu trung gian, cache (hiện rỗng) |
| `raw/` | Dữ liệu thô gốc (bất biến) |
| `outputs/` | Báo cáo HTML, log chạy (hiện rỗng) |
| `scripts/` | Helper scripts tương lai (hiện rỗng) |
| `review/` | Tài liệu review (hiện rỗng) |
| `tests/` | Test files pytest (hiện rỗng) |
| `wiki/` | Tài liệu nội bộ, LLM wiki (hiện rỗng) |
| `workshop/` | Thử nghiệm sandbox (hiện rỗng) |
| `.claude/` | Cấu hình Claude Code: permissions |
| `.env` | API keys (không commit) |

---

## Quy tắc làm việc

1. **Secrets trong `.env`** — không commit, không hardcode.
2. **Prompt versioned** — mọi thay đổi prompt đặt trong `prompts/`.
3. **Workshop trước production** — thử ở `workshop/` trước khi sửa script chính.
4. **Wiki song song** — cập nhật `wiki/` khi thay đổi logic quan trọng.
5. **Kế thừa, không đập lại** — mọi thay đổi phải build trên code đang chạy.
