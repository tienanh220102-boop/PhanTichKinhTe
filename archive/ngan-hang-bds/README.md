# Ngân Hàng BĐS

Thu thập tin tức ngân hàng & bất động sản → phân tích bằng Gemini AI → báo cáo HTML cho nhà đầu tư BĐS phía Nam.

> Mới bắt đầu? Đọc [HUONG-DAN.md](HUONG-DAN.md) — cầm tay chỉ việc, không cần biết code.
> Tra lệnh nhanh? Xem [LENH.md](LENH.md).

---

## Bắt đầu trong 30 giây

```bash
cp .env.example .env          # tạo file môi trường
# điền GEMINI_API_KEY vào .env
pip install -r requirements.txt
python banking_realestate_agent.py   # hoặc double-click run.bat
```

Báo cáo HTML xuất hiện trong `reports/` sau 1-2 phút.

---

## Hai loại bước — đừng nhầm

| Loại | Là gì | Ví dụ |
|---|---|---|
| **[CMD]** Lệnh python | Xác định, chạy lại y hệt | `python banking_realestate_agent.py` |
| **[AGENT]** Nhờ Claude | Bước phân tích, đề xuất | *"Thêm nguồn RSS mới"* |

---

## Bản đồ thư mục

```
raw/                    dữ liệu gốc bất biến
prompts/                prompt template cho Gemini AI
data/                   dữ liệu trung gian, cache
outputs/                log chạy
reports/                báo cáo HTML cuối cùng  ← ĐỌC Ở ĐÂY
scripts/                script phụ trợ
tests/                  test files
wiki/                   tài liệu nội bộ
workshop/               thử nghiệm sandbox
banking_realestate_agent.py   script chính
run.bat                 launcher Windows
.env                    API keys (không commit)
```

---

## Trạng thái hiện tại

Xem `wiki/log.md` để biết lịch sử chạy và thay đổi.
Hỏi Claude: *"Dự án Ngân Hàng BĐS đang ở đâu rồi?"*
