# 01 — Khung vĩ mô của giá hàng hóa

Vì sao agent theo dõi đúng các chỉ báo trong `FRED_MACRO_SERIES` + `DXY` + 3 tỷ lệ liên
thị trường, và mỗi cái phản ánh cơ chế kinh tế nào.

---

## 1. Đồng đô la Mỹ (DXY) — kênh định giá

Gần như mọi hàng hóa toàn cầu (dầu, vàng, đồng, ngũ cốc) **niêm yết bằng USD**. Khi USD
mạnh lên, cùng một thùng dầu quy ra các đồng tiền khác trở nên đắt hơn → cầu ngoài Mỹ
giảm → giá USD của hàng hóa có xu hướng giảm. Đây là **quan hệ nghịch DXY ↔ hàng hóa**,
nền tảng cho mục `[VĨ MÔ]` của báo cáo (`commodity_agent.py` dùng `DXY = DX-Y.NYB`).

Hai cơ chế lý thuyết đứng sau biến động DXY `[A:Ch16.2]`:

- **Chênh lệch lãi suất.** Lãi suất Mỹ tăng tương đối so với nước khác → tài sản USD hấp dẫn
  hơn → cầu USD dịch phải, cung dịch trái → USD lên giá `[A:Ch16, Fig 16.7]`. Vì NHTW điều
  khiển lãi suất qua CSTT, **CSTT Mỹ là động lực gốc của DXY** → xem [doc 02](02-chinh-sach-tien-te.md).
- **Lạm phát tương đối & PPP.** Nước lạm phát cao hơn → sức mua đồng tiền bào mòn → đồng tiền
  mất giá `[A:Ch16, Fig 16.8]`. Dài hạn tỷ giá hướng về **purchasing power parity**; ngắn–trung
  hạn lệch khỏi PPP theo lãi suất, kỳ vọng `[A:Ch16.2]`.

> **Hệ quả cho prompt:** Khi DXY và giá hàng hóa cùng chiều (cùng tăng/giảm) trong ngày,
> đó là tín hiệu rằng động lực hôm đó **không phải** kênh USD (mà là cung-cầu riêng, risk
> sentiment, hay dòng NHTW) — đáng nêu rõ thay vì áp máy móc quan hệ nghịch.

---

## 2. Vàng ↔ lãi suất thực (DFII10) — vì sao đây là "biến số quan trọng nhất với vàng"

Code chú thích `DFII10` là *"lợi suất thực — biến số quan trọng nhất với vàng"* và prompt
ghi *"real yield giảm = hỗ trợ vàng"*. Cơ sở lý thuyết:

**Phương trình Fisher** `[B:§12.1, eq 12.3]`:
```
i  ≡  r + πᵉ        (lãi suất danh nghĩa = lãi suất thực + kỳ vọng lạm phát)
```
Vàng **không trả lãi**. Chi phí cơ hội của việc nắm vàng thay vì trái phiếu chính là **lãi
suất thực** `r` (phần lợi tức thực bạn từ bỏ). Khi `r` (DFII10) giảm, chi phí cơ hội nắm
vàng giảm → cầu vàng tăng → giá vàng lên. Đây không phải tương quan ngẫu nhiên mà là quan
hệ chi-phí-cơ-hội trực tiếp.

Bộ ba FRED của agent chính là phân rã Fisher, đo được trên thị trường:

| Series | Vai trò Fisher | Ý nghĩa |
|--------|----------------|---------|
| `DGS10` | `i` | Lãi suất danh nghĩa 10Y |
| `DFII10` | `r` | Lãi suất thực (TIPS 10Y) — chi phí cơ hội nắm vàng |
| `T5YIE` | `πᵉ` | Breakeven = kỳ vọng lạm phát thị trường |

Quan hệ kiểm tra chéo: `DGS10 ≈ DFII10 + (breakeven 10Y)`. `T5YIE` là kỳ hạn 5Y nên không
khớp tuyệt đối, nhưng **xu hướng** phải nhất quán; lệch lớn = một series có dữ liệu lỗi/cũ
→ cờ kiểm tra fetch.

