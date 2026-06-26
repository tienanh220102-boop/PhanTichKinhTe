# 03 — Ngân hàng & BĐS phía Nam Việt Nam

Nền lý thuyết cho `main_agent.py --banking-only` (`_banking_report_prompt`), bộ chỉ báo WB
(`FR.INR.LEND` lãi suất cho vay, `FS.AST.PRVT.GD.ZS` tín dụng tư nhân %GDP) và chuỗi nhân
quả "Fed/ECB → USD/VND → NHNN" đã có trong prompt.

---

## 1. Kênh truyền dẫn tiền tệ vào tín dụng & BĐS

Từ [doc 02](02-chinh-sach-tien-te.md): CSTT → lãi suất → đầu tư & vay tiêu dùng. BĐS là
**big-ticket, vay nợ cao** nên cực nhạy với lãi suất `[A:Ch15.4]`:
```
NHNN nới/siết ──► lãi vay (FR.INR.LEND) ──► chi phí vốn vay mua nhà ──► cầu BĐS phía Nam
              ──► room/tăng trưởng tín dụng (FS.AST.PRVT.GD.ZS) ──► nguồn vốn cho chủ đầu tư
```
- Lãi suất tăng → khoản trả góp tăng → cầu nhà giảm; đồng thời chủ đầu tư khó huy động vốn.
- Đây là kênh trực tiếp; prompt banking đã đúng khi gắn nhãn tín dụng `NỚI LỎNG/THẮT CHẶT/KHÔNG ĐỔI`.

**Kênh tín dụng & financial accelerator** `[B:§10.2]`: do thông tin bất đối xứng giữa người
vay (biết rõ dự án) và người cho vay, **đầu tư phụ thuộc không chỉ lãi suất mà cả giá trị
ròng (net worth) của người vay**. Khi giá tài sản (BĐS) giảm → tài sản thế chấp mất giá →
net worth giảm → chi phí đại diện (agency cost) tăng → ngân hàng siết cho vay → đầu tư giảm
thêm → giá tài sản giảm tiếp. Vòng xoáy này **khuếch đại cú sốc** — lý do downturn BĐS + ngân
hàng thường tự gia cố. Nêu cơ chế này khi tin nói về siết tín dụng BĐS / nợ xấu tăng.

---

## 2. Lệch tiền tệ FX — vì sao tỷ giá USD/VND là rủi ro hệ thống

Chuỗi "lãi suất Fed/ECB → tỷ giá USD/VND → áp lực điều hành NHNN" trong prompt có nền lý
thuyết vững `[A:Ch16.3]`:

- Fed tăng lãi → chênh lệch lãi suất nghiêng về USD → vốn rút khỏi thị trường mới nổi → áp
  lực mất giá VND → NHNN buộc phải cân nhắc tăng lãi/bán dự trữ ngoại hối để giữ tỷ giá, **dù
  trong nước có thể cần nới lỏng** — đây là tam giác bất khả thi của một nền kinh tế mở.
- **Khủng hoảng do lệch tiền tệ** `[A:Ch16.3]`: ngân hàng vay USD, cho vay nội tệ. Khi nội tệ
  mất giá mạnh, khoản nợ USD phình ra trong khi tài sản tính bằng nội tệ → ngân hàng vỡ nợ
  hàng loạt (Đông Á 1997–98, Argentina 2002). → Theo dõi tỷ giá + mức độ vay ngoại tệ của hệ
  thống là chỉ báo rủi ro hệ thống, không chỉ là biến số lãi suất.

> **Hệ quả viết báo cáo:** Một tin Fed hawkish không chỉ là chuyện lãi suất Mỹ — với mảng VN
> nó là áp lực tỷ giá → áp lực lãi suất trong nước → áp lực lên BĐS. Mạch này phải xuyên suốt.

---

## 3. Ổn định ngân hàng: bank run, bảo hiểm tiền gửi, người cho vay cuối cùng

- **Bank run** `[A:Ch15.2]`: ngân hàng cho vay phần lớn tiền gửi, giữ dự trữ ít → chỉ cần *tin
  đồn* mất khả năng thanh toán cũng đủ kích hoạt rút tiền hàng loạt; **ngân hàng lành mạnh vẫn
  có thể sụp** và lan sang ngân hàng khác (chain reaction).
