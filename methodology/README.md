# Methodology — Nền tảng lý thuyết vĩ mô của dự án

Thư mục này ghi lại **cơ sở lý thuyết kinh tế vĩ mô** cho khung phân tích mà agent
đang chạy. Mục đích: mỗi chỉ báo, mỗi tỷ lệ liên thị trường, mỗi chuỗi nhân quả
agent dùng trong prompt **phải truy được về một cơ chế kinh tế cụ thể**, không phải
quy tắc ngón tay cái. Khi sửa prompt hay thêm chỉ báo, đối chiếu thư mục này trước.

> Đây là tài liệu **tham chiếu ổn định** (khác `wiki/` là lớp tóm tắt nguồn tin do
> agent tự ingest, và khác `docs/` là site GitHub Pages). Code prompt là nơi *thực thi*;
> thư mục này là nơi *giải thích vì sao*.

## Nguồn

| # | Sách | Cấp độ | Dùng cho |
|---|------|--------|----------|
| A | OpenStax — *Principles of Macroeconomics 2e* | Nhập môn, ứng dụng | Cơ chế thị trường ngoại hối, CSTT, lạm phát, tiền–ngân hàng, thương mại |
| B | D. Romer — *Advanced Macroeconomics, 5e* | Cao học | Nền lý thuyết: Fisher, term structure, Taylor rule, ZLB, financial accelerator, Diamond–Dybvig |

Trích dẫn trong các doc ghi dạng `[A:Ch16]` (OpenStax chương 16) hoặc `[B:§12.2]`
(Romer mục 12.2). Phần lý thuyết tăng trưởng dài hạn (Solow/Ramsey/RBC, Romer Ch1–5)
**không áp dụng** cho một agent phân tích tin tức + giá tần suất cao và đã được bỏ qua
có chủ đích.

## Các doc

| File | Nội dung | Map vào code |
|------|----------|--------------|
| [01-vi-mo-gia-hang-hoa.md](01-vi-mo-gia-hang-hoa.md) | Động lực vĩ mô của giá hàng hóa: USD, lãi suất thực, kỳ vọng lạm phát, cấu trúc kỳ hạn; vì sao vàng ↔ real yield | `FRED_MACRO_SERIES`, `DXY`, `build_intermarket_block`, mục `[VĨ MÔ]` |
| [02-chinh-sach-tien-te.md](02-chinh-sach-tien-te.md) | Truyền dẫn CSTT: OMO → fed funds → phổ lãi suất → AD; Fisher; Taylor rule; ZLB/QE; độ trễ dài-biến thiên | RSS Fed/ECB/CB, đọc tin "đã quyết định vs kỳ vọng" |
| [03-ngan-hang-bds.md](03-ngan-hang-bds.md) | Mảng ngân hàng & BĐS VN: kênh tín dụng, financial accelerator, bank run, lệch tiền tệ FX, chuỗi Fed→USD/VND→NHNN | `_banking_report_prompt`, WB `FR.INR.LEND`, `FS.AST.PRVT.GD.ZS` |

## Nguyên tắc áp dụng (đọc trước khi dùng để phân tích)

1. **Lý thuyết là khung kỳ vọng, không phải tín hiệu giao dịch.** Quan hệ "real yield ↑ →
   vàng ↓" đúng *trung bình, dài hạn*; ngày bất kỳ có thể nhiễu bởi risk-off, dòng NHTW,
   tồn kho. Tín hiệu MUA/BÁN vẫn là rule-based (MA/RSI), KHÔNG suy ra trực tiếp từ lý thuyết vĩ mô.
2. **Độ trễ.** CSTT tác động thực sau 1–3 năm `[A:Ch15.5]`. Tin "Fed giữ lãi suất" tác động
   *kỳ vọng & tỷ giá ngay*, nhưng tác động lên cầu hàng hóa thực thì trễ → phân biệt 2 tầng khi viết.
3. **Đối xứng dấu phải đúng.** Các chuỗi nhân quả ở đây là nguồn để hậu kiểm
   `validate_report_directions` và `build_movement_facts` — nếu báo cáo nói ngược chiều lý thuyết
   mà không nêu lý do, đó là cờ đỏ.
</content>
</invoke>
