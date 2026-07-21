# -*- coding: utf-8 -*-
"""
BÁO CÁO FORENSIC CHUYÊN SÂU MỘT MÃ — "đọc báo cáo tài chính như giới phân tích".

Mục tiêu: từ 3 báo cáo (kết quả kinh doanh / cân đối kế toán / lưu chuyển tiền tệ) nhiều
năm của VCI, dựng BỨC TRANH THỰC về kinh doanh, dòng tiền và cân đối kế toán — và soi các
THỦ THUẬT LÀM ĐẸP SỔ. Nền lý luận: CFA L1 R25 + L2 m14 (Financial Reporting Quality):
  - Reporting quality ≠ earnings quality (báo cáo trung thực vs kết quả bền vững).
  - Cờ đỏ hàng đầu: lãi ròng > CFO kéo dài (accruals cao → lợi nhuận không ra tiền).
  - Phải thu / tồn kho phình nhanh hơn doanh thu → nghi ghi nhận sớm / nhồi kênh.
  - Vốn hóa chi phí, đổi ước tính khấu hao/dự phòng, "cookie jar", thu nhập một lần lặp lại.
  - Mô hình cảnh báo định lượng: Beneish M-score (bóp lợi nhuận), Altman Z (kiệt quệ),
    thêm Piotroski F-score (sức khỏe cơ bản).

TRIẾT LÝ (khớp memory): mỗi nhận định KÈM SỐ + ngưỡng ghi rõ; CROSS-CHECK nhiều tầng, không
kết luận từ 1 chỉ số lẻ; dữ liệu thiếu → BỎ QUA, không bịa. Các điểm số (Beneish/Altman)
hiệu chỉnh cho thị trường Mỹ → chỉ dùng làm CỜ TƯƠNG ĐỐI, có cảnh báo, KHÔNG phải phán quyết.

Ngân hàng / chứng khoán / bảo hiểm: cấu trúc BCTC khác hẳn → phần lớn chỉ số dưới đây KHÔNG
áp dụng. Với bank, module trả nhánh riêng (dùng CAMELS ở vn_valuation) và ghi rõ "không áp".

Đơn vị số tiền = ĐỒNG (VND).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout

logger = logging.getLogger(__name__)

# ============================================================================
# Tên dòng BCTC (đã Việt hóa qua /metrics của VCI) — VERIFY trên data thật 21/07.
# ============================================================================
# --- Kết quả kinh doanh ---
I_REV_GROSS = "Doanh thu bán hàng và cung cấp dịch vụ"
I_REV = "Doanh thu thuần"
I_COGS = "Giá vốn hàng bán"
I_GROSS = "Lợi nhuận gộp"
I_FIN_INC = "Doanh thu hoạt động tài chính"       # lãi tiền gửi, cổ tức, chênh lệch tỷ giá...
I_FIN_EXP = "Chi phí tài chính"
I_INT = "Chi phí lãi vay"                          # (thường lưu dương trong KQKD của VCI)
I_SELL = "Chi phí bán hàng"
I_ADMIN = "Chi phí quản lý doanh nghiệp"
I_OP = "Lãi/(lỗ) từ hoạt động kinh doanh"
I_OTHER_NET = "Thu nhập khác, ròng"
I_JV = "Lãi/(lỗ) từ công ty liên doanh"
I_PRETAX = "Lãi/(lỗ) trước thuế"
I_NI = "Lãi/(lỗ) thuần sau thuế"
I_NI_PARENT = "Lợi nhuận của Cổ đông của Công ty mẹ"
I_EPS = "Lãi cơ bản trên cổ phiếu (VND)"

# --- Cân đối kế toán ---
B_CA = "TÀI SẢN NGẮN HẠN"
B_CASH = "Tiền và tương đương tiền"
B_ST_INVEST = "Đầu tư ngắn hạn"
B_RECV = "Các khoản phải thu"                      # phải thu ngắn hạn (tổng)
B_RECV_TRADE = "Phải thu khách hàng"              # phải thu thương mại
B_INV = "Hàng tồn kho, ròng"
B_PPE_NET = "GTCL TSCĐ hữu hình"                   # giá trị còn lại TSCĐ hữu hình
B_TA = "TỔNG CỘNG TÀI SẢN"
B_LIAB = "NỢ PHẢI TRẢ"
B_CL = "Nợ ngắn hạn"
B_ST_DEBT = "Vay ngắn hạn"
B_PAYABLE = "Phải trả người bán"
B_LT_DEBT = "Vay dài hạn"
B_EQUITY = "Vốn chủ sở hữu"
B_RE = "Lãi chưa phân phối"                        # lợi nhuận giữ lại
B_SHARE_CAP = "Vốn góp"

# --- Lưu chuyển tiền tệ ---
CF_DEP = "Khấu hao TSCĐ và BĐSĐT"
CF_CFO = "Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh"
CF_CAPEX = "Tiền chi để mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác"  # lưu ÂM
CF_CFI = "Lưu chuyển tiền thuần từ hoạt động đầu tư"
CF_CFF = "Lưu chuyển tiền thuần từ hoạt động tài chính"
CF_DIV_PAID = "Cổ tức, lợi nhuận đã trả cho chủ sở hữu"                       # lưu ÂM
CF_DEBT_IN = "Tiền thu được các khoản đi vay"
CF_DEBT_OUT = "Tiền trả nợ gốc vay"                                          # lưu ÂM
CF_SHARE_ISSUE = "Tiền thu từ phát hành cổ phiếu, nhận vốn góp của chủ sở hữu"
CF_SHARE_BUY = "Tiền chi trả vốn góp cho các chủ sở hữu, mua lại cổ phiếu của doanh nghiệp đã phát hành"

DAYS = 365.0


def _t(x: Optional[float]) -> str:
    """Format tỷ đồng, an toàn với None/NaN."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x/1e9:,.0f} tỷ"


