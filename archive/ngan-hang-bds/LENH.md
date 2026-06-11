# Lệnh Thường Dùng — Ngân Hàng BĐS

> **[CMD]** = bạn gõ trong Terminal (xác định, chạy lại y hệt)
> **[AGENT]** = bước LLM, nhờ Claude làm (phân tích, đề xuất)
> Mẹo: Cứ nói tiếng Việt với Claude — agent tự biết dùng lệnh nào.

---

## 1. Chạy pipeline chính

| Lệnh | Loại | Làm gì | Khi nào dùng |
|---|---|---|---|
| `run.bat` | [CMD] | Chạy toàn bộ pipeline (Windows, double-click) | Dùng hàng ngày |
| `python banking_realestate_agent.py` | [CMD] | Chạy pipeline từ Terminal | Khi cần xem log trực tiếp |

---

## 2. Cài đặt & môi trường

| Lệnh | Loại | Làm gì |
|---|---|---|
| `pip install -r requirements.txt` | [CMD] | Cài thư viện Python |
| `cp .env.example .env` | [CMD] | Tạo file môi trường từ mẫu |

---

## 3. Kiểm tra & debug

| Lệnh | Loại | Làm gì | Khi nào dùng |
|---|---|---|---|
| `pytest tests/` | [CMD] | Chạy test suite | Sau khi sửa code |
| *"Xem log lần chạy cuối"* | [AGENT] | Agent đọc file mới nhất trong `outputs/` | Khi có lỗi |
| *"Thêm nguồn RSS [tên báo]"* | [AGENT] | Agent sửa danh sách feed trong script | Muốn thêm nguồn |

---

## 4. Quản lý prompts

| Lệnh | Loại | Làm gì |
|---|---|---|
| *"Xem prompt phân tích hiện tại"* | [AGENT] | Đọc file trong `prompts/` |
| *"Sửa prompt để tập trung vào [chủ đề]"* | [AGENT] | Cập nhật prompt, version mới |

---

## Ghi nhớ nhanh

- Output báo cáo: `reports/*.html`
- Dữ liệu trung gian: `data/`
- Log: `outputs/`
- Secrets: `.env` (không commit)
