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

import html as _html
import logging
import re
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
I_MINOR = "Lợi ích của cổ đông thiểu số"        # phần lãi thuộc đối tác trong công ty con
I_NI_PARENT = "Lợi nhuận của Cổ đông của Công ty mẹ"
I_EPS = "Lãi cơ bản trên cổ phiếu (VND)"

# --- Cân đối kế toán ---
B_CA = "TÀI SẢN NGẮN HẠN"
B_CASH = "Tiền và tương đương tiền"
B_ST_INVEST = "Đầu tư ngắn hạn"
B_RECV = "Các khoản phải thu"                      # phải thu ngắn hạn (tổng)
B_RECV_TRADE = "Phải thu khách hàng"              # phải thu thương mại (bán chịu)
B_PREPAY = "Trả trước người bán"                   # ứng trước cho nhà cung cấp (không liên quan DT)
B_RECV_OTHER = "Phải thu khác"                     # phải thu khác (không liên quan DT)
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
B_INV_ASSOC = "Đầu tư vào các công ty liên kết"   # đầu tư equity-method (không kiểm soát)
B_MINOR = "Lợi ích của cổ đông thiểu số"

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
CF_INVEST_OTHER = "Tiền chi đầu tư góp vốn vào đơn vị khác"   # rót vốn vào DN khác (đa dạng hóa/M&A) — lưu ÂM

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


