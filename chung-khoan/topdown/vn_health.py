# -*- coding: utf-8 -*-
"""
Lớp SỨC KHỎE TÀI CHÍNH / DÒNG TIỀN — bắt suy yếu NỘI TẠI (khác tầng "phốt" bên ngoài).

Đọc báo cáo tài chính nhiều năm (VCI) → phát cờ ĐỎ NẶNG kèm BẰNG CHỨNG SỐ. Triết lý
(khớp memory): mỗi cờ có số + ngưỡng ghi rõ (chỉnh được); CROSS-CHECK nhiều tầng, không
kết luận từ 1 chỉ số lẻ; thiếu dữ liệu → bỏ qua, không bịa.

CHẶT (chỉ cờ nguy hiểm rõ) để công ty khỏe ra 0 cờ:
  1. CFO âm — nhất là khi VẪN CÓ LÃI (lợi nhuận không ra tiền → chất lượng LN kém, kinh điển).
  2. Chất lượng LN: CFO 3 năm ≪ lãi ròng 3 năm (tiền thực thu ít hơn lãi ghi sổ).
  3. Trả nợ mỏng: EBIT / |lãi vay| < 2 (khó gánh lãi).
  4. Thanh khoản yếu + đòn bẩy cao: current ratio < 1 VÀ D/E > 2 (đồng thời).
  5. Kinh doanh đi lùi: doanh thu giảm mạnh / lãi chuyển lỗ / lãi giảm sâu so năm trước.

QUAN TRỌNG — KHÔNG dùng "FCF âm" đơn lẻ làm cờ: công ty tăng trưởng (vd HPG xây nhà máy)
có capex lớn → FCF âm nhưng CFO mạnh, KHÔNG phải distress. Chỉ CFO/coverage/suy giảm mới đáng.

Ngân hàng: BỎ QUA (CFO/current ratio không có nghĩa như DN thường) — đã soi bằng CAMELS ở
vn_valuation. Đơn vị số tiền = ĐỒNG.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from vn_fundamentals import VCIFundamentals

logger = logging.getLogger(__name__)

# --- Tên cột (đã Việt hóa qua /metrics) — đã verify trên data thật ---
C_CFO = "Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh"
C_REV = "Doanh thu thuần"
C_PRETAX = "Lãi/(lỗ) trước thuế"
C_INT = "Chi phí lãi vay"          # lưu ÂM (chi phí) → dùng trị tuyệt đối
C_NI = "Lãi/(lỗ) thuần sau thuế"

# --- Ngưỡng (giả định, chỉnh được) ---
MIN_COVERAGE = 2.0        # EBIT/|lãi vay| tối thiểu coi là an toàn
MIN_CURRENT = 1.0         # current ratio
MAX_DE = 2.0              # D/E
REV_DROP = 0.15           # doanh thu giảm > 15% YoY
PROFIT_DROP = 0.40        # lãi ròng giảm > 40% YoY
CFO_NI_MIN = 0.4          # CFO 3 năm / lãi ròng 3 năm tối thiểu
_INT_FLOOR = 1e9          # |lãi vay| < 1 tỷ thì bỏ qua coverage (tránh chia số nhỏ)


def _t(x: float) -> str:
    """Format tỷ đồng."""
    return f"{x/1e9:,.0f} tỷ"


class VNHealth:
    def __init__(self, fx: Optional[VCIFundamentals] = None):
        self.fx = fx or VCIFundamentals()

    @staticmethod
    def _series(df: pd.DataFrame, col: str) -> List[Tuple[int, float]]:
        """[(năm, giá trị)] sắp theo năm tăng dần; bỏ NaN. Rỗng nếu thiếu cột."""
        if df is None or df.empty or col not in df.columns or "yearReport" not in df.columns:
            return []
        out = []
        for y, v in zip(df["yearReport"], df[col]):
            try:
                fv = float(v)
                yi = int(y)
            except (TypeError, ValueError):
                continue
            if not np.isnan(fv):
                out.append((yi, fv))
        out.sort(key=lambda t: t[0])
        return out

    def scan(self, symbol: str, is_bank: bool = False,
             ratios: Optional[pd.DataFrame] = None) -> List[str]:
        """Trả danh sách cờ đỏ (chuỗi có bằng chứng số). Rỗng nếu khỏe / thiếu dữ liệu.

        `ratios`: DataFrame get_ratios (nếu truyền vào thì đỡ gọi lại API).
        """
        symbol = symbol.upper().strip()
        if is_bank:
            return []  # bank: dùng CAMELS, không áp CFO/current ratio
        flags: List[str] = []
        try:
            inc = self.fx.get_statement(symbol, "INCOME_STATEMENT", "year")
            cf = self.fx.get_statement(symbol, "CASH_FLOW", "year")
        except Exception as e:  # noqa: BLE001
            logger.warning("get_statement %s lỗi: %s", symbol, e)
            return flags

        cfo = self._series(cf, C_CFO)
        rev = self._series(inc, C_REV)
        ni = self._series(inc, C_NI)
        pretax = self._series(inc, C_PRETAX)
        interest = self._series(inc, C_INT)

        # map năm → giá trị để căn theo cùng kỳ
        ni_map = dict(ni)
        cfo_map = dict(cfo)

        # ---- 1. CFO âm (kỳ gần nhất) ----
        if cfo:
            yr, cfo_last = cfo[-1]
            ni_last = ni_map.get(yr)
            if cfo_last < 0:
                if ni_last is not None and ni_last > 0:
                    flags.append(f"🔻 Dòng tiền {yr}: CFO ÂM ({_t(cfo_last)}) dù lãi ròng dương "
                                 f"({_t(ni_last)}) — lợi nhuận không ra tiền (chất lượng LN kém)")
                else:
                    flags.append(f"🔻 Dòng tiền {yr}: CFO ÂM ({_t(cfo_last)}) — hoạt động không tạo tiền")

        # ---- 2. Chất lượng LN: CFO 3 năm ≪ lãi ròng 3 năm ----
        yrs_common = [y for y in ni_map if y in cfo_map]
        yrs_common.sort()
        last3 = yrs_common[-3:]
        if len(last3) >= 3:
            sni = sum(ni_map[y] for y in last3)
            scfo = sum(cfo_map[y] for y in last3)
            if sni > 0 and scfo / sni < CFO_NI_MIN:
                flags.append(f"🔻 Chất lượng LN: CFO 3 năm chỉ bằng {scfo/sni:.0%} lãi ròng "
                             f"(<{CFO_NI_MIN:.0%}) — lợi nhuận ít chuyển thành tiền")

        # ---- 3. Trả nợ mỏng: EBIT/|lãi vay| < 2 ----
        if pretax and interest:
            yr, pt = pretax[-1]
            int_map = dict(interest)
            iv = abs(int_map.get(yr, 0.0))
            if iv > _INT_FLOOR:
                ebit = pt + iv               # cộng lại lãi vay (pretax đã trừ lãi)
                cov = ebit / iv
                if cov < MIN_COVERAGE:
                    flags.append(f"🔻 Trả nợ {yr}: EBIT/lãi vay = {cov:.1f}x (<{MIN_COVERAGE:.0f}) "
                                 f"— khả năng trả lãi mỏng")

        # ---- 4. Thanh khoản yếu + đòn bẩy cao (đồng thời) ----
        if ratios is None:
            try:
                ratios = self.fx.get_ratios(symbol)
            except Exception:  # noqa: BLE001
                ratios = None
        if ratios is not None and not ratios.empty:
            annual = ratios[ratios.get("quarter").fillna(0) == 0] if "quarter" in ratios else ratios
            if not annual.empty:
                row = annual.iloc[-1]
                cr = row.get("currentRatio")
                de = row.get("debtToEquity")
                try:
                    cr = float(cr); de = float(de)
                    if cr < MIN_CURRENT and de > MAX_DE:
                        flags.append(f"🔻 Thanh khoản: current ratio {cr:.2f} (<1) kèm đòn bẩy "
                                     f"D/E {de:.1f} (>{MAX_DE:.0f}) — áp lực ngắn hạn")
                except (TypeError, ValueError):
                    pass

        # ---- 5. Kinh doanh đi lùi (doanh thu/lãi so năm trước) ----
        if len(rev) >= 2:
            (_, r_prev), (yr, r_last) = rev[-2], rev[-1]
            if r_prev > 0 and (r_last - r_prev) / r_prev < -REV_DROP:
                flags.append(f"🔻 Kinh doanh {yr}: doanh thu giảm {(r_last/r_prev-1):.0%} "
                             f"so năm trước ({_t(r_prev)}→{_t(r_last)})")
        if len(ni) >= 2:
            (_, n_prev), (yr, n_last) = ni[-2], ni[-1]
            if n_last < 0 and n_prev > 0:
                flags.append(f"🔻 Kinh doanh {yr}: CHUYỂN LỖ ({_t(n_last)}) từ lãi ({_t(n_prev)})")
            elif n_prev > 0 and (n_last - n_prev) / n_prev < -PROFIT_DROP and n_last > 0:
                flags.append(f"🔻 Kinh doanh {yr}: lãi ròng giảm {(n_last/n_prev-1):.0%} "
                             f"so năm trước")

        return flags


if __name__ == "__main__":
    from vn_fundamentals import ensure_utf8_stdout
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    h = VNHealth()
    for sym in ("HPG", "FPT", "VCB"):
        fl = h.scan(sym, is_bank=(sym == "VCB"))
        print(f"\n=== {sym} — {len(fl)} cờ sức khỏe ===")
        for f in fl:
            print("  ", f)
        if not fl:
            print("   (không cờ — khỏe / hoặc bank dùng CAMELS)")
