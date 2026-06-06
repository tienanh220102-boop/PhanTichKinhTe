# Hướng Dẫn Sử Dụng — Giao Dịch Hàng Hóa

> Tài liệu cầm tay chỉ việc — không cần biết code.

---

## 1. Dự án này làm gì?

Công cụ này **theo dõi tự động giá và tin tức thị trường hàng hóa** (vàng, dầu, nông sản…), phân tích bằng AI để đưa ra tín hiệu giao dịch.

---

## 2. Chuẩn bị (làm 1 lần)

1. Copy: `.env.example` → `.env`, điền API key
2. Cài thư viện: `pip install -r requirements.txt`

---

## 3. Chạy agent

```
python commodity_agent.py
```

---

## 4. Kết quả ở đâu?

| Mục đích | File / Nơi |
|---|---|
| **Tin tức & phân tích mới nhất** | `data/last_commodity_news.json` |
| **Báo cáo export** | `outputs/` |

---

## 5. FAQ

- **Thêm hàng hóa theo dõi** → Nói với AI: *"Thêm [vàng/dầu/đồng] vào danh sách theo dõi"*
- **Thay đổi prompt phân tích** → Nói với AI: *"Cập nhật prompt hàng hóa"*
- **Không biết làm gì** → Hỏi AI: *"Dự án Hàng Hóa đang ở đâu?"*
