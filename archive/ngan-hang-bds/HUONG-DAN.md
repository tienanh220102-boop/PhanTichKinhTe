# Hướng Dẫn Sử Dụng — Ngân Hàng BĐS

> Tài liệu cầm tay chỉ việc — không cần biết code, không cần rành terminal.

---

## 1. Dự án này làm gì? (giải thích bằng lời thường)

Công cụ này **tự động thu thập tin tức mới nhất** về ngân hàng và bất động sản Việt Nam (từ RSS, báo điện tử), đưa vào AI phân tích, rồi tạo ra một **báo cáo HTML đẹp** để nhà đầu tư BĐS phía Nam đọc nhanh mỗi sáng.

> Ví dụ: sáng nào cũng có báo cáo tổng hợp: lãi suất mới, chính sách ngân hàng, diễn biến BĐS — không cần đọc 10 trang báo khác nhau.

---

## 2. Chuẩn bị (làm 1 lần duy nhất)

1. **Copy file môi trường:**
   ```
   .env.example → .env
   ```
2. **Điền API key** vào `.env` (ít nhất `GEMINI_API_KEY`).
3. **Cài thư viện:**
   ```
   pip install -r requirements.txt
   ```

---

## 3. Hai nơi bạn thao tác

| Nơi | Là gì | Dấu hiệu |
|---|---|---|
| **Terminal** | Cửa sổ gõ lệnh máy tính | Bạn gõ `python banking_realestate_agent.py` |
| **Khung chat Claude** | Nơi trò chuyện với AI | Bạn nói tiếng Việt, AI tự làm |

**Mẹo:** Cứ nói chuyện với AI bằng tiếng Việt — AI đã được hướng dẫn cách vận hành dự án này.

---

## 4. Chạy lấy tin tức mới

**Cách dễ nhất:** Double-click file `run.bat`

**Hoặc Terminal:**
```
python banking_realestate_agent.py
```

Chờ khoảng 1-2 phút → báo cáo HTML xuất hiện trong thư mục `reports/`.

---

## 5. Đọc kết quả ở đâu?

| Mục đích | File / Nơi |
|---|---|
| **Báo cáo hàng ngày** | `reports/` — mở file HTML mới nhất bằng trình duyệt |
| **Log / debug** | `outputs/` — xem nếu có lỗi |
| **Dữ liệu thô** | `data/` — tin tức chưa qua xử lý |

---

## 6. Gặp trục trặc? (FAQ)

- **"Chưa set GEMINI_API_KEY"** → Mở `.env`, điền key vào dòng `GEMINI_API_KEY=...`
- **Báo cáo không có tin mới** → Kiểm tra kết nối mạng; nguồn RSS có thể tạm ngừng.
- **Muốn thêm nguồn tin** → Nói với AI: *"Thêm nguồn RSS [tên báo] vào dự án"*
- **Muốn thay đổi nội dung phân tích** → Nói với AI: *"Sửa prompt phân tích để tập trung vào [chủ đề]"*
- **Không nhớ làm gì tiếp** → Nói với AI: *"Dự án Ngân Hàng BĐS đang ở đâu rồi?"*

---

## 7. Tóm tắt 1 phút

1. Điền `GEMINI_API_KEY` vào `.env` (1 lần).
2. Double-click `run.bat` hoặc `python banking_realestate_agent.py`.
3. Đọc báo cáo HTML trong `reports/`.
4. Thấy sai / muốn thay đổi → nói với AI bằng tiếng Việt.
