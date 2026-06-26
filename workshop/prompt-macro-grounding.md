# Workshop — Nhúng insight vĩ mô vào prompt (theo methodology/)

Thử nghiệm trước production (rule #3). Mục tiêu: biến lý thuyết trong `methodology/`
thành hướng dẫn prompt **plain-language, tối thiểu token**, không thêm jargon, không
đụng logic rule-based (MA/RSI) hay hậu kiểm sign-flip.

Nguyên tắc đã giữ: chỉ thêm 4 mẩu; mỗi mẩu truy về 1 doc methodology; diễn đạt cho
người đọc không chuyên (không nhắc DFII10/real yield/Taylor...).

---

## Hàng hóa — `commodity_agent.py :: build_session_report_prompt`

### (a) Hai kịch bản vàng — mục 🥇 KIM LOẠI QUÝ
Nguồn: [methodology/01 §2](../methodology/01-vi-mo-gia-hang-hoa.md) — "real yield giảm" có
2 nguyên nhân hàm ý khác nhau. Diễn đạt plain-language (không nói "real yield"):

- **Trước:** `…gắn tin tức + tác động đồng USD; bạc đang rẻ hay đắt…`
- **Sau:** thêm: nếu vàng tăng, phân biệt *vì lo lạm phát* (phòng thủ) hay *vì kỳ vọng
  Fed nới lỏng / USD yếu* (theo dòng tiền) — hai lý do khác nhau, nói rõ lý do nào.

### (b) Độ trễ chính sách — khối QUAN TRỌNG (cạnh TẦNG DỮ LIỆU)
Nguồn: [methodology/02 §5](../methodology/02-chinh-sach-tien-te.md) — CSTT tác động cầu
thực sau 1–3 năm; tin chính sách chỉ tác động *kỳ vọng/tỷ giá ngay*.

- Thêm bullet: quyết định Fed/NHTW tác động **đồng USD & kỳ vọng NGAY**, nhưng tác động
  **cầu hàng hóa thực thì TRỄ (1–3 năm)** → cấm viết "Fed hạ lãi → cầu dầu tăng ngay".

---

## Ngân hàng — `main_agent.py :: _banking_report_prompt`

### (c) Thiếu thanh khoản vs mất khả năng thanh toán — mục 🏦
Nguồn: [methodology/03 §3](../methodology/03-ngan-hang-bds.md) — insolvency vs illiquidity
đòi phản ứng chính sách khác nhau.

- Thêm: khi tin về thanh khoản/nợ xấu ngân hàng, phân biệt **thiếu thanh khoản tạm thời**
  (cần bơm thanh khoản, ít nghiêm trọng) với **mất khả năng thanh toán / nợ xấu cơ cấu**
  (vốn chủ âm — nghiêm trọng hơn).

### (d) Hỏi kênh lây lan trước khi báo động hệ thống — mục ⚠️
Nguồn: [methodology/03 §4](../methodology/03-ngan-hang-bds.md) — sự cố vi mô thường tự ổn
định; chỉ thành hệ thống khi có kênh lây lan.

- Thêm: trước khi coi một sự cố ngân hàng đơn lẻ là rủi ro hệ thống, hỏi **có kênh lây lan
  cụ thể không** (sở hữu chéo/liên đới, bán tháo tài sản, mất niềm tin lan rộng). Không có
  kênh rõ → không thổi thành rủi ro toàn ngành.

---

## KHÔNG đưa vào (cân nhắc rồi loại)
- **Taylor rule / behind-the-curve** cho prompt hàng hóa: thêm jargon, giá trị biên thấp,
  tốn token — giữ ở methodology làm khung tư duy, không nhồi vào báo cáo người-không-chuyên.
- **Sửa hậu kiểm** (`validate_report_directions`, `build_movement_facts`): các insight này
  là *diễn giải*, không phải kiểm dấu số — để nguyên, tránh rủi ro.

## Kiểm thử
`python tests/test_quant_smoke.py` sau khi áp dụng — đảm bảo prompt build không vỡ.
</content>
