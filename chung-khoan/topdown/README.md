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

## Báo cáo forensic chuyên sâu MỘT mã (`vn_deepdive`)

Đọc báo cáo tài chính "như giới phân tích" — soi bức tranh thực của kinh doanh, dòng tiền,
cân đối kế toán và các **thủ thuật làm đẹp sổ**. Nền lý luận: CFA L1 R25 + L2 m14 (Financial
Reporting Quality). Mỗi phần có callout **"💡 Đọc hiểu"** diễn giải bằng lời cho người mới.
Bảy phần: (1) **doanh nghiệp kinh doanh gì & cấu trúc tập đoàn** — mô tả bản chất KD + cổ đông
thiểu số + **danh sách công ty con/liên kết kèm tỷ lệ sở hữu** (nguồn CafeF, đánh dấu con niêm
yết); (2) bức tranh kinh doanh — tách lợi nhuận cốt lõi khỏi khoản một lần; (3) chất lượng lợi
nhuận — accruals, NI vs CFO, phải thu/tồn kho phình, **Beneish M-score**; (4) dòng tiền —
CFO/CFI/CFF, FCF, capex vs khấu hao, cổ tức có tiền thật không; (5) cân đối + chu kỳ vốn lưu
động DSO/DIO/DPO/CCC + độ phủ lãi vay; (6) **Altman Z''** (thị trường mới nổi) + **Piotroski
F-score**; (7) định giá. Ngân hàng → nhánh CAMELS riêng (không áp forensic thường).

```bash
python vn_deepdive_report.py FPT              # xuất reports/FPT_deepdive.md + .html
python vn_deepdive_report.py NVL --no-html    # chỉ Markdown
python vn_deepdive_report.py VNM --telegram   # kèm tóm tắt gọn qua Telegram
python vn_deepdive_report.py HPG --no-valuation  # bỏ tầng định giá (nhanh hơn)
```

Bản HTML tự chứa (theme sáng/tối, biểu đồ SVG doanh thu/LN/CFO). Beneish M-score và Altman Z
hiệu chỉnh cho thị trường Mỹ → chỉ là **cờ tham khảo**, không phải khuyến nghị. Watchdog: chu
kỳ vốn lưu động tự bỏ với DN thâm dụng tồn kho dài hạn (BĐS/xây dựng) để tránh số vô lý.

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
| `vn_valuation.py` | Định giá m23/m24/m13/m14 + peer_compare + CHUẨN HÓA CHU KỲ (rẻ cơ hội vs đáng đời) |
| `vn_topdown.py` | Vĩ mô → ngành |
| `vn_events.py` | Sự kiện DN + tin (cổ tức/ĐHCĐ/KQKD/hợp đồng) |
| `vn_report.py` | Pipeline tổng hợp + digest Telegram |
| `vn_group.py` | Danh sách công ty con & liên kết + tỷ lệ sở hữu (nguồn CafeF, keyless) |
| `vn_deepdive.py` | Tầng compute forensic một mã (accruals/Beneish/Altman/Piotroski/CCC) |
| `vn_deepdive_report.py` | Renderer Markdown + HTML + tóm tắt Telegram + CLI cho deep-dive |
| `vn_decision.py` | Báo cáo QUYẾT ĐỊNH: khung giá kịch bản (neo P/B lịch sử + mục tiêu Vietcap) + kế hoạch theo dõi N năm |
| `vn_portfolio.py` | Báo cáo DANH MỤC: tương quan + gom cụm rủi ro → chia đều + trần mã/cụm → vùng giá vào/thoát + cảnh báo đa dạng GIẢ |
| `vn_telegram.py` | Gửi tin Telegram (tự chunk >4096) |

_Công cụ hỗ trợ đọc, KHÔNG phải khuyến nghị mua/bán. Giả định r=13%, g=5% (chỉnh trong `vn_valuation.py`)._
