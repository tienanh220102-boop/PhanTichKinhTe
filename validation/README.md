# validation/ — Đo lường chất lượng & tín hiệu (chạy tay)

Tầng **kiểm chứng** của dự án: biến hệ thống từ "ra báo cáo" thành "ra báo cáo *đã đo*".
KHÔNG nằm trong cron (chạy khi cần). Khác `analysis/` (event study nhân quả) — ở đây đo
**edge dự báo của tín hiệu** và độ chính xác báo cáo.

## Script

| File | Vai trò |
|------|---------|
| `backtest_signals.py` | Backtest `classify_trend_signal` (MA20/MA50+RSI14): tái dùng ĐÚNG logic production, walk-forward không lookahead, đo forward-return theo lớp MUA/BÁN/GIỮ vs baseline drift |

Chạy: `python validation/backtest_signals.py` → lưu `outputs/validation_backtest_signals.txt`.

## Phát hiện lần đầu (period=5y, 10 symbol, ~12.080 phiên-tín hiệu)

**Tín hiệu rule-based gần như KHÔNG có edge dự báo; phía BÁN phản tác dụng.**

| Lớp | fwd5 mean | fwd10 | fwd20 | Đọc |
|-----|-----------|-------|-------|-----|
| Baseline (drift) | +0.20% | +0.38% | +0.76% | hàng hóa có xu hướng tăng nền |
| MUA | +0.33% | +0.77% | +1.07% | edge vượt baseline +0.1–0.4%, hit 52–53% — *biên rất mỏng* |
| BÁN | +0.40% | +0.66% | +1.10% | **sau tín hiệu BÁN giá vẫn TĂNG**; hit (fwd<0) chỉ 44–46% — *kém xu* |
| **Spread MUA−BÁN** | **−0.07%** | **+0.11%** | **−0.03%** | **≈0 → không tách được MUA khỏi BÁN** |

**Vì sao** (hợp lý kinh tế): tài sản hàng hóa có drift dương + hồi phục sau bán tháo. Tín
hiệu trend-following BÁN (giá < MA20 < MA50) hay khai hỏa **gần đáy cục bộ** → ngay sau đó
bật lên → BÁN đi ngược drift và ngược mean-reversion. Kết quả: short side là phần tệ nhất.

**Hệ quả đề xuất** (chưa áp dụng, chờ duyệt):
1. **Relabel** trong báo cáo: trình bày là **"Trạng thái xu hướng hiện tại"** (mô tả), KHÔNG
   phải **"Tín hiệu MUA/BÁN"** (ngụ ý dự báo) — vì dữ liệu cho thấy nó không dự báo được.
2. Hoặc **bỏ/giảm nhẹ phía BÁN** (gắn với đề xuất cũ "chặn BÁN khi 1D% > +2%").
3. Mọi cải tiến tín hiệu sau này PHẢI chạy lại backtest này — đã có thước đo.

## Phát hiện 2 — lọc vĩ mô (`backtest_macro_filter.py`)

Kiểm định: điều kiện hóa "Nghiêng tăng" theo chế độ vĩ mô (grounded methodology/01) có
tạo edge không? Giả thuyết: USD yếu (DXY<MA20) → long hàng hóa tốt hơn; real yield giảm
(DFII10↓) → long vàng tốt hơn.

| Lọc | chênh fwd5 | fwd10 | fwd20 | Đọc |
|-----|-----------|-------|-------|-----|
| H1: USD yếu vs mạnh (mọi hàng hóa) | +0,05% | +0,17% | +0,03% | **đúng dấu** nhưng noise-level |
| H2: real yield giảm vs tăng (vàng) | +0,24% | +0,98% | +0,29% | đúng dấu, fwd10 lớn nhưng *không nhất quán* |

**Kết luận (xác nhận trực giác "phân tích không in ra tiền"):**
- **Dấu đúng** → quan hệ vĩ mô trong methodology là THẬT ở mức *giải thích* (USD/real yield
  thực sự liên quan giá). Lý thuyết được validate như công cụ HIỂU.
- **Độ lớn noise-level + không nhất quán giữa horizon** → KHÔNG phải edge *dự báo* khai thác
  được. Số to nhất (vàng fwd10 +0,98%, n≈210, cửa sổ chồng lấn) gần như chắc là nhiễu.
- Bài học cốt lõi: **giải thích ≠ dự báo ≠ có lãi sau phí**. Ba ngưỡng khác nhau. Dự án sống ở
  ngưỡng *giải thích* — hợp lệ cho một sản phẩm bản tin/hiểu thị trường, KHÔNG phải máy in tiền.
  Thị trường dầu/vàng/FX quá hiệu quả để một hệ MA/RSI+lọc vĩ mô retail có alpha.

→ **Hệ quả định hướng**: ngừng săn edge (đúng), chuyển giá trị dự án sang *hiểu đúng + nhận
diện chế độ + tránh overtrading*. Tính năng trung thực nhất đã có sẵn: báo "dao động trong
biên độ bình thường, không driver rõ" thay vì bịa lý do.

## Caveat phương pháp (đã ghi trong báo cáo output)
- In-sample, **chưa trừ phí/spread**; cửa sổ forward **chồng lấn** → ý nghĩa thống kê bị
  thổi phồng (chênh lệch trên gần như nằm trong nhiễu — củng cố kết luận "không có edge rõ").
- Metric `hit` của lớp GIỮ hiện **không thông tin** (so với median của chính nó, ~50% theo
  định nghĩa) — bỏ qua; chỉ đọc MUA/BÁN/spread.

## Chunk kế tiếp (gợi ý)
- **Đo độ chính xác báo cáo**: log mọi lần `validate_report_directions` sửa dấu → tỷ lệ lỗi
  theo thời gian (chất lượng văn bản, tách khỏi edge tín hiệu).
- **Non-overlapping / theo nhóm tài sản**: tách edge theo từng nhóm (vàng có thể khác nông sản).
- **Có phí**: thêm chi phí giả định để xem edge MUA mỏng có sống nổi không.
</content>
