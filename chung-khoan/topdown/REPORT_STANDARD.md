# CHUẨN VIẾT BÁO CÁO PHÂN TÍCH — checklist sống

> File này là "chuẩn" mà báo cáo forensic (`vn_deepdive_report.py`) phải bám theo. Gộp: nguyên
> tắc từ 3 cuốn sách viết báo cáo (Technical Writing, Business Communication for Success, Magenta
> Book — xem memory `reference_report_writing`) + đặc thù phân tích cổ phiếu + bài học thực chiến.
> Mỗi lần cải thiện báo cáo: chấm bản mới theo checklist cuối file, sửa lệch, cập nhật file này.

## 0. Người đọc (audience-first)
- Người đọc mặc định: **nhà đầu tư MỚI** — thông minh nhưng chưa quen thuật ngữ. Vì vậy mỗi phần
  có hộp **"💡 Đọc hiểu"** giải thích bằng lời, và luôn quy số ra "tỷ đồng", "%", "số ngày".
- Không giả định người đọc biết mã, biết ngành. Nêu bản chất kinh doanh trước khi mổ số.

## 1. Cấu trúc bắt buộc — FORM MEMO ĐẦU TƯ (đọc từ trên xuống hiểu được câu chuyện)
Báo cáo phải đọc như một MEMO có mạch, KHÔNG phải checklist kiểm toán rời rạc. Trên = câu
chuyện & quyết định; dưới = bằng chứng chi tiết.
1. **Header** — mã · tên · ngành · **giá · vốn hóa · khuyến nghị Vietcap (rating/target/upside)**
   lấy từ `company_info` (có nguồn, KHÔNG tự chế rating).
2. **Luận điểm đầu tư** — đoạn văn mạch lạc: DN là gì → quy mô/tăng trưởng → chất lượng lợi
   nhuận → tài chính/tự nuôi → cấu trúc tập đoàn → định giá → "Ròng lại: …" (through-line).
3. **Góc nhìn đầu tư** — ✅ Điểm hấp dẫn (bull) / ⚠️ Điều khiến e ngại (bear).
4. **Điều rút ra cho doanh nghiệp** — hàm ý "so-what": financials NGHĨA LÀ GÌ, DN phải làm gì.
   KHÔNG lặp số thô; nói hệ quả/hành động.
5. **Góc nhìn nhà đầu tư** — (a) khuyến nghị Vietcap có nguồn; (b) theo khẩu vị NĐT (tăng trưởng/
   giá trị/cổ tức/thận trọng); (c) 3 kịch bản bull/base/bear = ĐIỀU KIỆN, KHÔNG dự phóng số.
6. **Mấu chốt cần theo dõi** — thay cho "định hướng tương lai": KHÔNG suy đoán/dự phóng (chốt với
   user 21/07), chỉ nêu điều cần theo dõi CỤ THỂ có số (data-driven watch_items).
7. **Phạm vi & giả định** — LÀM gì, nguồn, r/g, KHÔNG cover gì (ethos + chống hiểu sai).
8. **── Phân tích chi tiết (bằng chứng) ──** — 8 mục silo (cấu trúc → … → tổng hợp) mỗi mục có
   số + bảng + hộp 💡.
9. **Disclaimer** cuối: không khuyến nghị, đối chiếu thuyết minh/kiểm toán.

GUARD false-positive (bài học): watch/cờ "phụ thuộc vốn" chỉ khi FCF âm thật (FPT ESOP + FCF
dương → không gắn); cờ "cổ tức tài trợ bằng vay" chỉ khi cổ tức TRỌNG YẾU ≥10% lãi ròng (HPG 37
tỷ = tượng trưng → không gắn); lens tăng trưởng: ≥20% rất hấp dẫn, 10–20% ổn định, <10% chậm.
Lớp diễn giải (luận điểm/takeaway/lens/scenario) sinh deterministic từ `dd.metrics` (số chốt các
mục tự nạp) — không LLM, không bịa.

## 2. Nguyên tắc viết (từ sách)
- **Executive summary lên đầu**, dài 1/10–1/20 báo cáo; người đọc skip thẳng xuống đây.
- **Heading cụ thể, không chung chung.** "Phân tích dòng tiền" ✗ → "Dòng tiền: nguồn tiền thật,
  đầu tư và khả năng tự nuôi" ✓. Heading tốt = biết nội dung mà chưa cần đọc thân.
- **Lists**: có câu dẫn kết thúc bằng `:`; các mục song song ngữ pháp; sau list có câu chốt.
- **Omit needless words** (Strunk & White). Mỗi hộp 💡 tối đa ~2 câu, mỗi câu 1 ý.
- **Ethos–Logos–Pathos**: cite nguồn (ethos); cấu trúc + bằng chứng số (logos); viết dễ gần,
  liên quan người đọc (pathos).