def _strip_html(s: Optional[str]) -> str:
    """Bỏ thẻ HTML rồi giải mã HTML entity chuẩn (html.unescape phủ &oacute;/&acirc;... đầy đủ)."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)                       # &oacute;→ó, &acirc;→â, &nbsp;→ , &sup2;→²...
    return re.sub(r"\s+", " ", s).strip()


# ============================================================================
# Cấu trúc kết quả
# ============================================================================
@dataclass
class Section:
    title: str
    lines: List[str] = field(default_factory=list)     # dòng số liệu/nhận định
    table: Optional[pd.DataFrame] = None                # bảng số (tùy chọn)
    flags: List[str] = field(default_factory=list)      # cờ đỏ của phần
    explain: List[str] = field(default_factory=list)    # "💡 Đọc hiểu" — diễn giải cho người mới


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
    watch_items: List[str] = field(default_factory=list)   # điều cần theo dõi CỤ THỂ (data-driven)
    metrics: Dict[str, object] = field(default_factory=dict)  # số chốt để dựng luận điểm
    thesis: str = ""           # luận điểm đầu tư (đoạn văn mạch lạc)
    bull: List[str] = field(default_factory=list)   # điểm hấp dẫn
    bear: List[str] = field(default_factory=list)   # điều khiến e ngại
    takeaways: List[str] = field(default_factory=list)   # điều rút ra cho DN (hàm ý)
    lenses: List[str] = field(default_factory=list)      # góc nhìn theo loại NĐT
    scenarios: List[str] = field(default_factory=list)   # kịch bản bull/base/bear
    info: Dict[str, object] = field(default_factory=dict)  # giá/vốn hóa/rating Vietcap
    verdict: str = ""
    profile: str = ""          # mô tả bản chất kinh doanh (từ VCI)
    error: Optional[str] = None


class VNDeepDive:
    """Sinh báo cáo forensic một mã. Dùng lại VCIFundamentals (và tùy chọn sectors/valuation)."""

    def __init__(self, fx: Optional[VCIFundamentals] = None,
                 sectors=None, valuation=None, group=None):
        self.fx = fx or VCIFundamentals()
        self.sectors = sectors        # VCISectors (tùy chọn — để biết ngành + is_bank)
        self.valuation = valuation    # VNValuation (tùy chọn — nhận định đắt/rẻ)
        self.group = group            # VNGroup (tùy chọn — danh sách công ty con/liên kết)
        self._listed_cache: Optional[set] = None

    def _listed_universe(self) -> set:
        """Tập mã sàn (để đánh dấu công ty con niêm yết). Cache trong phiên."""
        if self._listed_cache is None:
            self._listed_cache = set()
            if self.sectors is not None:
                try:
                    m = self.sectors.get_industry_map()
                    self._listed_cache = {str(s).upper() for s in m["symbol"]}
                except Exception:  # noqa: BLE001
                    pass
        return self._listed_cache

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

        # hồ sơ công ty (bản chất kinh doanh) — không chặn nếu lỗi
        info = {}
        try:
            info = self.fx.company_info(symbol)
        except Exception:  # noqa: BLE001
            pass
        if info:
            if not name:
                name = info.get("viOrganShortName") or info.get("viOrganName") or ""
            if not sector:
                sector = info.get("sectorVn") or info.get("sector") or ""

        years = sorted(set(self._series(inc, I_REV)) |
                       set(self._series(bal, B_TA)) | set(self._series(cf, CF_CFO)))
        dd = DeepDive(symbol, name or symbol, is_bank, sector, years)
        dd.profile = _strip_html(info.get("profile") or info.get("enProfile") or "")
        # giá/vốn hóa + khuyến nghị Vietcap (có nguồn) để dựng header + góc nhìn
        if info:
            price = info.get("currentPrice"); div = info.get("dividendPerShareTsr")
            dd.info = {
                "price": price, "marketcap": info.get("marketCap"),
                "rating": info.get("rating"), "target": info.get("targetPrice"),
                "upside": info.get("upsideToTargetPercent"),
                "div_ps": div, "proj_tsr": info.get("projectedTSRPercentage"),
                "analyst": info.get("analyst"),
                "div_yield": (_safe_div(div, price) if (div is not None and price) else None),
            }

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
            "minor": self._series(inc, I_MINOR), "inv_assoc": self._series(bal, B_INV_ASSOC),
            "ca": self._series(bal, B_CA), "cash": self._series(bal, B_CASH),
            "st_inv": self._series(bal, B_ST_INVEST), "recv": self._series(bal, B_RECV),
            "recv_trade": self._series(bal, B_RECV_TRADE), "inv": self._series(bal, B_INV),
            "prepay": self._series(bal, B_PREPAY), "recv_other": self._series(bal, B_RECV_OTHER),
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
            "invest_other": self._series(cf, CF_INVEST_OTHER),
        }

        self._group_structure(dd, S)
        self._business_picture(dd, S)
        self._earnings_quality(dd, S)
        self._cashflow(dd, S)
        self._balance_sheet(dd, S)
        self._distress(dd, S, ratios)
        self._valuation(dd, symbol)

        self._recent_quarters(dd, symbol)
        self._quarterly_trends(dd, symbol)
        self._management_track(dd, symbol, S, ratios)
        self._make_verdict(dd)
        self._conclusion(dd)
        self._investment_view(dd)
        self._price_anchors(dd, ratios)
        return dd

    def _recent_quarters(self, dd: DeepDive, symbol: str) -> None:
        """Đọc số QUÝ (độc lập) để bắt turnaround/suy giảm gần đây mà số NĂM chưa phản ánh —
        vá lỗi 'hệ chỉ nhìn quá khứ theo năm' (đã làm MSR 2025 nhìn xấu dù 2026 bật). GUARDRAIL:
        đòi 2 quý xác nhận (giảm nhiễu 1 quý lẻ như FPT 2026Q1); chỉ nêu tín hiệu, không cờ đỏ."""
        try:
            q = self.fx.get_statement(symbol, "INCOME_STATEMENT", "quarter")
        except Exception:  # noqa: BLE001
            return
        if q is None or q.empty or "lengthReport" not in q.columns or I_NI not in q.columns:
            return
        ni_col = q[I_NI]
        if isinstance(ni_col, pd.DataFrame):
            ni_col = ni_col.iloc[:, 0]
        rows = []
        for y, lr, ni in zip(q["yearReport"], q["lengthReport"], ni_col):
            try:
                rows.append((int(y), int(lr), float(ni)))
            except (TypeError, ValueError):
                continue
        rows = [r for r in rows if not np.isnan(r[2])]
        rows.sort(key=lambda x: (x[0], x[1]))
        if len(rows) < 6:
            return
        (y1, q1, ni1), (y0, q0, ni0) = rows[-1], rows[-2]
        same = [r[2] for r in rows if r[0] == y1 - 1 and r[1] == q1]  # cùng kỳ năm trước
        ni_prevyr = same[0] if same else None
        older = [r[2] for r in rows[-6:-2]]           # 4 quý trước 2 quý gần nhất
        older_losses = sum(1 for x in older if x < 0)
        sec = dd.sections.get("business")
        # TURNAROUND: 2 quý liền có lãi sau chuỗi lỗ → số năm chưa phản ánh.
        # BÀI HỌC (cross-check NVL vs MSR): mã VỪA THOÁT LỖ thì tỷ số CFO 3 năm bị méo/không tính
        # được (3 năm lỗ) → hệ tài chính VỀ BẢN CHẤT không phân biệt được turnaround THẬT (MSR nhờ
        # tungsten) vs lãi TRÊN GIẤY (NVL tái cơ cấu). KHÔNG cố tự phân loại — LUÔN buộc cross-check.
        if ni1 > 0 and ni0 > 0 and older_losses >= 2:
            dd.metrics["recent_turn"] = "up_unconfirmed"
            if sec:
                sec.lines.append(
                    f"🟡 Diễn biến gần đây (theo quý): 2 quý liền có lãi (Q{q0}/{y0} {_t(ni0)}, "
                    f"Q{q1}/{y1} {_t(ni1)}) sau chuỗi lỗ — hệ bắt được khúc ngoặt mà số NĂM chưa "
                    f"phản ánh, NHƯNG không tự biết là turnaround tiền thật (kiểu MSR nhờ tungsten) "
                    f"hay lãi trên giấy (kiểu NVL tái cơ cấu). **BẮT BUỘC cross-check ngoài: lãi "
                    f"quý đến từ hoạt động cốt lõi/catalyst thật, hay khoản một lần?**")
        # SUY GIẢM sớm: quý gần nhất tụt mạnh so cùng kỳ VÀ so quý trước (2 tín hiệu)
        elif (ni_prevyr is not None and ni_prevyr > 0 and ni1 < 0.5 * ni_prevyr
              and ni1 < ni0):
            dd.metrics["recent_turn"] = "down"
            if sec:
                sec.lines.append(
                    f"🔴 Diễn biến gần đây (theo quý): Q{q1}/{y1} lãi {_t(ni1)} tụt mạnh so cùng kỳ "
                    f"năm trước ({_t(ni_prevyr)}) và so quý liền trước — cảnh báo sớm, số năm chưa "
                    f"phản ánh. *(1 quý có thể nhiễu — chờ quý sau xác nhận.)*")

    # ------------------------------------------------------------------
    # 8. DIỄN BIẾN THEO QUÝ — xu hướng biên & DSO (số năm làm mượt, quý lộ đà)
    # ------------------------------------------------------------------
    @staticmethod
    def _qseries(df, col) -> Dict[tuple, float]:
        """Chuỗi theo (năm, quý) từ báo cáo QUÝ; quý nằm ở cột lengthReport (1-4), số RỜI RẠC."""
        if df is None or df.empty or "lengthReport" not in df.columns or col not in df.columns:
            return {}
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        out: Dict[tuple, float] = {}
        for y, lr, v in zip(df["yearReport"], df["lengthReport"], s):
            try:
                out[(int(y), int(lr))] = float(v)
            except (TypeError, ValueError):
                continue
        return out

    def _quarterly_trends(self, dd: DeepDive, symbol: str) -> None:
        """Biên gộp/ròng + DSO theo QUÝ (~8 quý). Số năm làm mượt đà bào mòn/cải thiện; quý lộ ra."""
        if dd.is_bank:
            return
        try:
            qi = self.fx.get_statement(symbol, "INCOME_STATEMENT", "quarter")
            qb = self.fx.get_statement(symbol, "BALANCE_SHEET", "quarter")
        except Exception:  # noqa: BLE001
            return
        rev = self._qseries(qi, I_REV); ni = self._qseries(qi, I_NI); gross = self._qseries(qi, I_GROSS)
        recv = self._qseries(qb, B_RECV_TRADE) or self._qseries(qb, B_RECV)
        keys = sorted(rev.keys())
        used = [k for k in keys if rev.get(k) and rev[k] > 0]
        if len(used) < 5:
            return
        rows, nm_seq, dso_seq = [], [], []
        for i, k in enumerate(keys):
            r = rev.get(k)
            if not r or r <= 0:
                continue
            gm = _safe_div(gross.get(k), r); nm = _safe_div(ni.get(k), r)
            # DSO = phải thu KH / doanh thu TTM (4 quý) × 365 (khử mùa vụ)
            win4 = keys[max(0, i - 3):i + 1]
            ttm = sum(rev.get(kk, 0) for kk in win4) if len(win4) == 4 else None
            dso = (recv.get(k) / ttm * 365) if (ttm and ttm > 0 and recv.get(k) is not None) else None
            rows.append({"Quý": f"Q{k[1]}/{k[0]}", "Doanh thu (tỷ)": round(r / 1e9),
                         "Biên gộp": f"{gm*100:.1f}%" if gm is not None else "—",
                         "Biên ròng": f"{nm*100:.1f}%" if nm is not None else "—",
                         "DSO (ngày)": round(dso) if dso is not None else None})
            nm_seq.append(nm if nm is not None else np.nan)
            dso_seq.append(dso if dso is not None else np.nan)
        if len(rows) < 4:
            return
        sec = Section("8. Diễn biến theo quý: xu hướng biên lợi nhuận & số ngày thu tiền (DSO)")
        sec.table = pd.DataFrame(rows[-8:])
        # xu hướng biên ròng: 4 quý gần vs 4 quý liền trước
        nm_arr = np.array(nm_seq, dtype=float)
        if np.sum(~np.isnan(nm_arr)) >= 6:
            last4 = np.nanmean(nm_arr[-4:]); prev4 = np.nanmean(nm_arr[-8:-4])
            if not np.isnan(last4) and not np.isnan(prev4):
                d = last4 - prev4
                word = ("CO DẦN 🔻" if d < -0.01 else "cải thiện" if d > 0.01 else "đi ngang")
                sec.lines.append(f"Biên ròng 4 quý gần nhất bình quân {last4*100:.1f}% vs 4 quý trước "
                                 f"{prev4*100:.1f}% → {word}.")
                if d < -0.01:
                    dd.metrics["margin_trend_q"] = "down"
        # xu hướng DSO: quý gần nhất vs 4 quý trước
        dso_arr = np.array(dso_seq, dtype=float)
        valid_dso = dso_arr[~np.isnan(dso_arr)]
        if len(valid_dso) >= 5:
            dnow = valid_dso[-1]; dprev = valid_dso[-5] if len(valid_dso) >= 5 else valid_dso[0]
            if dprev > 0:
                chg = dnow / dprev - 1
                if chg > 0.2 and dnow > 90:
                    sec.lines.append(f"DSO tăng từ ~{dprev:.0f} lên ~{dnow:.0f} ngày (+{chg*100:.0f}%) "
                                     f"qua ~1 năm — tiền bị chôn ở phải thu lâu hơn, theo dõi chất lượng thu tiền.")
                elif chg < -0.15:
                    sec.lines.append(f"DSO giảm từ ~{dprev:.0f} xuống ~{dnow:.0f} ngày — thu tiền nhanh lên.")
                else:
                    sec.lines.append(f"DSO đi ngang quanh ~{dnow:.0f} ngày.")
        if not sec.lines:
            sec.lines.append("Không đủ dữ liệu quý để kết luận xu hướng.")
        sec.explain = [
            "Báo cáo NĂM làm mượt: một năm biên tốt che khúc suy yếu ở quý cuối. Đọc theo QUÝ thấy "
            "ĐÀ thật — biên đang co lại hay mở ra, DSO (số ngày thu tiền) đang phình hay rút. Biên "
            "ròng co dần + DSO phình = cảnh báo sớm chất lượng lợi nhuận, thường lộ trước số năm."]
        dd.sections["quarterly"] = sec

    # ------------------------------------------------------------------
    # 9. TRACK RECORD BAN LÃNH ĐẠO — ROIC theo thời gian & phân bổ vốn
    # ------------------------------------------------------------------
    def _management_track(self, dd: DeepDive, symbol: str, S: Dict, ratios) -> None:
        """Ban lãnh đạo tạo hay ĐỐT giá trị: ROIC qua các năm + lịch sử phân bổ vốn (capex, rót
        vốn sang mảng mới, cổ tức, pha loãng). Suất sinh lời trên vốn giảm dưới chi phí vốn dù rót
        nhiều vốn = phân bổ vốn hủy giá trị (vd đa dạng hóa không hiệu quả)."""
        if dd.is_bank:
            return
        roic: Dict[int, float] = {}
        if ratios is not None and not ratios.empty and "roic" in ratios.columns:
            ann = ratios[ratios["ratioType"] == "RATIO_YEAR"] if "ratioType" in ratios.columns else ratios
            for y, v in zip(ann.get("yearReport", []), ann.get("roic", [])):
                try:
                    fv = float(v)
                    if -1 < fv < 2:  # guardrail số rác
                        roic[int(y)] = fv
                except (TypeError, ValueError):
                    continue
        if len(roic) < 4:
            return
        years = sorted(roic)
        win = years[-7:]
        half = max(1, len(win) // 2)
        early = [roic[y] for y in win[:half]]
        late = [roic[y] for y in win[-half:]]
        roic_early = sum(early) / len(early)
        roic_late = sum(late) / len(late)
        roic_now = roic[win[-1]]
        r = 0.13
        if self.valuation is not None:
            try:
                r = self.valuation._rg_for(symbol)[0]  # r theo ngành (nếu có)
            except Exception:  # noqa: BLE001
                r = getattr(self.valuation, "r", 0.13)

        def cum(key, signed=False):
            s = S.get(key, {}) or {}
            vals = [s.get(y) for y in win if s.get(y) is not None]
            return sum(v if signed else abs(v) for v in vals)

        capex = cum("capex"); invest_other = cum("invest_other")
        div = cum("div_paid"); equity_raised = cum("share_issue", signed=True)
        assoc = S.get("inv_assoc", {}) or {}
        a_win = [y for y in win if assoc.get(y) is not None]
        assoc_growth = (assoc[a_win[-1]] - assoc[a_win[0]]) if len(a_win) >= 2 else 0.0
        equity_now = None
        eq = S.get("equity", {}) or {}
        if eq:
            ey = [y for y in win if eq.get(y) is not None]
            equity_now = eq[ey[-1]] if ey else None
        deployed = capex + invest_other + max(0.0, assoc_growth)

        sec = Section("9. Track record ban lãnh đạo: suất sinh lời trên vốn (ROIC) & phân bổ vốn")
        sec.table = pd.DataFrame([{"Năm": y, "ROIC": f"{roic[y]*100:.1f}%"} for y in win])
        trend = ("GIẢM 🔻" if roic_late < roic_early - 0.015 else
                 "TĂNG" if roic_late > roic_early + 0.015 else "đi ngang")
        sec.lines.append(f"ROIC bình quân {win[0]}–{win[half-1]}: {roic_early*100:.1f}% → "
                         f"{win[-half]}–{win[-1]}: {roic_late*100:.1f}% ({trend}). "
                         f"So chi phí vốn ~{r*100:.0f}%: ROIC hiện {roic_now*100:.1f}% "
                         f"{'DƯỚI' if roic_now < r else 'trên'} chi phí vốn.")
        alloc = [f"chi {_t(capex)} mua sắm/xây dựng TSCĐ (capex)"]
        if invest_other > 0:
            alloc.append(f"{_t(invest_other)} rót vốn sang đơn vị khác")
        if assoc_growth > 0:
            alloc.append(f"đầu tư liên kết tăng {_t(assoc_growth)}")
        if div > 0:
            alloc.append(f"trả cổ tức {_t(div)}")
        if equity_raised > 0:
            alloc.append(f"huy động thêm {_t(equity_raised)} vốn cổ phần (pha loãng)")
        sec.lines.append(f"Phân bổ vốn {win[0]}–{win[-1]}: " + "; ".join(alloc) + ".")

        big_deploy = equity_now is not None and deployed > 0.20 * equity_now
        below_hurdle = sum(1 for y in win if roic[y] < r) >= max(2, len(win) - 2)
        if roic_late < r and roic_late < roic_early - 0.02 and big_deploy:
            sec.flags.append(
                f"🔻 Phân bổ vốn CHƯA tạo giá trị: rót ~{_t(deployed)} vào capex/đầu tư nhưng ROIC "
                f"giảm còn {roic_late*100:.1f}% (< chi phí vốn ~{r*100:.0f}%) — vốn mở rộng chưa "
                f"đẻ ra suất sinh lời tương xứng (vd đa dạng hóa/dự án mới chưa hiệu quả).")
            dd.metrics["capital_allocation"] = "destroying"
        elif below_hurdle and trend != "TĂNG":
            sec.lines.append(f"⚠️ ROIC nhiều năm dưới chi phí vốn (~{r*100:.0f}%) — đồng vốn sinh lời "
                             f"kém hơn kỳ vọng của cổ đông; cần lý do tăng trưởng bù lại.")
            dd.metrics["capital_allocation"] = "below_hurdle"
        elif roic_late >= r and roic_late >= roic_early - 0.005:
            dd.positives.append(f"✅ Phân bổ vốn kỷ luật: ROIC giữ {roic_late*100:.1f}% ≥ chi phí "
                                f"vốn ~{r*100:.0f}% qua chu kỳ.")
            dd.metrics["capital_allocation"] = "creating"
        sec.explain = [
            "ROIC = suất sinh lời trên đồng vốn thực bỏ vào kinh doanh. Đây là thước đo ban lãnh "
            "đạo dùng tiền GIỎI hay không: ROIC bền trên chi phí vốn (~13%) = mỗi đồng tái đầu tư "
            "sinh thêm giá trị; ROIC tụt dưới chi phí vốn dù rót nhiều vốn (đa dạng hóa, dự án mới) "
            "= đang ĐỐT giá trị dù doanh thu có thể vẫn tăng.",
            "Lịch sử phân bổ vốn cho thấy tiền đi đâu: capex (mở rộng cốt lõi), rót sang đơn vị "
            "khác (đa dạng hóa), cổ tức/mua lại CP (trả lại cổ đông), phát hành CP (pha loãng)."]
        dd.sections["management"] = sec

    def _price_anchors(self, dd: DeepDive, ratios) -> None:
        """Lưu neo định giá (P/E, P/B lịch sử) để dựng khung giá kịch bản. P/B ổn định hơn cho
        mã chu kỳ (P/E méo khi lợi nhuận dao động)."""
        price = (dd.info or {}).get("price")
        if ratios is None or ratios.empty or not price:
            return
        pe = [float(x) for x in ratios.get("pe", []) if pd.notna(x) and float(x) > 0]
        pb = [float(x) for x in ratios.get("pb", []) if pd.notna(x) and float(x) > 0]
        if pe:
            dd.metrics.update({"pe_now": pe[-1], "pe_lo": float(np.percentile(pe, 20)),
                               "pe_med": float(np.median(pe))})
        if pb:
            dd.metrics.update({"pb_now": pb[-1], "pb_lo": min(pb),
                               "pb_med": float(np.median(pb)), "pb_hi": float(np.percentile(pb, 80)),
                               "bvps": price / pb[-1]})

    # ------------------------------------------------------------------
    # 0. CẤU TRÚC TẬP ĐOÀN & BẢN CHẤT KINH DOANH
    # ------------------------------------------------------------------
    def _group_structure(self, dd: DeepDive, S: dict) -> None:
        sec = Section("1. Doanh nghiệp kinh doanh gì & cấu trúc sở hữu tập đoàn")
        # bản chất kinh doanh (mô tả)
        if dd.profile:
            prof = dd.profile
            if len(prof) > 700:                       # cắt gọn ~vài câu đầu
                cut = prof[:700]
                prof = cut[:cut.rfind(".") + 1] if "." in cut else cut + "…"
            sec.lines.append(f"**Bản chất kinh doanh:** {prof}")

        # DANH SÁCH công ty con & liên kết (CafeF) — lấy TRƯỚC để dùng khi diễn giải thiểu số
        gs = None
        if self.group is not None:
            try:
                gs = self.group.get_structure(dd.symbol, self._listed_universe())
            except Exception:  # noqa: BLE001
                gs = None
        # có công ty con sở hữu MỘT PHẦN đáng kể (20–95%, vốn ≥1000 tỷ)? → tập đoàn phức tạp
        partial_subs = []
        if gs is not None and not gs.error:
            partial_subs = [a for a in gs.subsidiaries
                            if a.ownership is not None and 20 <= a.ownership <= 95
                            and (a.capital or 0) >= 1000]

        ni, minor, parent = S["ni"], S["minor"], S["ni_parent"]
        assoc, jv = S["inv_assoc"], S["jv"]
        yrs = sorted(ni)
        y1 = yrs[-1] if yrs else None
        minor_pct = None
        minor_neg = False
        if y1 is not None:
            ni1 = ni.get(y1); mi1 = minor.get(y1); par1 = parent.get(y1)
            minor_pct = _safe_div(mi1, ni1) if (ni1 and ni1 > 0 and mi1 is not None) else None
            minor_neg = mi1 is not None and mi1 < 0
            if minor_pct is not None and mi1 and mi1 > 0:
                sec.lines.append(
                    f"Lãi ròng hợp nhất {y1} {_t(ni1)}, trong đó **cổ đông công ty mẹ (cổ đông "
                    f"của mã {dd.symbol}) hưởng {_t(par1)}** và cổ đông thiểu số (đối tác trong "
                    f"các công ty con chưa sở hữu 100%) hưởng {_t(mi1)} ≈ {minor_pct*100:.0f}%.")
            elif minor_neg and par1 is not None:
                # thiểu số ÂM: công ty con chưa sở hữu 100% đang LỖ, phần lỗ do thiểu số gánh bớt
                sec.lines.append(
                    f"Lãi ròng hợp nhất {y1} {_t(ni1)}, nhưng phần thuộc **cổ đông công ty mẹ "
                    f"({_t(par1)}) lại CAO HƠN** tổng hợp nhất — nghĩa là một số công ty con chưa "
                    f"sở hữu 100% đang LỖ, và phần lỗ đó cổ đông thiểu số gánh bớt "
                    f"({_t(mi1)}). Đây là dấu hiệu tập đoàn có mảng lỗ lớn (thường là mảng mới).")
            elif par1 is not None:
                simple = not partial_subs
                if simple:
                    sec.lines.append(
                        f"Lãi ròng hợp nhất {y1} {_t(ni1)}, gần như trọn vẹn thuộc cổ đông công "
                        f"ty mẹ ({_t(par1)}) — công ty con hầu như sở hữu 100%, cấu trúc đơn giản.")
                else:
                    sec.lines.append(
                        f"Lãi ròng hợp nhất {y1} {_t(ni1)}; phần cổ đông công ty mẹ {_t(par1)}. "
                        f"Cổ đông thiểu số ròng gần 0 nhưng tập đoàn VẪN có nhiều công ty con sở "
                        f"hữu một phần (xem bảng) — có thể do lãi/lỗ các công ty con bù trừ nhau.")
        # đầu tư công ty liên kết + lãi từ đó
        if y1 is not None and assoc.get(y1) and assoc[y1] > 0:
            line = f"Đầu tư vào công ty liên kết cuối {y1}: {_t(assoc[y1])}"
            if jv.get(y1):
                line += f"; lãi/lỗ từ liên doanh–liên kết trong năm: {_t(jv[y1])}"
            sec.lines.append(line + " (những công ty tập đoàn có ảnh hưởng nhưng KHÔNG kiểm soát).")

        if gs is not None and not gs.error and (gs.subsidiaries or gs.associates):
            sec.lines.append(
                f"Theo dữ liệu CafeF, tập đoàn gồm **{len(gs.subsidiaries)} công ty con** "
                f"(kiểm soát) và **{len(gs.associates)} công ty liên kết**"
                + (f", trong đó {gs.n_listed_subs} công ty con đang NIÊM YẾT — có thể phân tích "
                   f"sâu riêng bằng chính báo cáo này" if gs.n_listed_subs else "") + ".")
            rows = []
            for a in gs.subsidiaries[:10]:
                own = f"{a.ownership:.1f}%" if a.ownership is not None else "n/a*"
                rows.append({"Loại": "Con", "Công ty": a.name, "Sở hữu": own,
                             "Vốn ĐL (tỷ)": f"{a.capital:,.0f}" if a.capital else "—",
                             "Niêm yết": a.code if a.is_listed else "—"})
            for a in gs.associates[:6]:
                own = f"{a.ownership:.1f}%" if a.ownership is not None else "n/a*"
                rows.append({"Loại": "Liên kết", "Công ty": a.name, "Sở hữu": own,
                             "Vốn ĐL (tỷ)": f"{a.capital:,.0f}" if a.capital else "—",
                             "Niêm yết": a.code if a.is_listed else "—"})
            if rows:
                sec.table = pd.DataFrame(rows)
            if any(a.ownership_bad for a in gs.subsidiaries + gs.associates):
                sec.lines.append("*(n/a\\*: nguồn CafeF ghi tỷ lệ sở hữu vô lý cho một số công "
                                 "ty — đã bỏ qua thay vì hiển thị số sai.)*")

        # phân loại cấu trúc để dựng luận điểm
        dd.metrics["group_kind"] = ("conglomerate" if (minor_pct is not None and minor_pct > 0.10)
                                    else "loss_subs" if minor_neg
                                    else "complex" if partial_subs
                                    else "simple")
        if gs is not None and not gs.error:
            dd.metrics["n_subs"] = len(gs.subsidiaries)
            dd.metrics["n_listed_subs"] = gs.n_listed_subs

        # diễn giải cho người mới
        exp = []
        if minor_pct is not None and minor_pct > 0.10:
            exp.append(
                f"Đây là một TẬP ĐOÀN: {dd.symbol} sở hữu nhiều công ty con nhưng không nắm 100% "
                f"vài công ty trong đó. Báo cáo hợp nhất gộp toàn bộ doanh thu/lợi nhuận của các "
                f"công ty con, nhưng {minor_pct*100:.0f}% lợi nhuận đó thực chất thuộc về đối tác "
                f"— nên khi tính lãi trên mỗi cổ phiếu và định giá, chỉ dùng phần 'lợi nhuận công "
                f"ty mẹ' ({_t(parent.get(y1))}), KHÔNG dùng con số hợp nhất lớn hơn.")
            if minor_pct > 0.30:
                sec.flags.append(
                    f"🔻 Cổ đông thiểu số hưởng {minor_pct*100:.0f}% lãi ròng {y1} (>30%) — phần "
                    f"lớn lợi nhuận 'đẹp' trên báo cáo không chảy về túi cổ đông {dd.symbol}.")
        elif minor_neg:
            exp.append(
                "Cảnh báo đọc số: đừng mừng vội khi thấy 'lãi công ty mẹ' cao hơn lãi hợp nhất. "
                "Điều đó xảy ra vì có công ty con đang LỖ mà tập đoàn không sở hữu 100% — cổ đông "
                "thiểu số gánh bớt phần lỗ. Cần tách xem mảng nào đang lỗ (thường là mảng đầu tư "
                "mới, đốt tiền) trước khi kết luận tập đoàn khỏe.")
        elif partial_subs:
            exp.append(
                "Đây là tập đoàn có cấu trúc PHỨC TẠP (nhiều công ty con sở hữu một phần, xem "
                "bảng), dù phần lãi thuộc cổ đông thiểu số năm nay ròng gần 0 — nhiều khả năng do "
                "lãi ở công ty con này bù cho lỗ ở công ty con khác. Không nên coi là 'đơn giản'.")
        elif minor_pct is not None:
            exp.append(
                f"Cấu trúc sở hữu đơn giản: gần như toàn bộ lợi nhuận thuộc cổ đông {dd.symbol}, "
                f"không bị chia sẻ nhiều cho đối tác thiểu số.")
        if gs is not None and gs.n_listed_subs:
            listed = [a for a in gs.subsidiaries if a.is_listed][:3]
            exp.append(
                "Mẹo: " + ", ".join(f"{a.code} ({a.name})" for a in listed) + " là công ty con "
                "ĐANG NIÊM YẾT — bạn có thể chạy báo cáo forensic riêng cho từng mã đó để xem sức "
                "khỏe từng mảng của tập đoàn.")
        exp.append(
            "Lưu ý dữ liệu: bảng trên cho biết TÊN và TỶ LỆ SỞ HỮU công ty con (nguồn CafeF), "
            "nhưng ĐÓNG GÓP lợi nhuận/doanh thu của TỪNG công ty con chỉ có trong thuyết minh báo "
            "cáo tài chính (bản kiểm toán) — không nguồn API nào bóc sẵn. Với công ty con đã niêm "
            "yết thì xem trực tiếp báo cáo của mã đó; còn lại chỉ định tính qua tỷ lệ sở hữu.")
        sec.explain = exp
        dd.sections["group"] = sec

    # ------------------------------------------------------------------
    # 2. BỨC TRANH KINH DOANH — tách lợi nhuận CỐT LÕI khỏi khoản một lần
    # ------------------------------------------------------------------
    def _business_picture(self, dd: DeepDive, S: dict) -> None:
        sec = Section("2. Bức tranh kinh doanh: tăng trưởng, biên lợi nhuận & chất lượng cốt lõi")
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
        dd.metrics.update({"năm": y1, "rev": rev.get(y1), "rev_g": rev_g, "gm": gm1})
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
            dd.metrics["noncore_share"] = share
            sec.lines.append(
                f"Cơ cấu lợi nhuận {y1}: LN thuần từ hoạt động kinh doanh cốt lõi "
                f"{_t(op.get(y1))}; thu nhập ngoài cốt lõi (lãi tài chính + thu nhập khác + "
                f"liên doanh) {_t(noncore1)} ≈ {share*100:.0f}% lãi trước thuế.")
            if share > 0.40:
                sec.flags.append(
                    f"🔻 Chất lượng LN: {share*100:.0f}% lãi trước thuế {y1} đến từ NGOÀI hoạt "
                    f"động cốt lõi (thu tài chính/khác/liên doanh) — lợi nhuận kém bền vững, "
                    f"cần soi có phải khoản một lần.")

        # 💡 diễn giải
        gm_txt = f"{gm1*100:.0f} đồng" if gm1 else "…"
        om1 = _safe_div(op.get(y1), rev.get(y1))
        om_txt = f"{om1*100:.0f} đồng" if om1 else "…"
        sec.explain = [
            f"Biên gộp = lãi còn lại trên mỗi 100 đồng doanh thu sau giá vốn (~{gm_txt}); biên "
            f"hoạt động kinh doanh là sau khi trừ thêm chi phí bán hàng, quản lý (~{om_txt}). Biên "
            f"cao và ổn định nhiều năm → lợi thế cạnh tranh bền.",
            "Tách 'lợi nhuận cốt lõi' vì lãi bán hàng/dịch vụ lặp lại được, còn lãi tài chính, bán "
            "tài sản hay đánh giá lại thường chỉ đến một lần — công ty lãi chủ yếu nhờ khoản một "
            "lần thì con số đẹp năm nay khó lặp lại."]
        dd.sections["business"] = sec

    # ------------------------------------------------------------------
    # 2. CHẤT LƯỢNG LỢI NHUẬN — accruals, NI vs CFO, phải thu/tồn kho, Beneish
    # ------------------------------------------------------------------
    def _earnings_quality(self, dd: DeepDive, S: dict) -> None:
        sec = Section("3. Chất lượng lợi nhuận: lãi có ra tiền không & dấu hiệu làm đẹp sổ")
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
                dd.metrics["cfo_ni_3y"] = cover
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

        # --- 2c. ĐIỀU TRA phải thu: phình do đâu? có phải bán chịu không? DSO bao nhiêu? ---
        rev = S["rev"]; recv_tot = S["recv"]; recv_trade = S["recv_trade"]
        prepay = S["prepay"]; recv_other = S["recv_other"]; inv = S["inv"]
        ys = sorted(set(rev) & set(recv_trade))
        if len(ys) >= 2:
            y0, y1 = ys[-2], ys[-1]
            g_rev = _safe_div(rev[y1], rev[y0])
            g_rev = (g_rev - 1) if g_rev else None
            g_trade = _safe_div(recv_trade[y1], recv_trade[y0])
            g_trade = (g_trade - 1) if g_trade else None
            # số ngày thu tiền bình quân trên phải thu KHÁCH HÀNG
            dso0 = _safe_div(recv_trade.get(y0), rev.get(y0))
            dso1 = _safe_div(recv_trade.get(y1), rev.get(y1))
            dso0 = dso0 * DAYS if dso0 is not None else None
            dso1 = dso1 * DAYS if dso1 is not None else None
            # bóc tách tổng phải thu: khách hàng vs trả trước NCC vs khác
            if recv_tot.get(y1):
                comp = []
                for nm, d in (("khách hàng", recv_trade), ("trả trước người bán", prepay),
                              ("phải thu khác", recv_other)):
                    if d.get(y1):
                        comp.append(f"{nm} {_t(d[y1])}")
                if comp:
                    sec.lines.append(f"Cơ cấu phải thu {y1} ({_t(recv_tot[y1])}): " + ", ".join(comp) + ".")
            growth_flagged = False
            if g_trade is not None and g_rev is not None:
                sec.lines.append(
                    f"Phải thu khách hàng {y1} {_pct(g_trade)} so doanh thu {_pct(g_rev)}"
                    + (f"; số ngày thu tiền (DSO) {dso0:.0f}→{dso1:.0f} ngày"
                       if (dso0 and dso1) else "") + ".")
                # KẾT LUẬN có bằng chứng (không còn 'nghi' chung chung)
                if g_trade - g_rev > 0.20 and g_trade > 0.15:
                    growth_flagged = True
                    dso_txt = (f"số ngày thu tiền tăng từ {dso0:.0f} lên {dso1:.0f} ngày"
                               if (dso0 and dso1) else "vòng quay thu tiền chậm lại")
                    # hiệu chỉnh mức tuyệt đối: DSO vẫn thấp thì theo dõi, không báo động
                    if dso1 is not None and dso1 < 45:
                        tail = (f"Tuy vậy DSO {dso1:.0f} ngày vẫn ở mức thấp — đây là điểm THEO DÕI "
                                f"(tốc độ chứ chưa phải mức nguy hiểm), soi tiếp các kỳ sau.")
                    else:
                        tail = ("Công ty đang nới tay bán chịu để đẩy doanh số — lợi nhuận ghi nhận "
                                "nhưng tiền chưa về; đối chiếu thuyết minh xem có khoản phải thu "
                                "lớn/quá hạn/dồn vào ít khách hàng không.")
                    sec.flags.append(
                        f"🔻 Bán chịu tăng nhanh hơn bán hàng: phải thu KHÁCH HÀNG {_pct(g_trade)} "
                        f"vs doanh thu {_pct(g_rev)} ({y1}), {dso_txt}. {tail}")
            # LEVEL check — phải thu ở MỨC cao (vốn kẹt), KHÔNG chỉ tốc độ. Vá lỗi lọt LCG (DSO 244
            # ngày, 0 cờ vì không phình nhanh hơn doanh thu). Chỉ báo khi tốc-độ chưa bắt.
            if dso1 is not None and dso1 > 150 and not growth_flagged:
                sev = "RẤT cao" if dso1 > 220 else "cao"
                sec.flags.append(
                    f"🔻 Phải thu ở mức {sev}: DSO {dso1:.0f} ngày ≈ {dso1/DAYS*100:.0f}% doanh thu "
                    f"cả năm kẹt ở phải thu khách hàng {y1} — vốn bị chôn, rủi ro thu tiền / thanh "
                    f"toán chậm (đặc biệt với nhà thầu vốn ngân sách). Soi tuổi nợ + mức tập trung khách hàng.")
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
                # SO SÁNH CHÉO: Beneish (thống kê accrual/tăng trưởng) vs dòng tiền thực. Nếu CFO
                # 3 năm mạnh (≥80% lãi ròng) thì cash BÁC BỎ nghi ngờ thao túng → nhiễu mô hình
                # (bị kích bởi tăng trưởng/biên nhảy), KHÔNG tính cờ đỏ. Vá false-positive DDV/BCC.
                cfo_ni = dd.metrics.get("cfo_ni_3y")
                if cfo_ni is not None and cfo_ni >= 0.8:
                    sec.lines.append(
                        f"*Đối chiếu: Beneish vượt ngưỡng NHƯNG dòng tiền 3 năm bằng {cfo_ni*100:.0f}% "
                        f"lãi ròng — tiền thực bác bỏ nghi ngờ thao túng; coi là nhiễu mô hình (do "
                        f"tăng trưởng/biên nhảy), KHÔNG tính cờ đỏ.*")
                else:
                    sec.flags.append(
                        f"🔻 Beneish M-score {mscore:+.2f} > −1.78 — mô hình xếp vào nhóm CÓ khả năng "
                        f"thao túng lợi nhuận (tham khảo, cần kiểm chứng thuyết minh).")
            dd._beneish_comps = comps  # lưu để render bảng

        sec.explain = [
            "Phần quan trọng nhất. Lợi nhuận là con số kế toán (có thể ghi doanh thu trước khi thu "
            "tiền); CFO mới là tiền thật về. Lãi cao mà CFO thấp hơn nhiều = lợi nhuận 'trên giấy' "
            "(accruals cao), thường đảo chiều các năm sau.",
            "Thủ thuật làm đẹp hay gặp: đẩy hàng cuối năm để ghi doanh thu (phải thu phình), giữ "
            "tồn kho không trích giảm giá, vốn hóa chi phí. Beneish M-score gộp 8 dấu hiệu như vậy "
            "— chỉ là cờ tham khảo, không phải bằng chứng."]
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
        sec = Section("4. Dòng tiền: nguồn tiền thật, đầu tư và khả năng tự nuôi")
        cfo, cfi, cff = S["cfo"], S["cfi"], S["cff"]
        capex, dep, div = S["capex"], S["dep"], S["div_paid"]
        debt_in, debt_out, share_issue = S["debt_in"], S["debt_out"], S["share_issue"]
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
        # cổ tức có được tài trợ bằng tiền thật không? — chỉ cờ khi cổ tức TRỌNG YẾU
        # (≥10% lãi ròng); cổ tức tượng trưng (vd HPG 37 tỷ) không đáng gắn cờ.
        if div.get(y1) is not None and fcf1 is not None and fcf1 < 0:
            dv = abs(div[y1]); ni1 = S["ni"].get(y1)
            material = dv >= 1e9 and (ni1 is None or ni1 <= 0 or dv >= 0.10 * abs(ni1))
            if material:
                sec.flags.append(
                    f"🔻 Chi trả cổ tức {_t(dv)} {y1} trong khi FCF ÂM ({_t(fcf1)}) — cổ tức "
                    f"phải tài trợ bằng vay/tiền tích lũy, không bền nếu kéo dài.")
        # CFO âm
        if c1 is not None and c1 < 0:
            ni1 = S["ni"].get(y1)
            extra = f" dù lãi ròng dương ({_t(ni1)})" if (ni1 and ni1 > 0) else ""
            sec.flags.append(
                f"🔻 CFO ÂM {_t(c1)} năm {y1}{extra} — hoạt động kinh doanh không tạo tiền.")

        # --- CẤU TRÚC TÀI TRỢ: tập đoàn sống bằng gì? (vay mới vs vốn góp chủ sở hữu) ---
        di = debt_in.get(y1); do = debt_out.get(y1); sh = share_issue.get(y1)
        cff1 = cff.get(y1)
        if di is not None:
            net_new_debt = di + (do or 0)            # do lưu âm (trả gốc)
            parts = [f"vay mới {_t(di)}"]
            if do:
                parts.append(f"trả gốc {_t(abs(do))}")
            parts.append(f"vay ròng {_t(net_new_debt)}")
            if sh and sh > 0:
                parts.append(f"nhận vốn góp chủ sở hữu {_t(sh)}")
            ext_raised = net_new_debt + (sh if (sh and sh > 0) else 0)
            depends = (cff1 is not None and cff1 > 0 and fcf1 is not None and fcf1 < 0
                       and ext_raised > 0)
            dd.metrics["funding_depends"] = depends
            dd.metrics["ext_raised"] = ext_raised
            line = f"Cách tập đoàn tài trợ {y1}: {', '.join(parts)}."
            if depends:
                line += (" Dòng tiền kinh doanh CHƯA đủ tự nuôi đầu tư nên phải huy động vốn bên "
                         "ngoài để bù — nguồn sống phụ thuộc thị trường vốn và các bên rót vốn.")
                dd.watch_items.append(
                    f"Khả năng tiếp tục vay & tái cấp vốn: năm {y1} tập đoàn huy động ròng "
                    f"{_t(ext_raised)} vốn bên ngoài (chủ yếu {_t(net_new_debt)} nợ vay mới) để bù "
                    f"dòng tiền đầu tư. Cần theo dõi lãi suất, lịch đáo hạn nợ, và các khoản BƠM "
                    f"VỐN từ chủ sở hữu/bên liên quan (thường nằm trong thuyết minh giao dịch liên "
                    f"quan, không hiện đủ trên báo cáo hợp nhất).")
            elif (fcf1 is not None and fcf1 < 0 and sh and sh > 0
                  and abs(fcf1) > 0 and sh > 0.5 * abs(fcf1)):
                # FCF âm VÀ vốn góp chủ sở hữu là nguồn bù chính → phụ thuộc thật sự
                dd.watch_items.append(
                    f"Phụ thuộc vốn góp chủ sở hữu: năm {y1} nhận {_t(sh)} vốn góp để bù dòng tiền "
                    f"tự do âm ({_t(fcf1)}) — theo dõi cổ đông/bên liên quan có tiếp tục rót vốn không.")
            sec.lines.append(line)

        sec.explain = [
            "Ba 'ống' tiền: CFO (từ kinh doanh, nên dương và lớn), CFI (đầu tư, thường âm vì mua "
            "sắm tài sản), CFF (vay/trả nợ, cổ tức). Khỏe = CFO đủ nuôi đầu tư và trả bớt nợ, "
            "không phải liên tục đi vay để sống.",
            "FCF (dòng tiền tự do) = CFO trừ đầu tư tài sản — tiền thật còn dư để trả cổ tức/giảm "
            "nợ. FCF âm do capex lớn (xây thêm nhà máy) là đầu tư tương lai; FCF âm vì CFO âm mới "
            "đáng lo."]
        dd.sections["cashflow"] = sec

    # ------------------------------------------------------------------
    # 4. CÂN ĐỐI KẾ TOÁN — đòn bẩy, thanh khoản, chất lượng tài sản, chu kỳ vốn lưu động
    # ------------------------------------------------------------------
    def _balance_sheet(self, dd: DeepDive, S: dict) -> None:
        sec = Section("5. Cân đối kế toán: đòn bẩy, thanh khoản & chu kỳ vốn lưu động")
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
        dd.metrics.update({"de": de, "net_debt": net_debt})
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
                dd.metrics["coverage"] = cov
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

        sec.explain = [
            "D/E (nợ trên vốn chủ) đo mức vay mượn — càng cao càng rủi ro khi lãi suất tăng hay "
            "kinh doanh xấu. Thanh toán hiện hành (tài sản ngắn hạn/nợ ngắn hạn) nên ≥1. Nợ ròng "
            "âm = tiền nhiều hơn nợ, rất an toàn.",
            "CCC (chu kỳ tiền mặt) = số ngày tiền bị kẹt trong vận hành (mua/làm hàng → bán chịu → "
            "thu tiền, trừ số ngày được nợ nhà cung cấp). Càng ngắn càng tốt; kéo dài qua các năm "
            "= vốn bị chôn vào hàng tồn hoặc khách chậm trả."]
        dd.sections["balance"] = sec

    # ------------------------------------------------------------------
    # 5. ĐIỂM CẢNH BÁO — Altman Z'' (thị trường mới nổi) + Piotroski F
    # ------------------------------------------------------------------
    def _distress(self, dd: DeepDive, S: dict, ratios: pd.DataFrame) -> None:
        sec = Section("6. Cảnh báo kiệt quệ & sức khỏe cơ bản (Altman Z, Piotroski F)")
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

        sec.explain = [
            "Altman Z ước lượng nguy cơ kiệt quệ tài chính (mất khả năng trả nợ) 1–2 năm tới — cao "
            "là an toàn. Piotroski F (0–9) đếm số mặt công ty cải thiện so năm trước (sinh lời, "
            "giảm nợ, hiệu quả).",
            "Cả hai xây từ dữ liệu doanh nghiệp Mỹ → chỉ là cờ tham khảo. Altman Z hay chấm 'an "
            "toàn' nhầm cho bất động sản (tài sản lớn) — phải đọc cùng phần dòng tiền, đừng tin mỗi "
            "điểm số."]
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
        sec = Section("7. Định giá: đắt hay rẻ — so lịch sử, CHU KỲ và so ngành")
        # --- 7a. So với lịch sử & nội tại (m23 percentile + m24 justified P/B) ---
        for nd in (a.get("nhận_định") or []):
            sec.lines.append(str(nd))
        for flag in (a.get("cờ_rủi_ro") or []):
            # cờ định giá đưa vào phần này nhưng KHÔNG nhân đôi vào tổng cờ forensic
            if str(flag) not in sec.lines:
                sec.lines.append(f"⚠️ {flag}")

        # --- 7b + 7c. Chuẩn hóa chu kỳ + so peer chuẩn hóa (chỉ phi ngân hàng) ---
        # Khử ẢO GIÁC lãi đỉnh/đáy: bội số spot rẻ có thể vì lãi đang ở đỉnh (rẻ ảo). Đây là
        # thước đo ĐÁNG TIN HƠN spot cho DN chu kỳ → dùng để chốt stance.
        cyc_stance = None
        if not dd.is_bank:
            try:
                nc = self.valuation.normalized_cycle(symbol)
            except Exception:  # noqa: BLE001
                nc = None
            if nc and nc.get("đủ_dữ_liệu"):
                dd.metrics["cycle"] = {k: nc.get(k) for k in
                                       ("chu_kỳ", "pe_spot", "pe_chuẩn", "roe_chuẩn",
                                        "biên_hiện_tại", "biên_mid", "justified_pb_chuẩn")}
                st = nc["chu_kỳ"]; pes, pen = nc["pe_spot"], nc["pe_chuẩn"]
                sec.lines.append(
                    f"Chu kỳ: biên hiện tại {_pct(nc['biên_hiện_tại'])} vs mid-cycle "
                    f"{_pct(nc['biên_mid'])} → đang ở {st}. P/E spot {pes} → "
                    f"P/E CHUẨN HÓA {pen} (đưa biên về mid-cycle).")
                if pes and pen:
                    if st == "ĐỈNH" and pen > pes * 1.15:
                        sec.lines.append(
                            f"⚠️ P/E spot {pes} RẺ ẢO — lãi đang ở ĐỈNH biên; chuẩn hóa về mid-cycle "
                            f"P/E thực ~{pen} (đắt hơn nhiều so với vẻ ngoài).")
                    elif st == "ĐÁY" and pen < pes * 0.85:
                        sec.lines.append(
                            f"P/E spot {pes} bị lãi ĐÁY chu kỳ thổi cao; chuẩn hóa về mid-cycle "
                            f"P/E ~{pen} — rẻ hơn vẻ ngoài NẾU biên hồi phục.")
                for cf in nc.get("cờ", []):
                    if f"⚠️ {cf}" not in sec.lines:
                        sec.lines.append(f"⚠️ {cf}")
            try:
                pc = self.valuation.cycle_peer_compare(symbol)
            except Exception:  # noqa: BLE001
                pc = None
            if pc and pc.get("nhận_định"):
                sec.lines.append(f"— So ngành {pc.get('ngành','')} "
                                 f"({pc.get('số_peer_dùng',0)} peer, đã chuẩn hóa chu kỳ):")
                for nd in pc["nhận_định"]:
                    sec.lines.append(f"  • {nd}")
                joined = " ".join(pc["nhận_định"])
                if "RẺ CƠ HỘI" in joined:
                    cyc_stance = "rẻ CƠ HỘI — chiết khấu vượt mức chất lượng ngành (đã chuẩn hóa chu kỳ)"
                elif "RẺ ĐÁNG ĐỜI" in joined:
                    cyc_stance = "rẻ nhưng ĐÁNG ĐỜI — do ROE/biên mỏng (đã chuẩn hóa chu kỳ)"
                elif "RẺ hơn ngành" in joined and "ĐẮT hơn ngành" not in joined:
                    cyc_stance = "rẻ hơn ngành (đã chuẩn hóa chu kỳ)"
                elif "ĐẮT hơn ngành" in joined and "RẺ hơn ngành" not in joined:
                    cyc_stance = "đắt hơn ngành (đã chuẩn hóa chu kỳ)"

        if not sec.lines:
            sec.lines.append("Không đủ dữ liệu định giá.")

        # --- stance để dựng luận điểm: ƯU TIÊN đọc CHU KỲ+PEER (đáng tin hơn spot) ---
        if cyc_stance:
            dd.metrics["val_stance"] = ("rẻ" if cyc_stance.startswith("rẻ") else
                                        "đắt" if cyc_stance.startswith("đắt") else "trái chiều")
            dd.metrics["val_basis"] = "chu kỳ & so ngành"
            dd.metrics["val_stance_detail"] = cyc_stance
        else:
            txt = " ".join(sec.lines)
            n_dat = txt.count("ĐẮT"); n_re = txt.count("RẺ")
            if n_dat and not n_re:
                dd.metrics["val_stance"] = "đắt"
            elif n_re and not n_dat:
                dd.metrics["val_stance"] = "rẻ"
            elif n_dat or n_re:
                dd.metrics["val_stance"] = "trái chiều"
            dd.metrics["val_basis"] = "lịch sử"

        sec.explain = [
            "Bội số 'rẻ' so với CHÍNH lịch sử mã dễ đánh lừa với DN CHU KỲ (xây dựng, thép, đầu tư "
            "công): lúc lãi đỉnh P/E thấp giả, lúc lãi đáy P/E cao giả. Chuẩn hóa chu kỳ đưa biên "
            "lợi nhuận về trung vị nhiều năm (mid-cycle) rồi đọc lại bội số — mới biết rẻ THẬT.",
            "Rẻ CƠ HỘI = định giá thấp hơn mức chất lượng (ROE) của nó đáng được → có thể bị bỏ "
            "quên. Rẻ ĐÁNG ĐỜI = thấp vì ROE/biên mỏng, thị trường định giá đúng. Cầu P/B–ROE "
            "(justified P/B từ ROE chuẩn hóa) tách hai cái đó.",
        ]
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

    # ------------------------------------------------------------------
    # 8. TỔNG HỢP & ĐIỀU CẦN THEO DÕI (true conclusion — chốt đánh đổi)
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_icon(s: str) -> str:
        for ic in ("🔻", "✅", "⚠️", "🚨"):
            s = s.replace(ic, "")
        return s.strip().rstrip(".").strip()   # bỏ dấu chấm cuối để không thành ".;" khi nối

    def _conclusion(self, dd: DeepDive) -> None:
        if dd.is_bank:
            return
        sec = Section("10. Tổng hợp & điều cần theo dõi")
        # định giá đắt/rẻ — ưu tiên stance đã chốt (chu kỳ+peer nếu có), nêu rõ CƠ SỞ
        val_stance = ""
        detail = dd.metrics.get("val_stance_detail")
        vs0 = dd.metrics.get("val_stance")
        basis0 = dd.metrics.get("val_basis", "lịch sử")
        if detail:
            val_stance = "định giá " + detail
        elif vs0 == "đắt":
            val_stance = f"định giá đang ĐẮT so với {basis0}"
        elif vs0 == "rẻ":
            val_stance = f"định giá đang RẺ so với {basis0}"
        elif vs0 == "trái chiều":
            val_stance = "định giá trái chiều giữa các thước đo"

        # bức tranh tổng thể: gộp điểm tựa + rủi ro + định giá
        n = len(dd.red_flags)
        picture = []
        if dd.positives:
            picture.append("Điểm tựa: " + "; ".join(self._strip_icon(p) for p in dd.positives[:2]) + ".")
        if n == 0:
            picture.append("Không có cờ đỏ forensic nào nổi lên từ dữ liệu.")
        else:
            picture.append(f"Rủi ro nổi bật ({n} cờ): " +
                           "; ".join(self._strip_icon(f) for f in dd.red_flags[:2]) +
                           ("; …" if n > 2 else "") + ".")
        if val_stance:
            picture.append("Về giá: " + val_stance + ".")
        sec.lines.append(" ".join(picture))

        # điều cần theo dõi: ưu tiên watch_items CỤ THỂ (data-driven) do các mục sinh ra,
        # rồi bổ sung watch chung rút từ cờ nếu còn thiếu.
        watch = list(dd.watch_items)                # cụ thể, có số (vd cấu trúc tài trợ)
        jlow = " ".join(dd.red_flags).lower()       # so khớp không phân biệt hoa/thường
        generic = []
        if "cfo âm" in jlow or "không ra tiền" in jlow or "accruals" in jlow:
            generic.append("dòng tiền kinh doanh (CFO) các quý tới có dương và bám sát lợi nhuận không")
        if "cốt lõi" in jlow:
            generic.append("khoản thu nhập ngoài cốt lõi có lặp lại được không hay chỉ một lần")
        if "tồn kho" in jlow or "chu kỳ tiền mặt" in jlow:
            generic.append("tồn kho và tốc độ bán hàng — vốn có bị chôn thêm không")
        if "thiểu số" in jlow or "công ty con chưa sở hữu 100% đang lỗ" in jlow:
            generic.append("mảng công ty con nào đang lỗ và có thu hẹp lỗ không")
        # chỉ thêm generic nếu chưa được watch cụ thể phủ, và tổng ≤3
        for g in generic:
            if len(watch) >= 3:
                break
            watch.append(g)
        if not watch:
            watch.append("dòng tiền và biên lợi nhuận có giữ được ổn định qua các kỳ không")
        if len(watch) == 1:
            sec.lines.append("**Điều cần theo dõi:** " + watch[0] +
                             ("" if watch[0].endswith(".") else "."))
        else:
            sec.lines.append("**Điều cần theo dõi:**")
            for w in watch[:3]:
                sec.lines.append("- " + w + ("" if w.endswith(".") else "."))

        sec.lines.append(
            "**Điều có thể làm đổi đánh giá:** đọc thuyết minh báo cáo tài chính (nội dung khoản "
            "phi cốt lõi, giao dịch bên liên quan, lịch đáo hạn nợ) và bản kiểm toán — những thứ "
            "nằm ngoài dữ liệu tự động ở đây.")
        sec.lines.append(
            "*Đây là phân tích dữ kiện từ báo cáo đã công bố, KHÔNG phải khuyến nghị mua/bán.*")
        dd.sections["conclusion"] = sec

    # ------------------------------------------------------------------
    # LUẬN ĐIỂM ĐẦU TƯ — đoạn văn mạch lạc + bản hai mặt (đặt LÊN ĐẦU báo cáo)
    # ------------------------------------------------------------------
    def _investment_view(self, dd: DeepDive) -> None:
        if dd.is_bank:
            dd.thesis = ("Đây là ngân hàng — sức khỏe đánh giá bằng khung CAMELS (NIM/NPL/CAR/"
                         "LDR/CASA), không áp forensic doanh nghiệp thường. Xem tầng định giá riêng.")
            return
        m = dd.metrics
        p: List[str] = []
        # 1. định danh + bản chất
        ident = dd.name or dd.symbol
        if dd.sector:
            ident += f" — doanh nghiệp ngành {dd.sector.lower()}"
        p.append(ident + ".")
        # 2. quy mô & tăng trưởng
        if m.get("rev") is not None:
            s = f"Doanh thu {m.get('năm')} {_t(m['rev'])}"
            if m.get("rev_g") is not None:
                s += f", tăng trưởng {_pct(m['rev_g'])}"
            if m.get("gm") is not None:
                s += f"; biên lợi nhuận gộp {m['gm']*100:.0f}%"
            p.append(s + ".")
        # 3. chất lượng lợi nhuận (lãi có ra tiền không) — cốt lõi
        c = m.get("cfo_ni_3y")
        if c is not None:
            if c >= 0.9:
                p.append(f"Lợi nhuận ra tiền thật — dòng tiền kinh doanh 3 năm bằng {c*100:.0f}% "
                         f"lãi ròng.")
            elif c < 0.5:
                p.append(f"Chất lượng lợi nhuận đáng ngại — dòng tiền kinh doanh 3 năm chỉ bằng "
                         f"{c*100:.0f}% lãi ròng, phần lớn lợi nhuận nằm 'trên giấy'.")
            else:
                p.append(f"Dòng tiền kinh doanh 3 năm bằng {c*100:.0f}% lãi ròng.")
        ns = m.get("noncore_share")
        if ns is not None and ns > 0.40:
            p.append(f"Đáng chú ý: khoảng {ns*100:.0f}% lãi trước thuế đến từ ngoài hoạt động cốt "
                     f"lõi (tài chính/đánh giá lại/khác) — cần dè chừng tính bền vững.")
        # 4. tài chính & khả năng tự nuôi
        fin = []
        if m.get("de") is not None:
            fin.append(f"đòn bẩy D/E {m['de']:.1f} lần")
        if m.get("coverage") is not None and m["coverage"] < 2:
            fin.append(f"độ phủ lãi vay mỏng ({m['coverage']:.1f} lần)")
        if m.get("funding_depends"):
            fin.append(f"phụ thuộc vốn huy động bên ngoài (~{_t(m.get('ext_raised'))}/năm)")
        elif m.get("net_debt") is not None and m["net_debt"] < 0:
            fin.append("tiền ròng dương, không áp lực nợ")
        if fin:
            p.append("Về tài chính: " + ", ".join(fin) + ".")
        # 5. cấu trúc tập đoàn (nếu đáng nói)
        gk = m.get("group_kind")
        if gk == "loss_subs":
            p.append("Là tập đoàn có mảng công ty con đang lỗ lớn — lãi công ty mẹ cao hơn lãi hợp "
                     "nhất, cần tách xem mảng nào đốt tiền.")
        elif gk == "conglomerate":
            p.append("Là tập đoàn mà một phần đáng kể lợi nhuận thuộc về cổ đông thiểu số.")
        # 6. định giá
        vs = m.get("val_stance")
        if vs:
            basis = m.get("val_basis", "lịch sử")
            detail = m.get("val_stance_detail")
            p.append(f"Định giá hiện {detail}." if detail else f"Định giá hiện {vs} so với {basis}.")
        # 7. through-line — bức tranh ròng
        n = len(dd.red_flags)
        if n == 0:
            net = "Ròng lại: nền tảng lành mạnh, chưa lộ cờ đỏ forensic nào"
        elif n <= 2:
            net = f"Ròng lại: về cơ bản ổn nhưng có {n} điểm cần lưu ý"
        else:
            net = (f"Ròng lại: bức tranh có {n} cờ đỏ đáng kể — chất lượng lợi nhuận/dòng tiền/cân "
                   f"đối cần soi kỹ trước khi tin con số lợi nhuận")
        if vs == "đắt":
            net += ", trong khi thị trường đang trả giá cao"
        elif vs == "rẻ" and n == 0:
            net += f" và giá đang thấp so với {m.get('val_basis', 'lịch sử')}"
        p.append(net + ".")
        dd.thesis = " ".join(p)

        # bản hai mặt — điểm hấp dẫn (bull) vs điều e ngại (bear)
        _basis = m.get("val_basis", "lịch sử")
        bull = [self._strip_icon(x) for x in dd.positives]
        if vs == "rẻ":
            bull.append(f"Định giá thấp so với {_basis} (dư địa nếu chất lượng giữ được)")
        if m.get("rev_g") is not None and m["rev_g"] >= 0.15 and (c is None or c >= 0.5):
            bull.append(f"Doanh thu tăng trưởng mạnh ({_pct(m['rev_g'])})")
        bear = [self._strip_icon(x) for x in dd.red_flags]
        if vs == "đắt":
            bear.append(f"Định giá cao so với {_basis} — kỳ vọng đã phản ánh vào giá")
        # tín hiệu QUÝ gần nhất (số năm chưa phản ánh)
        rt = m.get("recent_turn")
        if rt == "up":
            bull.append("Turnaround đang diễn ra ở các quý gần nhất (2 quý liền có lãi sau lỗ) — "
                        "số liệu năm chưa phản ánh")
        elif rt == "up_unconfirmed":
            bull.append("Các quý gần nhất đã có lãi trở lại (sau chuỗi lỗ) — NHƯNG cần cross-check "
                        "ngoài xem là turnaround tiền thật hay lãi trên giấy (dòng tiền chưa xác nhận)")
        elif rt == "down":
            bear.append("Các quý gần nhất đang suy giảm mạnh — cảnh báo sớm số năm chưa phản ánh")
        dd.bull = bull
        dd.bear = bear

        self._takeaways(dd, m, c, ns, vs)
        self._lenses(dd, m, c, ns, vs)
        self._scenarios(dd, m, c, ns, vs)

    def _takeaways(self, dd, m, c, ns, vs) -> None:
        """Điều rút ra cho DN — hàm ý 'so-what', không lặp lại số thô."""
        t: List[str] = []
        if m.get("funding_depends"):
            t.append("Doanh nghiệp buộc phải duy trì khả năng huy động vốn liên tục để vận hành — "
                     "mọi cú siết tín dụng hay tăng lãi suất đều đe dọa trực tiếp mô hình; ưu tiên "
                     "hàng đầu là giữ dòng vốn và kéo dài kỳ hạn nợ.")
        if m.get("group_kind") == "loss_subs":
            t.append("Vận mệnh nhóm phụ thuộc vào việc mảng công ty con đang lỗ có thu hẹp lỗ được "
                     "không; mảng cốt lõi đang phải gánh cho phần còn lại.")
        if ns is not None and ns > 0.40:
            t.append("Lợi nhuận công bố phụ thuộc lớn vào khoản ngoài cốt lõi (tài chính/đánh giá "
                     "lại) → chất lượng lãi mong manh, khó xem là bền và khó ngoại suy.")
        if c is not None and c < 0.5:
            t.append("Lãi ghi sổ chưa chuyển thành tiền — bài toán cốt lõi là cải thiện thu tiền "
                     "về (vốn lưu động, tiến độ bán hàng/thu nợ), không phải tăng lãi trên giấy.")
        de = m.get("de"); cov = m.get("coverage")
        if de is not None and de > 3 and cov is not None and cov < 2:
            t.append("Đòn bẩy cao đi kèm biên trả lãi mỏng khiến DN nhạy cảm với lãi suất — giảm "
                     "nợ/tăng vốn chủ là hướng lành mạnh hóa bảng cân đối.")
        if not dd.red_flags and vs == "rẻ":
            t.append("Nền tảng lành mạnh mà định giá thấp → thị trường có thể đang định giá thấp; "
                     "việc cần làm là kiểm chứng chất lượng có duy trì được qua các kỳ tới.")
        if not t:
            t.append("Bức tranh tài chính cân bằng — chưa có hàm ý cấp bách nào nổi lên; theo dõi "
                     "để chất lượng hiện tại được duy trì.")
        dd.takeaways = t

    def _lenses(self, dd, m, c, ns, vs) -> None:
        """Góc nhìn theo loại nhà đầu tư — mỗi loại một dòng, suy từ metrics."""
        L: List[str] = []
        rg = m.get("rev_g")
        # tăng trưởng
        if rg is not None:
            caveat = ", nhưng cần lãi cốt lõi đi kèm" if (ns and ns > 0.4) else ""
            if rg >= 0.20:
                L.append(f"**Nhà đầu tư tăng trưởng:** rất hấp dẫn — doanh thu tăng {rg*100:.0f}%"
                         + caveat + ".")
            elif rg >= 0.10:
                L.append(f"**Nhà đầu tư tăng trưởng:** hấp dẫn — tăng trưởng ổn định {rg*100:.0f}%"
                         + caveat + ".")
            elif rg >= 0:
                L.append(f"**Nhà đầu tư tăng trưởng:** trung bình — tăng trưởng chậm ({rg*100:.0f}%).")
            else:
                L.append(f"**Nhà đầu tư tăng trưởng:** không phù hợp — doanh thu giảm ({rg*100:.0f}%).")
        # giá trị
        if vs == "rẻ":
            L.append(f"**Nhà đầu tư giá trị:** đáng chú ý — định giá thấp so với "
                     f"{m.get('val_basis', 'lịch sử')} (miễn tránh được bẫy giá trị).")
        elif vs == "đắt":
            L.append("**Nhà đầu tư giá trị:** không hấp dẫn — định giá cao.")
        elif vs:
            L.append("**Nhà đầu tư giá trị:** trung tính — định giá quanh mức lịch sử.")
        # cổ tức
        dy = dd.info.get("div_yield")
        if dy is not None:
            if dy >= 0.04 and not m.get("funding_depends"):
                L.append(f"**Nhà đầu tư cổ tức:** phù hợp — suất cổ tức ~{dy*100:.1f}% và không "
                         f"phải vay để trả.")
            elif dy > 0:
                L.append(f"**Nhà đầu tư cổ tức:** suất ~{dy*100:.1f}% nhưng cần soi cổ tức có được "
                         f"tài trợ bằng tiền thật không.")
            else:
                L.append("**Nhà đầu tư cổ tức:** không phù hợp — hầu như không chia cổ tức.")
        # thận trọng
        n = len(dd.red_flags); de = m.get("de")
        if n == 0 and (de is None or de < 1.5):
            L.append("**Nhà đầu tư thận trọng:** chấp nhận được — ít cờ đỏ, đòn bẩy thấp.")
        elif n >= 3 or (de is not None and de > 3):
            L.append("**Nhà đầu tư thận trọng:** nên tránh — nhiều cờ đỏ hoặc đòn bẩy cao.")
        else:
            L.append("**Nhà đầu tư thận trọng:** cân nhắc kỹ — có một vài rủi ro cần theo dõi.")
        dd.lenses = L

    def _scenarios(self, dd, m, c, ns, vs) -> None:
        """Kịch bản bull/base/bear = ĐIỀU KIỆN (không phải dự phóng số)."""
        S: List[str] = []
        bull_if = []
        if m.get("group_kind") == "loss_subs":
            bull_if.append("mảng công ty con đang lỗ thu hẹp lỗ / có lãi")
        if ns is not None and ns > 0.4:
            bull_if.append("lợi nhuận cốt lõi tự đứng vững, bớt lệ thuộc khoản một lần")
        if m.get("funding_depends"):
            bull_if.append("tiếp tục huy động vốn với chi phí hợp lý và giãn được kỳ hạn nợ")
        if c is not None and c < 0.5:
            bull_if.append("dòng tiền kinh doanh cải thiện, bám sát lợi nhuận")
        if not bull_if and vs == "rẻ":
            bull_if.append("chất lượng lợi nhuận duy trì để thị trường định giá lại")
        if not bull_if:
            bull_if.append("giữ được đà tăng trưởng và biên lợi nhuận hiện tại")
        S.append("🟢 **Lạc quan (bull):** nếu " + "; ".join(bull_if) + ".")
        S.append("⚪ **Cơ sở (base):** xu hướng hiện tại tiếp diễn — "
                 + ("tăng trưởng nhưng rủi ro chưa được giải quyết"
                    if dd.red_flags else "nền tảng ổn định, chưa có biến lớn") + ".")
        bear_if = []
        if m.get("funding_depends"):
            bear_if.append("tín dụng siết / lãi suất tăng khiến khó tái cấp vốn")
        if m.get("group_kind") == "loss_subs":
            bear_if.append("mảng lỗ tiếp tục đốt tiền, bào mòn vốn")
        if m.get("coverage") is not None and m["coverage"] < 2:
            bear_if.append("lợi nhuận không đủ trả lãi kéo dài")
        if ns is not None and ns > 0.4:
            bear_if.append("khoản thu nhập ngoài cốt lõi không lặp lại, lãi thật lộ ra thấp")
        if not bear_if:
            bear_if.append("nhu cầu suy yếu làm giảm doanh thu và biên lợi nhuận")
        S.append("🔴 **Bi quan (bear):** nếu " + "; ".join(bear_if) + ".")
        dd.scenarios = S


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
