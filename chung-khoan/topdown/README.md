# Phân tích Top-Down TTCK Việt Nam (định lượng, keyless)

Bộ phân tích "như giới phân tích" — độc lập với pipeline screener+LLM ở thư mục cha.
KHÔNG dùng LLM, KHÔNG cần API key. Chỉ cần `requests`, `pandas`, `numpy` (đã có trong
`../requirements.txt`). Nguồn dữ liệu: API công khai VCI (Vietcap).

## Luồng (từ tổng quát đến chi tiết, nền CFA L2)

1. **Nhịp thị trường** (`vn_topdown.market_pulse`, m37) — VN-Index/HNX/UPCoM: trend, RSI, %biến động.
2. **Vũ trụ thanh khoản** (`liquid_universe`) — lọc mã giao dịch sôi động nhất theo GTGD.
3. **Xếp hạng ngành** (`sector_ranking`, m23) — median P/E, P/B, ROE theo ngành ICB → ngành trọng điểm.
4. **Định giá mã trọng điểm** (`vn_valuation.assess`, m23/m24/m13/m14) — percentile lịch sử +
   justified P/B (residual income) + CAMELS ngân hàng + cờ value-trap. Drill rải đều theo ngành (round-robin).
5. **Sự kiện & tin** (`vn_events`) — cổ tức/ĐHCĐ/phát hành + tin KQKD/hợp đồng.

## Chạy

```bash
python vn_report.py                      # mặc định: liquid 120, drill 15, có sự kiện
python vn_report.py --telegram           # gửi digest tất định (cần TELEGRAM_TOKEN/TELEGRAM_CHAT)
python vn_report.py --symbols FPT,VCB     # chỉ drill danh sách chỉ định
python vn_report.py --peers              # so peer ngành (tốn API hơn)
python vn_report.py --per-sector 2       # chặn tối đa 2 mã/ngành khi drill
```

Báo cáo Markdown lưu ở `reports/YYYY-MM-DD_phantich.md`. Digest Telegram tất định (không LLM):
nhịp thị trường + ngành trọng điểm + cảnh báo rủi ro + mã rẻ + cổ tức sắp chốt + KQKD.

## Module

| File | Vai trò |
|------|---------|
| `vn_data.py` | Giá/chỉ số OHLCV (chịu lỗi từng batch) |
| `vn_fundamentals.py` | Tỷ số định giá + báo cáo tài chính (VCI iq) |
| `vn_sectors.py` | Bản đồ ngành ICB 4 cấp + peers |
| `vn_valuation.py` | Định giá m23/m24/m13/m14 + peer_compare (lọc rác) |
| `vn_topdown.py` | Vĩ mô → ngành |
| `vn_events.py` | Sự kiện DN + tin (cổ tức/ĐHCĐ/KQKD/hợp đồng) |
| `vn_report.py` | Pipeline tổng hợp + digest Telegram |
| `vn_telegram.py` | Gửi tin Telegram (tự chunk >4096) |

_Công cụ hỗ trợ đọc, KHÔNG phải khuyến nghị mua/bán. Giả định r=13%, g=5% (chỉnh trong `vn_valuation.py`)._
