# Giao Dịch Hàng Hóa

Agent theo dõi giá & tin tức thị trường hàng hóa → phân tích AI → tín hiệu giao dịch.

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
