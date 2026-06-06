# Lệnh Thường Dùng — Giao Dịch Hàng Hóa

> **[CMD]** = gõ Terminal | **[AGENT]** = nhờ Claude làm

---

## 1. Chạy agent

| Lệnh | Loại | Làm gì | Khi nào dùng |
|---|---|---|---|
| `python commodity_agent.py` | [CMD] | Lấy tin & phân tích thị trường | Dùng hàng ngày |

## 2. Quản lý danh mục & prompt

| Lệnh | Loại | Làm gì |
|---|---|---|
| *"Thêm [vàng/dầu/đồng] vào theo dõi"* | [AGENT] | Thêm symbol vào danh sách |
| *"Cập nhật prompt phân tích hàng hóa"* | [AGENT] | Sửa file trong `prompts/` |

## 3. Dev & test

| Lệnh | Loại | Làm gì |
|---|---|---|
| `pip install -r requirements.txt` | [CMD] | Cài thư viện |
| `pytest tests/` | [CMD] | Chạy test suite |

---

**Output:** `last_commodity_news.json` (root) · `outputs/`