> **Hai kịch bản cho vàng cần phân biệt trong báo cáo:**
> - **Real yield giảm vì kỳ vọng lạm phát tăng** (`T5YIE↑`, `DGS10` đứng yên): vàng tăng như
>   hàng rào lạm phát — *bullish lành mạnh*.
> - **Real yield giảm vì lãi suất danh nghĩa giảm** (Fed dovish, `DGS10↓`): vàng tăng do
>   nới lỏng tiền tệ — gắn với USD yếu, risk-on.
> Cùng "real yield giảm" nhưng hàm ý khác nhau → đọc kèm `T5YIE` và `DGS10` để biết kênh nào.

**Hiệu ứng Fisher** `[B:§12.1]`: dài hạn, thay đổi lạm phát truyền **một-đối-một** vào lãi
suất danh nghĩa. **Hiệu ứng thanh khoản (liquidity effect)** `[B:§12.1]`: *ngắn hạn*, nới
lỏng tiền tệ lại **hạ** lãi suất danh nghĩa (kênh real-rate lấn át kênh kỳ vọng lạm phát) —
lý do một tin "Fed bơm tiền" có thể khiến `DGS10` giảm trước rồi mới tăng sau khi lạm phát
hiện ra. Đừng kết luận vội chiều của lãi suất chỉ từ một tin nới lỏng.

---

## 3. VIX & tỷ lệ Đồng/Vàng — chu kỳ risk-on/risk-off

Code: `VIXCLS` chú thích *"risk-on/off, đối chiếu tỷ lệ Đồng/Vàng"*; `build_intermarket_block`
tính **Đồng/Vàng** và **Vàng/Bạc**.

- **Đồng/Vàng**: đồng (`Copper`) là kim loại công nghiệp → cầu gắn tăng trưởng/sản xuất toàn
  cầu; vàng là tài sản trú ẩn. Tỷ lệ Đồng/Vàng tăng = thị trường đặt cược tăng trưởng
  (risk-on); giảm = phòng thủ (risk-off). Đối chiếu với `VIX` cao (sợ hãi) phải nhất quán:
  VIX↑ thường đi cùng Đồng/Vàng↓.
- **Vàng/Bạc** (gold-silver ratio): bạc vừa là kim loại quý vừa công nghiệp → tỷ lệ cao =
  phòng thủ/suy thoái, thấp = chu kỳ công nghiệp mạnh.

Nền vĩ mô: đây là biểu hiện thị trường của **chu kỳ kinh tế (AD/AS)** `[A:Ch11]` — cầu công
nghiệp dịch theo tổng cầu, còn vàng phản ứng ngược với chu kỳ và với lãi suất thực.

---

## 4. Cung–cầu hàng hóa & nguyên tắc tồn kho

Giá ngắn hạn của từng mặt hàng do **cung và cầu của chính nó** quyết định `[A:Ch3]`; vĩ mô
ở trên là *nền dịch chuyển đường cầu*, không thay thế phân tích cung-cầu mặt hàng.

**Nguyên tắc tồn kho** (đã ghi trong CLAUDE.md): tồn kho lệch khỏi trung bình 5 năm
> 2 độ lệch chuẩn = tín hiệu lớn. Cơ sở: hàng hóa có **cầu kém co giãn theo giá ngắn hạn**
`[A:Ch5]` — một thay đổi nhỏ về lượng (tồn kho) gây thay đổi lớn về giá. Vì vậy độ lệch
tồn kho khuếch đại thành biến động giá. Nguồn thẩm quyền: EIA (dầu khí), USDA WASDE (nông
sản), ICSG/INSG (kim loại CN) — xem bảng "Nguồn dữ liệu thẩm quyền" trong CLAUDE.md.

---

## 5. Bản đồ chuỗi nhân quả (tóm tắt để nhúng vào phân tích)

```
CSTT Fed (doc 02) ──► fed funds ──► phổ lãi suất (term structure) ──► DGS10
        │                                              │
        ▼                                              ▼
   chênh lệch lãi suất ──► DXY ──(nghịch)──► giá hàng hóa USD
                                              ▲
   DFII10 (real yield) ──(chi phí cơ hội)──► VÀNG
        │
   T5YIE (kỳ vọng lạm phát) ──► vàng như hàng rào lạm phát
        │
   VIX / Đồng-Vàng ──► risk-on/off ──► kim loại CN vs trú ẩn
        │
   Cung-cầu mặt hàng + tồn kho (>2σ) ──► biến động giá riêng từng nhóm
```

Mỗi mũi tên là một quan hệ trung bình; báo cáo nên nêu **khi nào dữ liệu lệch khỏi mũi tên**
vì đó mới là thông tin có giá trị.
</content>