- **Mô hình Diamond–Dybvig** `[B:§10.6]`: ngân hàng làm **chuyển hóa kỳ hạn** (maturity
  transformation) — nhận tiền gửi ngắn hạn (rút bất kỳ lúc nào), cho vay dài hạn (kém thanh
  khoản). Tồn tại **hai cân bằng**: (a) bình thường, mọi người tin tưởng; (b) **bank run tự
  hiện thực hóa** (self-fulfilling) — nếu ai cũng tin người khác sẽ rút thì rút sớm là tối ưu,
  thành cân bằng Nash. Điểm mấu chốt: khủng hoảng có thể xảy ra **không cần** nền tảng xấu, chỉ
  cần niềm tin sụp đổ.
- **Phòng vệ**: bảo hiểm tiền gửi + NHTW làm **lender of last resort** `[A:Ch15.2]` cắt cân
  bằng (b). → Khi đọc tin về thanh khoản ngân hàng VN, phân biệt vấn đề **mất khả năng thanh
  toán (insolvency, net worth âm — phải xử lý)** với **thiếu thanh khoản tạm thời (illiquidity —
  cần bơm thanh khoản)**: hai cái đòi hỏi phản ứng chính sách khác nhau.

---

## 4. Lây lan (contagion) — vì sao khó khăn một nơi thành khủng hoảng hệ thống

Bốn kênh lây lan `[B:§10.7]`, hữu ích khi đánh giá một sự kiện ngân hàng đơn lẻ có nguy cơ
hệ thống không:

1. **Counterparty contagion** (trực tiếp nhất): các định chế nắm quyền đòi nợ lẫn nhau; một
   bên gặp run → giá trị quyền đòi của bên khác giảm → đẩy họ vào nghi ngờ khả năng thanh
   toán → run lan ra.
2. Bán tháo tài sản hạ giá (fire sales) làm giảm giá trị tài sản của định chế khác.
3. Mất niềm tin lan theo thông tin (nghi ngờ một ngân hàng → nghi ngờ ngân hàng "giống" nó).
4. Rút thanh khoản đồng loạt.

> Lưu ý phương pháp `[B:§10.7]`: ở cấp vi mô, khó khăn một định chế thường **tự ổn định** (vốn
> chảy sang nơi khác). Chỉ khi có **kênh lây lan** thì sự cố đơn lẻ mới thành khủng hoảng hệ
> thống. → Đừng thổi phồng mọi tin xấu ngân hàng thành rủi ro hệ thống; hỏi: *có kênh lây lan
> cụ thể nào không?*

---

## 5. Bối cảnh nền dài hạn (World Bank) — dùng đúng vai trò

Agent fetch `FR.INR.LEND` (lãi suất cho vay) và `FS.AST.PRVT.GD.ZS` (tín dụng tư nhân %GDP)
từ World Bank. Đây là **dữ liệu năm, trễ ~1 năm** → chỉ làm *nền cấu trúc*, KHÔNG dùng phân
tích diễn biến trong ngày (bài học đã ghi: tránh viện dẫn số WB cũ cho tin trong ngày). Tín
dụng tư nhân %GDP cao = đòn bẩy hệ thống cao = nhạy hơn với cú sốc lãi suất (liên hệ financial
accelerator §1). Lãi suất cho vay là mức nền để so sánh xu hướng tin tức ngắn hạn.

---

## Tóm tắt chuỗi nhân quả mảng VN

```
Fed/ECB (doc 02) ──► chênh lệch lãi suất ──► tỷ giá USD/VND ──► áp lực điều hành NHNN
                                                                      │
NHNN (lãi suất, room tín dụng) ──► FR.INR.LEND, tín dụng ──► cầu & nguồn vốn BĐS phía Nam
                                                                      │
   giá BĐS ⇄ net worth người vay (financial accelerator §10.2) ──► chu kỳ tín dụng
                                                                      │
   thanh khoản NH: phân biệt insolvency vs illiquidity; hỏi kênh lây lan trước khi báo động hệ thống
```
</content>
