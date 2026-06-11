# Phân tích Kinh tế

Dự án hợp nhất 2 mảng (gộp từ Giao Dịch Hàng Hóa + Ngân Hàng BĐS, 11/06/2026):
- 🛢️ **Hàng hóa quốc tế**: giá + tin tức → phân tích AI → tín hiệu (`scripts/commodity_agent.py`)
- 🏦 **Ngân hàng & BĐS phía Nam VN**: tin tức → báo cáo 17h + weekly (`scripts/main_agent.py --banking-only`)

Tài liệu dự án Ngân Hàng BĐS cũ: [archive/ngan-hang-bds/](archive/ngan-hang-bds/)

> Mới bắt đầu? Đọc [HUONG-DAN.md](HUONG-DAN.md). Tra lệnh? Xem [LENH.md](LENH.md).

---

## Bắt đầu trong 30 giây

```bash
cp .env.example .env      # điền API key vào .env
pip install -r requirements.txt
python commodity_agent.py
```

---

## Bản đồ thư mục

```
raw/                        dữ liệu gốc bất biến
prompts/                    prompt phân tích hàng hóa
data/                       dữ liệu trung gian
last_commodity_news.json    trạng thái đã gửi (tự tạo, ở root)
outputs/                    báo cáo export
wiki/                       tài liệu nội bộ
workshop/                   thử nghiệm
commodity_agent.py          agent chính
.env                        API keys (không commit)
```