def _pct(x: Optional[float], digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x*100:+.{digits}f}%"


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        if b == 0 or np.isnan(a) or np.isnan(b):
            return None
        return a / b
    except (TypeError, ValueError):
        return None


# ============================================================================
# Cấu trúc kết quả
# ============================================================================
@dataclass
class Section:
    title: str
    lines: List[str] = field(default_factory=list)     # dòng diễn giải
    table: Optional[pd.DataFrame] = None                # bảng số (tùy chọn)
    flags: List[str] = field(default_factory=list)      # cờ đỏ của phần


@dataclass
class DeepDive:
    symbol: str
    name: str
    is_bank: bool
    sector: str
    years: List[int]
    sections: Dict[str, Section] = field(default_factory=dict)
    red_flags: List[str] = field(default_factory=list)
    positives: List[str] = field(default_factory=list)
    verdict: str = ""
    error: Optional[str] = None


class VNDeepDive:
    """Sinh báo cáo forensic một mã. Dùng lại VCIFundamentals (và tùy chọn sectors/valuation)."""

    def __init__(self, fx: Optional[VCIFundamentals] = None,
                 sectors=None, valuation=None):
        self.fx = fx or VCIFundamentals()
        self.sectors = sectors        # VCISectors (tùy chọn — để biết ngành + is_bank)
        self.valuation = valuation    # VNValuation (tùy chọn — nhận định đắt/rẻ)

    # ---- lấy chuỗi theo năm ----
    @staticmethod
    def _series(df: pd.DataFrame, col: str) -> Dict[int, float]:
        """{năm: giá trị} bỏ NaN. Rỗng nếu thiếu cột. Nếu tên cột trùng (VCI có), lấy cột đầu."""
        if df is None or df.empty or "yearReport" not in df.columns or col not in df.columns:
            return {}
        sub = df[col]
        if isinstance(sub, pd.DataFrame):    # tên cột trùng → lấy cột đầu
            sub = sub.iloc[:, 0]
        out: Dict[int, float] = {}
        for y, v in zip(df["yearReport"], sub):
            try:
                yi, fv = int(y), float(v)
            except (TypeError, ValueError):
                continue
            if not np.isnan(fv):
                out[yi] = fv
        return out

    def analyze(self, symbol: str, name: str = "", is_bank: Optional[bool] = None) -> DeepDive:
        symbol = symbol.upper().strip()
        # ngành + is_bank
        sector = ""
        if self.sectors is not None:
            try:
                info = self.sectors.sector_of(symbol) or {}
                sector = info.get("icb_l2") or info.get("icb_l1") or ""
                if not name:
                    name = info.get("name") or ""
                if is_bank is None:
                    is_bank = bool(info.get("is_bank"))
            except Exception:  # noqa: BLE001
                pass
        is_bank = bool(is_bank)

        try:
            inc = self.fx.get_statement(symbol, "INCOME_STATEMENT", "year")
            bal = self.fx.get_statement(symbol, "BALANCE_SHEET", "year")
            cf = self.fx.get_statement(symbol, "CASH_FLOW", "year")
            ratios = self.fx.get_ratios(symbol)
        except Exception as e:  # noqa: BLE001
            return DeepDive(symbol, name or symbol, is_bank, sector, [], error=str(e))

        years = sorted(set(self._series(inc, I_REV)) |
                       set(self._series(bal, B_TA)) | set(self._series(cf, CF_CFO)))
        dd = DeepDive(symbol, name or symbol, is_bank, sector, years)

        if is_bank:
            dd.sections["bank"] = Section(
                "Lưu ý ngân hàng",
                ["Đây là tổ chức tín dụng — cấu trúc báo cáo tài chính khác hẳn doanh nghiệp "
                 "sản xuất/dịch vụ. Các chỉ số forensic dưới đây (accruals, chu kỳ vốn lưu động, "
                 "Altman Z, Beneish) KHÔNG áp dụng. Đánh giá sức khỏe ngân hàng dùng khung CAMELS "
                 "(NIM, NPL, CAR, CIR, LDR, CASA) — xem tầng định giá/CAMELS riêng."])
            dd.verdict = "Ngân hàng — dùng khung CAMELS, không áp forensic doanh nghiệp thường."
            return dd

        # gom các chuỗi hay dùng
        S = {
            "rev": self._series(inc, I_REV), "cogs": self._series(inc, I_COGS),
            "gross": self._series(inc, I_GROSS), "op": self._series(inc, I_OP),
            "fin_inc": self._series(inc, I_FIN_INC), "fin_exp": self._series(inc, I_FIN_EXP),
            "int": self._series(inc, I_INT), "sell": self._series(inc, I_SELL),
            "admin": self._series(inc, I_ADMIN), "other": self._series(inc, I_OTHER_NET),
            "jv": self._series(inc, I_JV), "pretax": self._series(inc, I_PRETAX),
            "ni": self._series(inc, I_NI), "ni_parent": self._series(inc, I_NI_PARENT),
            "ca": self._series(bal, B_CA), "cash": self._series(bal, B_CASH),
            "st_inv": self._series(bal, B_ST_INVEST), "recv": self._series(bal, B_RECV),
            "recv_trade": self._series(bal, B_RECV_TRADE), "inv": self._series(bal, B_INV),
            "ppe": self._series(bal, B_PPE_NET), "ta": self._series(bal, B_TA),
            "liab": self._series(bal, B_LIAB), "cl": self._series(bal, B_CL),
            "st_debt": self._series(bal, B_ST_DEBT), "payable": self._series(bal, B_PAYABLE),
            "lt_debt": self._series(bal, B_LT_DEBT), "equity": self._series(bal, B_EQUITY),
            "re": self._series(bal, B_RE),
            "dep": self._series(cf, CF_DEP), "cfo": self._series(cf, CF_CFO),
            "capex": self._series(cf, CF_CAPEX), "cfi": self._series(cf, CF_CFI),
            "cff": self._series(cf, CF_CFF), "div_paid": self._series(cf, CF_DIV_PAID),
            "debt_in": self._series(cf, CF_DEBT_IN), "debt_out": self._series(cf, CF_DEBT_OUT),
            "share_issue": self._series(cf, CF_SHARE_ISSUE), "share_buy": self._series(cf, CF_SHARE_BUY),
        }

        self._business_picture(dd, S)
        self._earnings_quality(dd, S)
        self._cashflow(dd, S)
        self._balance_sheet(dd, S)
        self._distress(dd, S, ratios)
        self._valuation(dd, symbol)

        self._make_verdict(dd)
        return dd

    # ------------------------------------------------------------------
    # 1. BỨC TRANH KINH DOANH — tách lợi nhuận CỐT LÕI khỏi khoản một lần
    # ------------------------------------------------------------------
    def _business_picture(self, dd: DeepDive, S: dict) -> None:
        sec = Section("1. Bức tranh kinh doanh thực")
        rev, gross, op = S["rev"], S["gross"], S["op"]
        yrs = sorted(rev)
        if len(yrs) < 2:
            sec.lines.append("Thiếu dữ liệu doanh thu nhiều năm.")
            dd.sections["business"] = sec
            return
        rows = []
        for y in yrs:
            r = rev.get(y); g = gross.get(y); o = op.get(y)
            gm = _safe_div(g, r); om = _safe_div(o, r)
            fin_inc = S["fin_inc"].get(y); other = S["other"].get(y); jv = S["jv"].get(y)
            pretax = S["pretax"].get(y); ni = S["ni"].get(y)
            # lợi nhuận CỐT LÕI ~ LN từ HĐKD trừ phần thu nhập tài chính (lãi gửi/tỷ giá) — xấp xỉ
            # phần "không cốt lõi" = thu nhập tài chính + thu nhập khác ròng + lãi liên doanh
            noncore = sum(v for v in (fin_inc, other, jv) if v is not None)
            rows.append({"Năm": y, "Doanh thu": r, "LN gộp": g, "Biên gộp": gm,
                         "LN thuần HĐKD": o, "Biên HĐKD": om,
                         "Thu nhập ngoài cốt lõi": noncore if (fin_inc or other or jv) else None,
                         "LN trước thuế": pretax, "LN sau thuế": ni})
        tbl = pd.DataFrame(rows)
        sec.table = tbl

        y0, y1 = yrs[-2], yrs[-1]
        rev_g = _safe_div(rev.get(y1), rev.get(y0))
        rev_g = (rev_g - 1) if rev_g else None
        gm0, gm1 = _safe_div(gross.get(y0), rev.get(y0)), _safe_div(gross.get(y1), rev.get(y1))
        sec.lines.append(
            f"Doanh thu {y1}: {_t(rev.get(y1))}, tăng trưởng {_pct(rev_g)} so {y0}. "
            f"Biên lợi nhuận gộp {gm1*100:.1f}% "
            f"(năm trước {gm0*100:.1f}%)." if (gm1 is not None and gm0 is not None) else
            f"Doanh thu {y1}: {_t(rev.get(y1))}, tăng trưởng {_pct(rev_g)} so {y0}.")
        # biên gộp nhảy bất thường (dấu hiệu ghi nhận/phân bổ giá vốn thất thường)
        if gm0 is not None and gm1 is not None and abs(gm1 - gm0) > 0.15:
            sec.flags.append(
                f"🔻 Biên lợi nhuận gộp nhảy bất thường {gm0*100:.1f}%→{gm1*100:.1f}% "
                f"({y0}→{y1}) — cần soi cách ghi nhận doanh thu/giá vốn (dự án, hoàn nhập).")

        # bóc tách chất lượng lợi nhuận: bao nhiêu % LN trước thuế đến từ ngoài cốt lõi?
        pretax1 = S["pretax"].get(y1)
        noncore1 = sum(v for v in (S["fin_inc"].get(y1), S["other"].get(y1), S["jv"].get(y1))
                       if v is not None)
        share = _safe_div(noncore1, pretax1)
        if share is not None and pretax1 and pretax1 > 0:
            sec.lines.append(
                f"Cơ cấu lợi nhuận {y1}: LN thuần từ hoạt động kinh doanh cốt lõi "
                f"{_t(op.get(y1))}; thu nhập ngoài cốt lõi (lãi tài chính + thu nhập khác + "
                f"liên doanh) {_t(noncore1)} ≈ {share*100:.0f}% lãi trước thuế.")
            if share > 0.40:
                sec.flags.append(
                    f"🔻 Chất lượng LN: {share*100:.0f}% lãi trước thuế {y1} đến từ NGOÀI hoạt "
                    f"động cốt lõi (thu tài chính/khác/liên doanh) — lợi nhuận kém bền vững, "
                    f"cần soi có phải khoản một lần.")
        dd.sections["business"] = sec

    # ------------------------------------------------------------------
    # 2. CHẤT LƯỢNG LỢI NHUẬN — accruals, NI vs CFO, phải thu/tồn kho, Beneish
    # ------------------------------------------------------------------
    def _earnings_quality(self, dd: DeepDive, S: dict) -> None:
        sec = Section("2. Chất lượng lợi nhuận & dấu hiệu làm đẹp")
        ni, cfo, ta = S["ni"], S["cfo"], S["ta"]
        yrs = sorted(set(ni) & set(cfo))

        # --- 2a. NI vs CFO nhiều năm (cờ đỏ số 1 theo CFA) ---
        rows = []
        neg_gap_years = 0
        for y in yrs:
            n, c = ni[y], cfo[y]
            ratio = _safe_div(c, n) if n and n > 0 else None
            rows.append({"Năm": y, "LN sau thuế": n, "CFO": c, "CFO/LN": ratio})
            if n and n > 0 and c < n:
                neg_gap_years += 1
        if rows:
            sec.table = pd.DataFrame(rows)
        if len(yrs) >= 3:
            last3 = yrs[-3:]
            sni = sum(ni[y] for y in last3); scfo = sum(cfo[y] for y in last3)
            if sni > 0:
                cover = scfo / sni
                sec.lines.append(
                    f"Dòng tiền so lợi nhuận (3 năm {last3[0]}–{last3[-1]}): CFO cộng dồn "
                    f"{_t(scfo)} = {cover*100:.0f}% lãi ròng cộng dồn {_t(sni)}.")
                if cover < 0.5:
                    sec.flags.append(
                        f"🔻 Lợi nhuận không ra tiền: CFO 3 năm chỉ bằng {cover*100:.0f}% lãi "
                        f"ròng (<50%) — accruals cao, chất lượng lợi nhuận thấp (cờ đỏ số 1 CFA).")
                elif cover >= 0.9:
                    dd.positives.append(
                        f"✅ Lợi nhuận có tiền thật: CFO 3 năm bằng {cover*100:.0f}% lãi ròng.")

        # --- 2b. Accruals ratio (bảng cân đối): (ΔNOA)/NOA_tb.  Xấp xỉ dùng (NI-CFO)/TA_tb ---
        if len(yrs) >= 2:
            y1 = yrs[-1]; y0 = yrs[-2]
            ta_avg = _safe_div((ta.get(y1, 0) + ta.get(y0, 0)), 2)
            accr = _safe_div((ni.get(y1, 0) - cfo.get(y1, 0)), ta_avg)
            if accr is not None:
                sec.lines.append(
                    f"Tỷ lệ accruals {y1} (dòng dồn tích = (LN − CFO)/tổng tài sản bình quân): "
                    f"{accr*100:+.1f}%. Càng cao & dương → lợi nhuận càng dựa vào bút toán, "
                    f"kém bền (CFA L2 m14).")
                if accr > 0.10:
                    sec.flags.append(
                        f"🔻 Accruals cao {accr*100:+.1f}% (>10%) {y1} — phần lớn lợi nhuận là "
                        f"dồn tích kế toán, không phải tiền; dễ đảo chiều.")

        # --- 2c. Phải thu / tồn kho phình nhanh hơn doanh thu ---
        rev = S["rev"]; recv = S["recv"]; inv = S["inv"]
        ys = sorted(set(rev) & set(recv))
        if len(ys) >= 2:
            y0, y1 = ys[-2], ys[-1]
            g_rev = _safe_div(rev[y1], rev[y0])
            g_recv = _safe_div(recv[y1], recv[y0])
            if g_rev and g_recv:
                g_rev -= 1; g_recv -= 1
                sec.lines.append(
                    f"Phải thu {y1} thay đổi {_pct(g_recv)} trong khi doanh thu thay đổi {_pct(g_rev)}.")
                if g_recv - g_rev > 0.20 and g_recv > 0.15:
                    sec.flags.append(
                        f"🔻 Phải thu phình nhanh hơn doanh thu ({_pct(g_recv)} vs {_pct(g_rev)}) "
                        f"{y1} — nghi ghi nhận doanh thu sớm / nới điều khoản bán chịu.")
        ys = sorted(set(rev) & set(inv))
        if len(ys) >= 2:
            y0, y1 = ys[-2], ys[-1]
            g_rev = _safe_div(rev[y1], rev[y0])
            g_inv = _safe_div(inv[y1], inv[y0])
            if g_rev and g_inv:
                g_rev -= 1; g_inv -= 1
                if g_inv - g_rev > 0.25 and g_inv > 0.20:
                    sec.flags.append(
                        f"🔻 Tồn kho phình nhanh hơn doanh thu ({_pct(g_inv)} vs {_pct(g_rev)}) "
                        f"{y1} — nghi hàng ế / nguy cơ trích lập giảm giá tồn kho.")

        # --- 2d. Beneish M-score (8 biến) — CẢNH BÁO hiệu chỉnh cho thị trường Mỹ ---
        m = self._beneish(S)
        if m is not None:
            mscore, comps = m
            sec.lines.append(
                f"Beneish M-score {mscore:+.2f} (ngưỡng −1.78; cao hơn → khả năng bóp lợi nhuận "
                f"cao). *Mô hình hiệu chỉnh cho thị trường Mỹ — chỉ dùng làm cờ tham khảo.*")
            if mscore > -1.78:
                sec.flags.append(
                    f"🔻 Beneish M-score {mscore:+.2f} > −1.78 — mô hình xếp vào nhóm CÓ khả năng "
                    f"thao túng lợi nhuận (tham khảo, cần kiểm chứng thuyết minh).")
            dd._beneish_comps = comps  # lưu để render bảng
        dd.sections["quality"] = sec

    def _beneish(self, S: dict) -> Optional[Tuple[float, Dict[str, float]]]:
        """Beneish M-score. Cần dữ liệu 2 năm liền kề. Trả (M, {8 biến}) hoặc None."""
        rev, gross, ta = S["rev"], S["gross"], S["ta"]
        recv, ca, ppe = S["recv"], S["ca"], S["ppe"]
        sga_sell, sga_adm = S["sell"], S["admin"]
        liab, cl, ltd = S["liab"], S["cl"], S["lt_debt"]
        dep, cfo, ni = S["dep"], S["cfo"], S["ni"]
        yrs = sorted(set(rev) & set(ta) & set(recv))
        if len(yrs) < 2:
            return None
        t, p = yrs[-1], yrs[-2]      # t = năm nay, p = năm trước

        def g(d, y):
            return d.get(y)

        try:
            # DSRI
            dsri = _safe_div(_safe_div(recv[t], rev[t]), _safe_div(recv[p], rev[p]))
            # GMI = GM_p / GM_t
            gm_t = _safe_div(gross.get(t), rev[t]); gm_p = _safe_div(gross.get(p), rev[p])
            gmi = _safe_div(gm_p, gm_t)
            # AQI = softassets_t / softassets_p ; soft = 1 - (CA+PPE)/TA
            def soft(y):
                num = (ca.get(y, 0) + ppe.get(y, 0))
                return 1 - _safe_div(num, ta.get(y)) if ta.get(y) else None
            aqi = _safe_div(soft(t), soft(p))
            # SGI
            sgi = _safe_div(rev[t], rev[p])
            # DEPI = deprate_p / deprate_t ; deprate = dep/(dep+PPE)
            def deprate(y):
                dv = dep.get(y); pv = ppe.get(y)
                if dv is None or pv is None:
                    return None
                return _safe_div(dv, dv + pv)
            depi = _safe_div(deprate(p), deprate(t))
            # SGAI = (SGA/Sales)_t / (SGA/Sales)_p
            def sga(y):
                s = 0.0; has = False
                for d in (sga_sell, sga_adm):
                    if d.get(y) is not None:
                        s += abs(d[y]); has = True
                return s if has else None
            sgai = _safe_div(_safe_div(sga(t), rev[t]), _safe_div(sga(p), rev[p]))
            # LVGI = lev_t/lev_p ; lev = (CL+LTD)/TA  (dùng nợ phải trả nếu thiếu)
            def lev(y):
                if liab.get(y) is not None:
                    return _safe_div(liab[y], ta.get(y))
                num = (cl.get(y, 0) + ltd.get(y, 0))
                return _safe_div(num, ta.get(y))
            lvgi = _safe_div(lev(t), lev(p))
            # TATA = (NI - CFO)/TA
            tata = _safe_div((ni.get(t, 0) - cfo.get(t, 0)), ta.get(t))
        except Exception:  # noqa: BLE001
            return None

        comps = {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
                 "DEPI": depi, "SGAI": sgai, "LVGI": lvgi, "TATA": tata}
        # thiếu biến nào → không tính (tránh bịa)
        need = ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA"]
        if any(comps[k] is None for k in need):
            return None
        m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
             + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
        return m, comps

    # ------------------------------------------------------------------
    # 3. DÒNG TIỀN — cơ cấu CFO/CFI/CFF, FCF, capex vs khấu hao, cổ tức
    # ------------------------------------------------------------------
    def _cashflow(self, dd: DeepDive, S: dict) -> None:
        sec = Section("3. Phân tích dòng tiền")
        cfo, cfi, cff = S["cfo"], S["cfi"], S["cff"]
        capex, dep, div = S["capex"], S["dep"], S["div_paid"]
        yrs = sorted(cfo)
        rows = []
        for y in yrs:
            c = cfo.get(y); cx = capex.get(y)
            fcf = (c + cx) if (c is not None and cx is not None) else None  # capex đã âm
            rows.append({"Năm": y, "CFO": c, "CFI": cfi.get(y), "CFF": cff.get(y),
                         "Capex": cx, "FCF": fcf, "Cổ tức trả": div.get(y)})
        if rows:
            sec.table = pd.DataFrame(rows)
        if not yrs:
            dd.sections["cashflow"] = sec
            return
        y1 = yrs[-1]
        c1 = cfo.get(y1); cx1 = capex.get(y1); dep1 = dep.get(y1)
        fcf1 = (c1 + cx1) if (c1 is not None and cx1 is not None) else None
        sec.lines.append(
            f"Năm {y1}: CFO {_t(c1)}, đầu tư (CFI) {_t(cfi.get(y1))}, tài chính (CFF) "
            f"{_t(cff.get(y1))}. Dòng tiền tự do FCF (CFO − capex) ≈ {_t(fcf1)}.")
        # capex vs khấu hao: đầu tư mở rộng hay chỉ duy trì?
        if cx1 is not None and dep1:
            ratio = _safe_div(abs(cx1), dep1)
            if ratio is not None:
                trạng = ("đầu tư mở rộng mạnh" if ratio > 1.5 else
                         "duy trì" if ratio >= 0.8 else "đầu tư dưới mức khấu hao (co lại)")
                caveat = (" FCF âm ở đây đến từ capex lớn — KHÔNG xấu nếu mở rộng hiệu quả "
                          "(soi ROIC)." if (ratio > 1.5 and fcf1 is not None and fcf1 < 0) else "")
                sec.lines.append(
                    f"Capex {_t(abs(cx1))} so khấu hao {_t(dep1)} = {ratio:.1f}x → {trạng}.{caveat}")
        # cổ tức có được tài trợ bằng tiền thật không? (chỉ khi cổ tức ĐÁNG KỂ ≥1 tỷ)
        if div.get(y1) is not None and fcf1 is not None:
            dv = abs(div[y1])
            if dv >= 1e9 and fcf1 < 0:
                sec.flags.append(
                    f"🔻 Chi trả cổ tức {_t(dv)} {y1} trong khi FCF ÂM ({_t(fcf1)}) — cổ tức "
                    f"phải tài trợ bằng vay/tiền tích lũy, không bền nếu kéo dài.")
        # CFO âm
        if c1 is not None and c1 < 0:
            ni1 = S["ni"].get(y1)
            extra = f" dù lãi ròng dương ({_t(ni1)})" if (ni1 and ni1 > 0) else ""
            sec.flags.append(
                f"🔻 CFO ÂM {_t(c1)} năm {y1}{extra} — hoạt động kinh doanh không tạo tiền.")
        dd.sections["cashflow"] = sec

    # ------------------------------------------------------------------
    # 4. CÂN ĐỐI KẾ TOÁN — đòn bẩy, thanh khoản, chất lượng tài sản, chu kỳ vốn lưu động
    # ------------------------------------------------------------------
    def _balance_sheet(self, dd: DeepDive, S: dict) -> None:
        sec = Section("4. Cân đối kế toán & chu kỳ vốn lưu động")
        ta, liab, equity = S["ta"], S["liab"], S["equity"]
        cl, ca = S["cl"], S["ca"]
        st_debt, lt_debt = S["st_debt"], S["lt_debt"]
        cash, st_inv = S["cash"], S["st_inv"]
        yrs = sorted(ta)
        if not yrs:
            dd.sections["balance"] = sec
            return
        y1 = yrs[-1]
        de = _safe_div(liab.get(y1), equity.get(y1))
        cr = _safe_div(ca.get(y1), cl.get(y1))
        total_debt = (st_debt.get(y1, 0) or 0) + (lt_debt.get(y1, 0) or 0)
        cash_like = (cash.get(y1, 0) or 0) + (st_inv.get(y1, 0) or 0)
        net_debt = total_debt - cash_like
        sec.lines.append(
            f"Cuối {y1}: tổng tài sản {_t(ta.get(y1))}, nợ phải trả {_t(liab.get(y1))} "
            f"(D/E {de:.2f} lần)" + (f", tỷ lệ thanh toán hiện hành {cr:.2f}" if cr else "") + ".")
        sec.lines.append(
            f"Vay có lãi {_t(total_debt)} (ngắn hạn {_t(st_debt.get(y1))} + dài hạn "
            f"{_t(lt_debt.get(y1))}); tiền + đầu tư ngắn hạn {_t(cash_like)} → nợ ròng {_t(net_debt)}"
            + (" (tiền ròng dương — không áp lực nợ)." if net_debt < 0 else "."))
        # cờ đòn bẩy + thanh khoản
        if de is not None and de > 2 and cr is not None and cr < 1:
            sec.flags.append(
                f"🔻 Đòn bẩy cao D/E {de:.1f} lần kèm thanh khoản yếu (hiện hành {cr:.2f}<1) — "
                f"áp lực trả nợ ngắn hạn.")
        # độ phủ lãi vay (EBIT/|lãi vay|) — khả năng gánh nợ
        op1 = S["op"].get(y1); int1 = S["int"].get(y1)
        if op1 is not None and int1 is not None and abs(int1) > 1e9:
            cov = _safe_div(op1, abs(int1))
            if cov is not None:
                sec.lines.append(
                    f"Độ phủ lãi vay {y1}: LN từ HĐKD / lãi vay = {cov:.1f} lần.")
                if cov < 2:
                    sec.flags.append(
                        f"🔻 Độ phủ lãi vay {cov:.1f} lần (<2) {y1} — biên an toàn trả lãi mỏng.")

        # --- chu kỳ vốn lưu động DSO/DIO/DPO/CCC ---
        # WATCHDOG: DN thâm dụng tồn kho dài hạn (BĐS, xây dựng, hạ tầng) hạch toán dự án dở dang
        # vào tồn kho nhưng giá vốn ghi nhận nhỏ giọt → DIO/CCC nổ tới hàng nghìn ngày, VÔ NGHĨA.
        # Ngưỡng phi lý: DIO > 900 ngày (~2.5 năm) → coi chu kỳ vốn lưu động KHÔNG áp dụng.
        rev, cogs = S["rev"], S["cogs"]
        recv_trade, inv, payable = S["recv_trade"], S["inv"], S["payable"]
        rows = []
        inv_heavy = False
        for y in yrs[-4:]:
            r = rev.get(y); c = abs(cogs.get(y)) if cogs.get(y) is not None else None
            dso = _safe_div(recv_trade.get(y), r)
            dso = dso * DAYS if dso is not None else None
            dio = _safe_div(inv.get(y), c)
            dio = dio * DAYS if dio is not None else None
            dpo = _safe_div(payable.get(y), c)
            dpo = dpo * DAYS if dpo is not None else None
            if dio is not None and dio > 900:
                inv_heavy = True
            ccc = (dso + dio - dpo) if None not in (dso, dio, dpo) else None
            rows.append({"Năm": y, "DSO (ngày)": dso, "DIO (ngày)": dio,
                         "DPO (ngày)": dpo, "CCC (ngày)": ccc})
        if rows and inv_heavy:
            sec.lines.append(
                "Chu kỳ vốn lưu động (DSO/DIO/CCC): KHÔNG áp dụng — doanh nghiệp thâm dụng tồn "
                "kho dài hạn (bất động sản/xây dựng), giá vốn ghi nhận theo tiến độ dự án nên "
                "chỉ số vòng quay bị méo. Soi trực tiếp tồn kho và dòng tiền thay thế.")
        elif rows:
            sec.table = pd.DataFrame(rows)
            last = rows[-1]
            if last["CCC (ngày)"] is not None:
                sec.lines.append(
                    f"Chu kỳ chuyển hóa tiền mặt {y1}: phải thu {last['DSO (ngày)']:.0f} + tồn kho "
                    f"{last['DIO (ngày)']:.0f} − phải trả {last['DPO (ngày)']:.0f} = "
                    f"{last['CCC (ngày)']:.0f} ngày. Càng dài → càng chôn vốn vào vận hành.")
                # xu hướng xấu đi
                first = next((r for r in rows if r["CCC (ngày)"] is not None), None)
                if first and first is not last and last["CCC (ngày)"] - first["CCC (ngày)"] > 30:
                    sec.flags.append(
                        f"🔻 Chu kỳ tiền mặt kéo dài thêm "
                        f"{last['CCC (ngày)']-first['CCC (ngày)']:.0f} ngày "
                        f"({first['Năm']}→{y1}) — vốn lưu động bị chôn nhiều hơn.")
        dd.sections["balance"] = sec

    # ------------------------------------------------------------------
    # 5. ĐIỂM CẢNH BÁO — Altman Z'' (thị trường mới nổi) + Piotroski F
    # ------------------------------------------------------------------
    def _distress(self, dd: DeepDive, S: dict, ratios: pd.DataFrame) -> None:
        sec = Section("5. Điểm cảnh báo kiệt quệ & sức khỏe cơ bản")
        z = self._altman_z(S)
        if z is not None:
            zscore, zone = z
            sec.lines.append(
                f"Altman Z''-score (bản thị trường mới nổi) = {zscore:.2f} → {zone}. "
                f"*Ngưỡng: >2.6 an toàn · 1.1–2.6 xám · <1.1 nguy cơ kiệt quệ. Hiệu chỉnh gốc "
                f"cho DN Mỹ, dùng tham khảo.*")
            if zscore < 1.1:
                sec.flags.append(
                    f"🔻 Altman Z'' {zscore:.2f} < 1.1 — vùng CẢNH BÁO nguy cơ kiệt quệ tài "
                    f"chính (tham khảo).")
        f = self._piotroski(S)
        if f is not None:
            fscore, detail, roa_neg, cfo_neg = f
            sec.lines.append(
                f"Piotroski F-score = {fscore}/9. *Điểm này đo ĐÀ CẢI THIỆN năm-qua-năm (sinh "
                f"lời/đòn bẩy/hiệu quả), không phải chất lượng tuyệt đối — blue-chip đã ở đỉnh có "
                f"thể điểm thấp mà vẫn khỏe.* Đạt: {detail}.")
            # chỉ thành cờ đỏ khi RẤT yếu VÀ có yếu tố tuyệt đối xấu (lỗ hoặc CFO âm)
            if fscore <= 2 and (roa_neg or cfo_neg):
                sec.flags.append(
                    f"🔻 Piotroski F-score rất thấp ({fscore}/9) kèm "
                    f"{'ROA âm' if roa_neg else 'CFO âm'} — nền tảng cơ bản suy yếu trên diện rộng.")
            elif fscore >= 7:
                dd.positives.append(f"✅ Piotroski F-score {fscore}/9 — nhiều mặt cơ bản đang cải thiện.")
        dd.sections["distress"] = sec

    def _altman_z(self, S: dict) -> Optional[Tuple[float, str]]:
        """Altman Z''-score cho thị trường mới nổi (không cần giá trị vốn hóa thị trường):
        Z'' = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
        X1=vốn lưu động/TA, X2=LN giữ lại/TA, X3=EBIT/TA, X4=vốn CSH sổ sách/nợ phải trả."""
        ta, ca, cl = S["ta"], S["ca"], S["cl"]
        re, equity, liab = S["re"], S["equity"], S["liab"]
        op, fin_exp = S["op"], S["fin_exp"]
        yrs = sorted(set(ta) & set(ca) & set(cl))
        if not yrs:
            return None
        y = yrs[-1]
        TA = ta.get(y)
        if not TA:
            return None
        wc = _safe_div((ca.get(y, 0) - cl.get(y, 0)), TA)
        x2 = _safe_div(re.get(y), TA)
        # EBIT ≈ LN từ HĐKD (đã sát EBIT cho DN phi tài chính); fallback pretax + |lãi vay|
        ebit = op.get(y)
        if ebit is None:
            pt = S["pretax"].get(y); iv = S["int"].get(y)
            ebit = (pt + abs(iv)) if (pt is not None and iv is not None) else None
        x3 = _safe_div(ebit, TA)
        x4 = _safe_div(equity.get(y), liab.get(y))
        if None in (wc, x2, x3, x4):
            return None
        z = 3.25 + 6.56 * wc + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        zone = ("an toàn" if z > 2.6 else "vùng xám" if z >= 1.1 else "NGUY CƠ kiệt quệ")
        return z, zone

    def _piotroski(self, S: dict) -> Optional[Tuple[int, str, bool, bool]]:
        """Piotroski F-score (0–9). Cần 2 năm liền kề. Trả (điểm, chi tiết, roa_âm, cfo_âm)."""
        ni, cfo, ta = S["ni"], S["cfo"], S["ta"]
        rev, gross, cogs = S["rev"], S["gross"], S["cogs"]
        ca, cl, lt_debt = S["ca"], S["cl"], S["lt_debt"]
        share_issue = S["share_issue"]
        yrs = sorted(set(ni) & set(ta))
        if len(yrs) < 2:
            return None
        t, p = yrs[-1], yrs[-2]
        pts = 0; items = []

        roa_t = _safe_div(ni.get(t), ta.get(t)); roa_p = _safe_div(ni.get(p), ta.get(p))
        roa_neg = roa_t is not None and roa_t <= 0
        cfo_neg = cfo.get(t) is not None and cfo[t] <= 0
        if roa_t is not None and roa_t > 0:
            pts += 1; items.append("ROA>0")
        if cfo.get(t) is not None and cfo[t] > 0:
            pts += 1; items.append("CFO>0")
        if roa_t is not None and roa_p is not None and roa_t > roa_p:
            pts += 1; items.append("ROA↑")
        if cfo.get(t) is not None and ni.get(t) is not None and cfo[t] > ni[t]:
            pts += 1; items.append("CFO>LN")
        # đòn bẩy dài hạn giảm
        lev_t = _safe_div(lt_debt.get(t), ta.get(t)); lev_p = _safe_div(lt_debt.get(p), ta.get(p))
        if lev_t is not None and lev_p is not None and lev_t < lev_p:
            pts += 1; items.append("nợ DH↓")
        # thanh khoản tăng
        cur_t = _safe_div(ca.get(t), cl.get(t)); cur_p = _safe_div(ca.get(p), cl.get(p))
        if cur_t is not None and cur_p is not None and cur_t > cur_p:
            pts += 1; items.append("thanh khoản↑")
        # không phát hành thêm cổ phiếu đáng kể
        if share_issue.get(t) is not None and share_issue[t] <= 0.01 * (ta.get(t) or 1):
            pts += 1; items.append("không pha loãng")
        elif share_issue.get(t) is None:
            pts += 1; items.append("không pha loãng")
        # biên gộp tăng
        gm_t = _safe_div(gross.get(t), rev.get(t)); gm_p = _safe_div(gross.get(p), rev.get(p))
        if gm_t is not None and gm_p is not None and gm_t > gm_p:
            pts += 1; items.append("biên gộp↑")
        # vòng quay tài sản tăng
        at_t = _safe_div(rev.get(t), ta.get(t)); at_p = _safe_div(rev.get(p), ta.get(p))
        if at_t is not None and at_p is not None and at_t > at_p:
            pts += 1; items.append("vòng quay TS↑")
        return pts, ", ".join(items) if items else "—", roa_neg, cfo_neg

    # ------------------------------------------------------------------
    # 6. ĐỊNH GIÁ (tùy chọn, dùng lại vn_valuation)
    # ------------------------------------------------------------------
    def _valuation(self, dd: DeepDive, symbol: str) -> None:
        if self.valuation is None:
            return
        try:
            a = self.valuation.assess(symbol)
        except Exception:  # noqa: BLE001
            return
        if not a:
            return
        sec = Section("6. Định giá")
        for nd in (a.get("nhận_định") or []):
            sec.lines.append(str(nd))
        for flag in (a.get("cờ_rủi_ro") or []):
            # cờ định giá đưa vào phần này nhưng KHÔNG nhân đôi vào tổng cờ forensic
            if str(flag) not in sec.lines:
                sec.lines.append(f"⚠️ {flag}")
        if not sec.lines:
            sec.lines.append("Không đủ dữ liệu định giá.")
        dd.sections["valuation"] = sec

    # ------------------------------------------------------------------
    # Tổng hợp cờ + verdict
    # ------------------------------------------------------------------
    def _make_verdict(self, dd: DeepDive) -> None:
        for sec in dd.sections.values():
            dd.red_flags.extend(sec.flags)
        n = len(dd.red_flags)
        if n == 0:
            dd.verdict = ("KHÔNG phát hiện cờ đỏ forensic nào — báo cáo tài chính có chất lượng "
                          "khá, lợi nhuận ra tiền, cân đối lành mạnh (theo dữ liệu VCI).")
        elif n <= 2:
            dd.verdict = (f"Có {n} điểm cần lưu ý nhưng chưa nghiêm trọng — theo dõi các cờ bên "
                          f"dưới ở các kỳ tới.")
        else:
            dd.verdict = (f"⚠️ {n} cờ đỏ forensic — chất lượng lợi nhuận/dòng tiền/cân đối có vấn "
                          f"đề đáng kể. Thận trọng, đọc kỹ thuyết minh trước khi định giá.")


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    dd = VNDeepDive()
    for sym in ("FPT", "NVL", "HAG"):
        r = dd.analyze(sym)
        print(f"\n{'='*70}\n{sym} — {r.verdict}\n{'='*70}")
        if r.error:
            print("LỖI:", r.error); continue
        for key, sec in r.sections.items():
            print(f"\n## {sec.title}")
            for ln in sec.lines:
                print("  ", ln)
            for fl in sec.flags:
                print("   »", fl)
        print(f"\n>> TỔNG: {len(r.red_flags)} cờ đỏ, {len(r.positives)} điểm cộng")