- **Analytical report**: facts + phân tích + kết luận. Tách rõ đâu là SỐ, đâu là NHẬN ĐỊNH, đâu
  là CỜ (theo từ khóa, cần kiểm chứng) — không trộn.

## 3. Đạo đức trình bày số & biểu đồ
- Trục biểu đồ cột **bắt đầu từ 0** (không bóp méo mức thay đổi). Đã đảm bảo trong `_svg_bars`
  bằng `min(vals+[0])`/`max(vals+[0])`.
- Số vô lý (chu kỳ vốn lưu động BĐS hàng nghìn ngày, tỷ lệ sở hữu >100%) → **BỎ + ghi chú**,
  KHÔNG hiển thị số rác (watchdog).
- Điểm số ngoại lai (Beneish/Altman hiệu chỉnh thị trường Mỹ) → luôn kèm "cờ tham khảo, không
  phán quyết"; nhắc đọc cùng dòng tiền, đừng tin mỗi điểm số.

## 4. Nguyên tắc forensic (đặc thù phân tích cổ phiếu)
- **Reporting quality ≠ earnings quality** (CFA L1 R25 / L2 m14). Cờ đỏ số 1: lãi > CFO kéo dài.
- Tách **lợi nhuận cốt lõi** khỏi khoản một lần (tài chính/đánh giá lại/thoái vốn).
- Phải thu/tồn kho phình nhanh hơn doanh thu → nghi ghi nhận sớm / hàng ế.
- **Tập đoàn**: soi cổ đông thiểu số (lãi hợp nhất có thật thuộc cổ đông mã không), công ty con
  niêm yết thì drill riêng. Thiểu số ÂM = công ty con đang lỗ (đừng mừng khi "lãi mẹ > hợp nhất").
- Ngân hàng → nhánh CAMELS, không áp forensic doanh nghiệp thường.
- **ĐIỀU TRA khi dữ liệu cho phép — KHÔNG để "nghi" chung chung.** Cờ nào chạm nghi ngờ mà data
  còn bóc sâu được thì phải bóc: vd "phải thu phình" → tách phải thu KHÁCH HÀNG (bán chịu) vs
  trả trước người bán vs phải thu khác + tính DSO (số ngày thu tiền) → kết luận CÓ BẰNG CHỨNG
  ("bán chịu +152% vs doanh thu +12%, DSO 11→26 ngày") thay vì "nghi ghi nhận sớm". Chỉ để lại
  cho thuyết minh phần thật sự cần nguồn ngoài (quá hạn/tập trung khách hàng). Hiệu chỉnh mức
  tuyệt đối: DSO vẫn thấp (<45 ngày) → "điểm theo dõi", đừng báo động (HPG DSO 26 vẫn lành mạnh).

## 5. Trung thực & giới hạn (bài học thực chiến)
- **Xác minh danh tính trước khi chạy** (mã VFS sàn VN = Chứng khoán Nhất Việt, KHÔNG phải VinFast).
- Nêu rõ dữ liệu KHÔNG có: đóng góp lợi nhuận từng công ty con, nội dung khoản phi cốt lõi, lịch
  đáo hạn nợ — đều nằm trong thuyết minh/nguồn ngoài, không API bóc sẵn.
- Ước lượng "khăn giấy" phải ghi rõ là ước lượng + giả định; sai thì rút lại (đã xảy ra: ước lượng
  drag VinFast −19k quá thấp so số SEC thật).
- Cite nguồn ngoài (SEC/US GAAP) khi mượn số ngoài hệ VN, và nêu khác biệt chuẩn kế toán.

## Checklist trước khi xuất báo cáo
- [ ] Có mục **Phạm vi & giả định** (nguồn, r/g, KHÔNG cover gì) ngay đầu?
- [ ] Executive summary (Kết luận nhanh) đủ verdict + cờ + điểm cộng?
- [ ] Heading từng phần **cụ thể**, nói được nội dung/câu hỏi phần đó trả lời?
- [ ] Mỗi phần có hộp 💡 ≤2 câu, gọt hết chữ thừa?
- [ ] Có mục **Tổng hợp & điều cần theo dõi** ở cuối (chốt đánh đổi + watch-items)?
- [ ] Số vô lý đã bị bỏ + ghi chú? Điểm số ngoại lai có cảnh báo tham khảo?
- [ ] Cờ theo từ khóa ghi "cần kiểm chứng"? Disclaimer không-khuyến-nghị ở cuối?
- [ ] Cite nguồn (VCI/CafeF/SEC…)? Danh tính mã đã xác minh?
