# 02 — Chính sách tiền tệ & truyền dẫn

Nền lý thuyết cho các RSS feed chính sách NHTW (`Fed Monetary`, `ECB Press`, `Google News CB`)
và cho cách đọc tin "đã quyết định vs kỳ vọng". Đây là động lực gốc của DXY và lãi suất ở
[doc 01](01-vi-mo-gia-hang-hoa.md).

---

## 1. NHTW thực thi CSTT thế nào

Ba công cụ truyền thống `[A:Ch15.3]`:

1. **Nghiệp vụ thị trường mở (OMO)** — mua/bán trái phiếu chính phủ để điều chỉnh dự trữ
   ngân hàng, nhắm vào **fed funds rate** (lãi vay qua đêm liên ngân hàng). Đây là công cụ
   chính, chính xác nhất. NHTW mua trái phiếu → bơm tiền → lãi suất giảm; bán → hút tiền → lãi tăng.
2. **Tỷ lệ dự trữ bắt buộc** — ít dùng vì gây xáo trộn (VN: NHNN dùng công cụ này nhiều hơn Fed).
3. **Lãi suất chiết khấu** — cửa sổ cho vay cứu thanh khoản; vai trò "lender of last resort".

**Chuỗi truyền dẫn** `[A:Ch15.4]`:
```
OMO ──► dự trữ NH ──► fed funds ──► phổ lãi suất thị trường ──► đầu tư DN + vay tiêu dùng
                                                                 (nhà, xe, big-ticket)
                                                                        ──► AD ──► sản lượng & giá
```
- **Nới lỏng (expansionary)**: hạ lãi suất → AD dịch phải → chống suy thoái, nhưng quá đà → lạm phát.
- **Thắt chặt (contractionary)**: tăng lãi suất → AD dịch trái → hạ lạm phát, nhưng quá đà → suy thoái.
- CSTT nên **nghịch chu kỳ (countercyclical)** `[A:Ch15.4]`.

---

## 2. Từ lãi suất ngắn hạn đến lãi suất dài hạn (term structure)

NHTW chỉ trực tiếp điều khiển lãi suất *ngắn hạn*. Lãi suất dài hạn (DGS10 mà agent theo
dõi) được xác định bởi **expectations theory of the term structure** `[B:§12.2]`:

```
lãi suất dài hạn n kỳ  =  trung bình các lãi suất ngắn hạn kỳ vọng trong n kỳ  +  term premium
   iⁿₜ = (i¹ₜ + Eₜi¹ₜ₊₁ + … + Eₜi¹ₜ₊ₙ₋₁)/n + θₙₜ
```

Hệ quả thực dụng:
- DGS10 phản ánh **kỳ vọng về cả lộ trình lãi suất tương lai**, không chỉ mức hiện tại. Một
  tin Fed "giữ nguyên nhưng phát tín hiệu sẽ tăng" có thể đẩy DGS10 lên dù fed funds chưa đổi.
- **Đường cong lợi suất đảo ngược** (lãi ngắn > lãi dài) = thị trường kỳ vọng lãi suất tương
  lai giảm = kỳ vọng nới lỏng/suy thoái — đáng nêu trong mục VĨ MÔ khi xuất hiện.

---

## 3. Quy tắc Taylor — dự đoán hành động NHTW

Thay vì coi NHTW hành động tùy hứng, mô hình hóa bằng **Taylor rule** `[B:§12.6]`:
```
iₜ = rⁿ + φπ(πₜ − π*) + φy·(lnYₜ − lnYⁿₜ)     với Taylor đề xuất φπ=1.5, φy=0.5, r*=π*=2%
```
Hai nguyên tắc cốt lõi:
- **Nguyên tắc Taylor**: lãi suất danh nghĩa phải tăng **hơn một-đối-một** với lạm phát (φπ>1)
  để *lãi suất thực* tăng khi lạm phát vượt mục tiêu — nếu không, lạm phát tự khuếch đại `[B:§12.6]`.
- Tăng lãi khi sản lượng trên mức tự nhiên, giảm khi dưới.

> **Dùng để đọc tin:** Khi lạm phát Mỹ (CPIAUCSL) vượt mục tiêu 2% mà Fed chưa siết tương ứng,
> Taylor rule gợi ý áp lực tăng lãi → kỳ vọng USD mạnh, vàng chịu áp lực. Đây là khung *kỳ vọng*,
> dùng để phân biệt "Fed đang trước hay sau đường cong (behind the curve)".

---

## 4. Giới hạn dưới bằng 0 (ZLB) & nới lỏng định lượng (QE)

- **ZLB** `[B:§12.7]`: lãi suất danh nghĩa không xuống dưới ~0 (vì tiền mặt lợi tức 0). Khi
  chạm ZLB, công cụ lãi suất hết tác dụng → 2008–2015 Mỹ, Nhật từ cuối 1990s. Quy tắc Taylor
  từng đòi fed funds ≈ −4% năm 2009 nhưng không thực hiện được.
- **QE** `[A:Ch15.4]`: mua trái phiếu *dài hạn* + chứng khoán thế chấp (MBS) để hạ lãi suất
  dài hạn khi lãi ngắn đã chạm 0. Khác OMO truyền thống ở kỳ hạn và loại tài sản.

> Khi tin nhắc QE/QT (thắt chặt định lượng), tác động chính nằm ở **lãi suất dài hạn (DGS10)
> và thanh khoản**, không phải fed funds → ảnh hưởng trực tiếp DXY và vàng.

---

## 5. Hai cạm bẫy phải nhúng vào cách viết báo cáo

1. **Độ trễ dài và biến thiên** `[A:Ch15.5]`: CSTT tác động sản lượng/giá thực sau **1–3 năm**.
   → Tin chính sách tác động *kỳ vọng, tỷ giá, tài sản tài chính ngay hôm nay*; tác động cầu
   hàng hóa thực thì trễ. Báo cáo phải tách 2 tầng, không nói "Fed tăng lãi → cầu dầu giảm ngay".
2. **"Đẩy dây" (pushing on a string)** `[A:Ch15.5]`: thắt chặt luôn hiệu quả (kéo dây), nhưng
   nới lỏng có thể vô hiệu nếu ngân hàng giữ dự trữ dư thừa / DN-hộ ngại vay (Nhật 1990s–2000s).
   → Bất đối xứng: tin "Fed hạ lãi" không đảm bảo kích cầu, đặc biệt khi tâm lý xấu.

**Phương trình số lượng tiền** `[A:Ch15.5]`: `M·V = P·Y`. Đúng theo định nghĩa, nhưng `V`
(vòng quay tiền) biến động khó lường từ thập niên 1980 → quan hệ "in tiền → lạm phát" chỉ
chắc chắn *dài hạn / khi lạm phát cao* `[B:§12.1]`, không dùng dự báo ngắn hạn.

---

## 6. Đối với báo cáo: phân biệt "đã quyết định" vs "kỳ vọng"

Prompt banking đã yêu cầu điều này; lý do lý thuyết: thị trường tài chính **forward-looking**,
giá đã phản ánh kỳ vọng. Một quyết định *đúng như kỳ vọng* thường ít làm giá biến động; chỉ
**bất ngờ so với kỳ vọng** mới gây cú sốc. Vì vậy khi đọc tin NHTW, phải nêu rõ:
- Đây là **quyết định đã ra** hay **đồn đoán/định hướng**?
- Nếu đã ra: **khớp hay lệch kỳ vọng thị trường**? (lệch mới là tin gây biến động)
</content>
