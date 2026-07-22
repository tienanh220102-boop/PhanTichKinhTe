# -*- coding: utf-8 -*-
"""
Tầng LÝ LUẬN định giá — biến tỷ số thô (vn_fundamentals) thành nhận định có cơ sở CFA L2.

Nền lý thuyết (wiki D:\\AI Tiến Anh\\Sách\\wiki\\L2):
  - m23 Market-Based Valuation: đắt/rẻ theo PERCENTILE lịch sử của P/E, P/B, EV/EBITDA
    (adaptive, không dùng ngưỡng cứng); bank dùng P/B, phi-bank dùng EV/EBITDA + P/E.
  - m24 Residual Income: justified P/B = (ROE − g)/(r − g); P/B > 1 hợp lý CHỈ khi ROE > r.
  - m13 Financial Institutions: bank soi bằng NPL/CAR/LDR/NIM/CIR, KHÔNG dùng P/E chung.
  - m14 Quality: cờ VALUE-TRAP = rẻ nhưng biên lợi nhuận/ROE xấu hoặc đi xuống.

Triết lý (khớp memory user): mọi nhận định KÈM BẰNG CHỨNG số + GIẢ ĐỊNH ghi rõ; guardrail
mọi field (dấu, khoảng hợp lệ, thiếu → bỏ qua chứ không bịa); rẻ ≠ tốt (chống value trap).

CẢNH BÁO: r (cost of equity) và g là GIẢ ĐỊNH mặc định cho thị trường VN, KHÔNG phải
sự thật — chỉnh qua tham số. Đây là công cụ hỗ trợ đọc, không phải khuyến nghị mua/bán.
"""
from __future__ import annotations

import sys
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from vn_fundamentals import VCIFundamentals, ensure_utf8_stdout
from vn_sectors import VCISectors

logger = logging.getLogger(__name__)

# --- Giả định thị trường VN (ghi rõ, chỉnh được) ---
DEFAULT_COST_OF_EQUITY = 0.13   # r ≈ rf(TPCP VN) + ERP + country premium (m18); ~13% cho equity VN
DEFAULT_LONG_RUN_GROWTH = 0.05  # g dài hạn ~ tăng trưởng GDP danh nghĩa thận trọng (m09)

# r/g THEO NGÀNH (ICB L1) — GIẢ ĐỊNH, không phải sự thật. Spread khiêm tốn (tránh false
# precision): r cao hơn cho ngành CHU KỲ/beta cao (thép, dầu, BĐS/tài chính), thấp hơn cho
# phòng thủ (tiện ích, tiêu dùng, y tế); g cao hơn cho ngành tăng trưởng cấu trúc (CNTT, y tế).
# Cơ sở: chênh lệch beta/độ ổn định dòng tiền giữa các ngành. Chỉnh được; thiếu ngành → default.
SECTOR_RG = {
    "Ngân hàng":            (0.130, 0.040),
    "Tài chính":            (0.145, 0.050),   # chứng khoán/bảo hiểm — beta cao
    "Tiện ích Cộng đồng":   (0.115, 0.040),   # điện/nước — dòng tiền ổn định, phòng thủ
    "Hàng Tiêu dùng":       (0.120, 0.050),
    "Dược phẩm và Y tế":    (0.120, 0.060),   # phòng thủ + tăng trưởng cấu trúc
    "Dịch vụ Tiêu dùng":    (0.130, 0.055),
    "Công nghệ Thông tin":  (0.135, 0.070),   # tăng trưởng cao
    "Viễn thông":           (0.125, 0.050),
    "Công nghiệp":          (0.140, 0.050),   # gồm xây dựng — chu kỳ
    "Nguyên vật liệu":      (0.150, 0.050),   # thép/hóa chất — chu kỳ mạnh
    "Dầu khí":              (0.150, 0.045),   # hàng hóa biến động
}

# --- Guardrail: khoảng hợp lệ để loại số rác (watchdog) ---
_SANE = {
    "pe": (0.0, 300.0), "pb": (0.0, 50.0), "ps": (0.0, 100.0),
    "evToEbitda": (0.0, 200.0), "roe": (-2.0, 2.0), "roa": (-1.0, 1.0),
}


def _clean(row: Dict[str, object], field: str) -> Optional[float]:
    """Lấy field dạng float đã guardrail: None nếu thiếu/0-vô-nghĩa/ngoài khoảng hợp lệ."""
    v = row.get(field)
    if v is None or (isinstance(v, float) and (np.isnan(v))):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if field in _SANE:
        lo, hi = _SANE[field]
        if not (lo <= v <= hi):
            return None
    return v


def _mcap(row: Dict[str, object]) -> Optional[float]:
    """Vốn hóa (VND) đã guardrail: None nếu thiếu/không dương."""
    v = row.get("marketCap")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _pct_rank(series: pd.Series, value: float) -> Optional[float]:
    """Percentile (0-100) của `value` trong chuỗi lịch sử. Cao = đắt so với quá khứ."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s[(s > 0)]  # bỏ 0/âm vô nghĩa cho bội số
    if len(s) < 4:
        return None
    return round(float((s < value).mean()) * 100, 1)


def _annual_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Chỉ giữ dòng SỐ CẢ NĂM (RATIO_YEAR), loại các dòng TTM theo quý.

    VCI trả mỗi năm 5 dòng: quarter 1-4 = TTM theo quý (ratioType RATIO_TTM) dùng giá
    tại các thời điểm khác nhau; quarter 5 = số cả năm (RATIO_YEAR). Percentile lịch sử
    và biên mid-cycle PHẢI dùng số NĂM — trộn TTM-quý vào làm méo phân phối (giá khác kỳ).

    LƯU Ý: quarter KHÔNG bao giờ = 0 ở nguồn này (nên filter cũ `quarter==0` luôn rỗng).
    """
    if "ratioType" in df.columns:
        a = df[df["ratioType"] == "RATIO_YEAR"]
        if not a.empty:
            return a.reset_index(drop=True)
    if "quarter" in df.columns:
        a = df[pd.to_numeric(df["quarter"], errors="coerce") == 5]
        if not a.empty:
            return a.reset_index(drop=True)
    return df


def _fmt_pct(v: Optional[float]) -> str:
    """Định dạng % gọn, chịu None."""
    return f"{v:.1%}" if isinstance(v, (int, float)) else "n/a"


def _verdict_from_pct(pct: Optional[float]) -> str:
    if pct is None:
        return "không đủ lịch sử"
    if pct <= 20:
        return "RẺ so với lịch sử"
    if pct <= 40:
        return "dưới trung bình"
    if pct <= 60:
        return "quanh trung bình"
    if pct <= 80:
        return "trên trung bình"
    return "ĐẮT so với lịch sử"


class VNValuation:
    def __init__(self, fx: Optional[VCIFundamentals] = None,
                 sx: Optional[VCISectors] = None,
                 cost_of_equity: float = DEFAULT_COST_OF_EQUITY,
                 long_run_growth: float = DEFAULT_LONG_RUN_GROWTH):
        self.fx = fx or VCIFundamentals()
        self.sx = sx or VCISectors()
        self.r = cost_of_equity
        self.g = long_run_growth
        self._explicit_rg = (cost_of_equity != DEFAULT_COST_OF_EQUITY
                             or long_run_growth != DEFAULT_LONG_RUN_GROWTH)

    def _rg_for(self, symbol: str) -> tuple:
        """(r, g) THEO NGÀNH ICB L1 của mã. Nếu user truyền r/g tường minh khi khởi tạo → tôn
        trọng (dùng chung cho mọi mã). Thiếu ngành/không map → default self.r/self.g."""
        if self._explicit_rg:
            return self.r, self.g
        try:
            sec = self.sx.sector_of(symbol)
            if sec.get("is_bank"):
                return SECTOR_RG.get("Ngân hàng", (self.r, self.g))
            return SECTOR_RG.get(sec.get("icb_l1"), (self.r, self.g))
        except Exception:  # noqa: BLE001
            return self.r, self.g

    @staticmethod
    def _is_bank(row: Dict[str, object]) -> bool:
        """Bank nếu có tỷ số đặc thù ngân hàng khác 0 (NIM/NPL/CAR/LDR)."""
        for f in ("netInterestMargin", "npl", "car", "ldrLoanDepositRatio"):
            v = row.get(f)
            try:
                if v is not None and abs(float(v)) > 1e-9:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    def assess(self, symbol: str) -> Dict[str, object]:
        symbol = symbol.upper().strip()
        ratios = self.fx.get_ratios(symbol)
        if ratios.empty:
            return {"symbol": symbol, "error": "không có dữ liệu ratio"}

        # Chuỗi SỐ CẢ NĂM (RATIO_YEAR) cho percentile lịch sử; latest = dòng mới nhất
        # (TTM hiện tại) cho định giá hiện thời. (Sửa: filter cũ `quarter==0` luôn rỗng.)
        annual = _annual_rows(ratios)
        latest = ratios.iloc[-1].to_dict()
        r, g = self._rg_for(symbol)  # r/g theo ngành (m18/m24), fallback default

        out: Dict[str, object] = {
            "symbol": symbol,
            "kỳ": f"{latest.get('yearReport')}",
            "loại": "Ngân hàng" if self._is_bank(latest) else "Phi ngân hàng",
            "giả_định": {"r (cost of equity)": r, "g (dài hạn)": g, "theo_ngành": not self._explicit_rg},
            "bằng_chứng": {},
            "nhận_định": [],
            "cờ_rủi_ro": [],
        }
        ev = out["bằng_chứng"]
        notes: List[str] = out["nhận_định"]
        flags: List[str] = out["cờ_rủi_ro"]

        is_bank = self._is_bank(latest)
        roe = _clean(latest, "roe")
        pb = _clean(latest, "pb")
        pe = _clean(latest, "pe")

        # ---- 1. Đắt/rẻ theo percentile lịch sử (m23) ----
        if is_bank:
            # bank: P/B là bội số chính (m13/m24)
            metrics = [("pb", "P/B")]
        else:
            metrics = [("evToEbitda", "EV/EBITDA"), ("pe", "P/E"), ("pb", "P/B")]
        for field, label in metrics:
            cur = _clean(latest, field)
            if cur is None:
                continue
            pct = _pct_rank(annual.get(field, pd.Series(dtype=float)), cur)
            ev[label] = {"hiện tại": round(cur, 2), "percentile_lịch_sử": pct}
            notes.append(f"{label} = {cur:.2f} → {_verdict_from_pct(pct)}"
                         + (f" (pct {pct})" if pct is not None else ""))

        # ---- 2. Justified P/B vs thực tế (m24) — dùng cho MỌI mã có ROE & P/B ----
        if roe is not None and pb is not None and (r - g) > 0:
            justified_pb = (roe - g) / (r - g)
            ev["justified_P/B (m24)"] = {
                "công thức": "(ROE − g)/(r − g)",
                "ROE": round(roe, 4), "r": r, "g": g,
                "justified": round(justified_pb, 2), "thực_tế": round(pb, 2),
            }
            if justified_pb > 0:
                gap = pb / justified_pb - 1
                dv = ("cao hơn hợp lý → thị trường kỳ vọng ROE/g cao hơn giả định (hoặc đắt)"
                      if gap > 0.15 else
                      "thấp hơn hợp lý → có thể rẻ (nếu ROE bền)" if gap < -0.15 else
                      "quanh mức hợp lý")
                notes.append(f"Justified P/B ≈ {justified_pb:.2f} vs thực tế {pb:.2f} "
                             f"({gap:+.0%}) → {dv}")
            # Nguyên tắc cốt tử m24: P/B>1 hợp lý chỉ khi ROE > r
            if pb > 1 and roe < r:
                flags.append(f"P/B>1 ({pb:.2f}) nhưng ROE ({roe:.1%}) < r ({r:.0%}) "
                             f"→ định giá khó biện minh (m24)")

        # ---- 3. Cờ chất lượng / value-trap (m14) ----
        margin = _clean(latest, "afterTaxProfitMargin")
        margins_series = pd.to_numeric(annual.get("afterTaxProfitMargin", pd.Series(dtype=float)),
                                       errors="coerce").dropna()
        margin_down = len(margins_series) >= 3 and margins_series.iloc[-1] < margins_series.iloc[-3]
        pe_pct = ev.get("P/E", {}).get("percentile_lịch_sử") if "P/E" in ev else None
        cheap = (pe_pct is not None and pe_pct <= 30)
        if cheap and (margin_down or (roe is not None and roe < 0.10)):
            flags.append("VALUE-TRAP nghi vấn: rẻ (P/E percentile thấp) NHƯNG "
                         + ("biên lợi nhuận đi xuống" if margin_down else f"ROE thấp ({roe:.1%})")
                         + " (m14) — rẻ có thể vì triển vọng xấu, không phải cơ hội")
        if pe is not None and pe <= 0:
            flags.append("P/E âm/không dùng được (đang lỗ) → dùng P/B & earnings yield (m23)")

        # ---- 4. CAMELS cho bank (m13) ----
        if is_bank:
            npl = _clean(latest, "npl")
            car = latest.get("car")
            ldr = _clean(latest, "ldrLoanDepositRatio")
            cir_raw = latest.get("cir")
            cir = abs(float(cir_raw)) if cir_raw not in (None, "") else None  # guardrail dấu
            nim = _clean(latest, "netInterestMargin")
            cov = _clean(latest, "loansLossReserveToLoans")
            ev["CAMELS (m13)"] = {"NIM": nim, "NPL": npl, "LDR": ldr,
                                  "CIR(|.|)": round(cir, 4) if cir else None,
                                  "bao_phủ_nợ_xấu": cov, "ROA": _clean(latest, "roa")}
            if npl is not None and npl > 0.03:
                flags.append(f"NPL cao ({npl:.2%} > 3%) — chất lượng tài sản đáng lo (m13)")
            if ldr is not None and ldr > 1.05:
                flags.append(f"LDR cao ({ldr:.0%} > 105%) — áp lực thanh khoản (m13)")
            notes.append("Bank: đọc bằng CAMELS + P/B-ROE, KHÔNG dùng P/E/EV-EBITDA chung (m13)")

        # ---- 5. Kết luận có điều kiện (không phải khuyến nghị) ----
        out["tóm_tắt"] = self._summarize(out, is_bank, roe, pb)
        return out

    def peer_compare(self, symbol: str, level: str = "icb_l2",
                     max_peers: int = 30, min_valid: int = 5,
                     same_exchange: bool = True,
                     min_mcap_ty: float = 500.0,
                     rel_mcap_floor: float = 0.0) -> Dict[str, object]:
        """So sánh bội số với PEER cùng ngành ICB (m23 method-of-comparables).

        Lấy median bội số của peer (đã guardrail), định vị mã mục tiêu: rẻ/đắt hơn ngành.
        Bank → dùng P/B; phi-bank → EV/EBITDA + P/E + P/B. (Gọi nhiều API — dùng on-demand.)

        LỌC RÁC (refinement m23) — peer ICB thô hay lẫn mã nhỏ/UPCoM làm median vô nghĩa:
          - `same_exchange=True`: chỉ so với peer CÙNG SÀN (mã HOSE so HOSE, không lẫn UPCoM rác).
          - Ngưỡng vốn hóa TUYỆT ĐỐI `min_mcap_ty` (500 tỷ): bỏ mã micro-cap/rác làm lệch median.
            `rel_mcap_floor` (mặc định 0 = tắt): ngưỡng TƯƠNG ĐỐI theo mã đích — CẨN THẬN, bật lên
            sẽ loại sạch peer của mega-cap (vd HPG so nhóm thép nhỏ hơn) → 0 peer; chỉ dùng khi hiểu rõ.
          - Cảnh báo phân phối: median P/B < 1 với phi-bank ⇒ nghi lẫn mã nhỏ ⇒ BỎ QUA verdict P/B.
        """
        symbol = symbol.upper().strip()
        sec = self.sx.sector_of(symbol)
        peers = self.sx.peers(symbol, level=level, same_exchange=same_exchange)[:max_peers]
        me = self.fx.snapshot(symbol)
        is_bank = bool(sec.get("is_bank"))
        fields = ["pb"] if is_bank else ["evToEbitda", "pe", "pb"]

        # Ngưỡng vốn hóa: sàn tuyệt đối + tương đối theo mã đích
        my_mcap = _mcap(me)
        floor = min_mcap_ty * 1e9
        if my_mcap:
            floor = max(floor, my_mcap * rel_mcap_floor)

        peer_vals: Dict[str, List[float]] = {f: [] for f in fields}
        used = 0
        dropped_small = 0
        for p in peers:
            try:
                snp = self.fx.snapshot(p)
            except Exception:  # noqa: BLE001
                continue
            pm = _mcap(snp)
            if pm is not None and pm < floor:
                dropped_small += 1
                continue  # loại mã quá nhỏ (rác làm lệch median)
            got = False
            for f in fields:
                val = _clean(snp, f)
                if val is not None:
                    peer_vals[f].append(val)
                    got = True
            used += 1 if got else 0

        out: Dict[str, object] = {
            "symbol": symbol,
            "ngành": f"{sec.get('icb_l2')} ({level})",
            "cùng_sàn": same_exchange,
            "ngưỡng_vốn_hóa_tỷ": round(floor / 1e9, 0),
            "số_peer_dùng": used,
            "loại_bỏ_nhỏ": dropped_small,
            "so_sánh": {},
            "nhận_định_peer": [],
        }
        if used < min_valid:
            out["nhận_định_peer"].append(
                f"Chỉ {used} peer đạt chuẩn (< {min_valid}, đã loại {dropped_small} mã nhỏ) "
                "→ so sánh peer KHÔNG đáng tin, bỏ qua")
            return out

        for f, label in (("evToEbitda", "EV/EBITDA"), ("pe", "P/E"), ("pb", "P/B")):
            if f not in fields:
                continue
            vals = peer_vals[f]
            mine = _clean(me, f)
            if not vals or mine is None:
                continue
            med = float(np.median(vals))
            # Guardrail phân phối: P/B median < 1 với phi-bank ⇒ nghi peer lẫn mã nhỏ/UPCoM
            unreliable = (f == "pb" and not is_bank and med < 1.0)
            disc = mine / med - 1 if med > 0 else None
            entry: Dict[str, object] = {
                "mã": round(mine, 2), "median_ngành": round(med, 2),
                "n_peer": len(vals),
                "chênh_%": round(disc * 100, 1) if disc is not None else None,
            }
            if unreliable:
                entry["cảnh_báo"] = "median P/B<1 — nghi lẫn mã nhỏ, verdict bị bỏ qua"
            out["so_sánh"][label] = entry
            if unreliable:
                out["nhận_định_peer"].append(
                    f"{label} median ngành {med:.2f} < 1 → BỎ QUA (peer lẫn mã nhỏ/UPCoM, "
                    "m23 không đáng tin cho bội số này)")
            elif disc is not None:
                verdict = ("RẺ hơn ngành" if disc < -0.15 else
                           "ĐẮT hơn ngành" if disc > 0.15 else "ngang ngành")
                out["nhận_định_peer"].append(
                    f"{label} {mine:.2f} vs median ngành {med:.2f} ({disc:+.0%}) → {verdict}")
        return out

    # ================= CHUẨN HÓA CHU KỲ (mid-cycle) — phân biệt rẻ-cơ-hội vs rẻ-đáng-đời =========
    # Bội số SPOT méo nặng với mã CHU KỲ (xây dựng, đầu tư công, thép): P/E thấp trên lãi ĐỈNH
    # trông "rẻ" nhưng ảo; P/E cao trên lãi ĐÁY trông "đắt" nhưng có thể là cơ hội. Chuẩn hóa =
    # đưa biên về mid-cycle (trung vị nhiều năm) rồi đọc lại bội số.
    #   P/E_chuẩn = P/E_spot × (biên_hiện_tại / biên_mid)   [doanh thu triệt tiêu]
    #   ROE_chuẩn = ROE_spot × (biên_mid / biên_hiện_tại)
    #   justified P/B (m24) = (ROE_chuẩn − g)/(r − g), chỉ có nghĩa khi ROE_chuẩn > g.
    # GIẢ ĐỊNH/GIỚI HẠN: coi doanh thu ở mức hiện tại, chỉ biên hồi quy về mid-cycle; median
    # nhiều năm giả định cấu trúc kinh doanh KHÔNG đổi (DN suy thoái cấu trúc → median thổi phồng).

    def _latest_revenue_equity(self, symbol: str):
        """(doanh_thu_thuần, vốn_CSH) năm gần nhất — chỉ dùng cho fallback năm LỖ."""
        rev = eq = None
        try:
            inc = self.fx.get_statement(symbol, "INCOME_STATEMENT")
            if not inc.empty and "Doanh thu thuần" in inc.columns:
                if "yearReport" in inc.columns:
                    inc = inc.sort_values("yearReport")
                rev = float(pd.to_numeric(inc["Doanh thu thuần"], errors="coerce").dropna().iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        try:
            bs = self.fx.get_statement(symbol, "BALANCE_SHEET")
            if not bs.empty and "Vốn chủ sở hữu" in bs.columns:
                if "yearReport" in bs.columns:
                    bs = bs.sort_values("yearReport")
                eq = float(pd.to_numeric(bs["Vốn chủ sở hữu"], errors="coerce").dropna().iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        return rev, eq

    def _cycle_metrics(self, df: pd.DataFrame, revenue_cur: Optional[float] = None,
                       equity_cur: Optional[float] = None, min_years: int = 4,
                       r: Optional[float] = None, g: Optional[float] = None) -> Dict[str, object]:
        """Metrics chuẩn hóa chu kỳ từ df ratios (thuần; fallback năm lỗ cần revenue/equity).
        r/g mặc định theo self (chỉnh được để dùng r/g theo ngành)."""
        r = self.r if r is None else r
        g = self.g if g is None else g
        ann = _annual_rows(df)
        margins = pd.to_numeric(ann.get("afterTaxProfitMargin", pd.Series(dtype=float)),
                                errors="coerce").dropna()
        margins = margins[margins != 0]
        res: Dict[str, object] = {"đủ_dữ_liệu": False, "cờ": []}
        if len(margins) < min_years:
            res["note"] = f"chỉ {len(margins)} năm biên (< {min_years}) → chưa đủ để chuẩn hóa chu kỳ"
            return res
        med_m = float(margins.median())
        cur = df.iloc[-1].to_dict()
        pe_s = _clean(cur, "pe")
        pb_s = _clean(cur, "pb")
        roe_s = _clean(cur, "roe")
        mcap = _mcap(cur)
        try:
            mar_c = float(cur.get("afterTaxProfitMargin"))
        except (TypeError, ValueError):
            mar_c = None
        if med_m <= 0:
            res["note"] = f"biên trung vị ≤ 0 ({med_m:.1%}) → lỗ xuyên chu kỳ, chuẩn hóa vô nghĩa"
            res["cờ"].append("lỗ xuyên chu kỳ")
            return res

        pe_n = roe_n = None
        method = "tỷ lệ biên"
        if mar_c is not None and mar_c > 0:
            if pe_s is not None:
                pe_n = pe_s * (mar_c / med_m)
            if roe_s is not None:
                roe_n = roe_s * (med_m / mar_c)
        else:
            method = "lãi chuẩn hóa từ doanh thu (năm lỗ)"
            if revenue_cur and mcap:
                ln_norm = med_m * revenue_cur
                if ln_norm > 0:
                    pe_n = mcap / ln_norm
                    if equity_cur and equity_cur > 0:
                        roe_n = ln_norm / equity_cur
            if pe_n is None:
                res["cờ"].append("biên hiện tại ≤0 (đang lỗ) & thiếu doanh thu → chưa chuẩn hóa được")

        if mar_c is None:
            cyc = "?"
        elif mar_c > med_m * 1.15:
            cyc = "ĐỈNH"
        elif mar_c < med_m * 0.85:
            cyc = "ĐÁY"
        else:
            cyc = "giữa"

        jpb_n = None
        if roe_n is not None and (r - g) > 0:
            if roe_n > g:
                jpb_n = (roe_n - g) / (r - g)
            else:
                res["cờ"].append(f"ROE chuẩn hóa ({roe_n:.1%}) ≤ g ({g:.0%}) → "
                                 "justified P/B không áp dụng (không tạo giá trị trên vốn)")

        res.update({
            "đủ_dữ_liệu": pe_n is not None,
            "n_năm": int(len(margins)),
            "biên_hiện_tại": round(mar_c, 4) if mar_c is not None else None,
            "biên_mid": round(med_m, 4),
            "chu_kỳ": cyc,
            "pe_spot": round(pe_s, 2) if pe_s is not None else None,
            "pe_chuẩn": round(pe_n, 2) if pe_n is not None else None,
            "pb": round(pb_s, 2) if pb_s is not None else None,
            "roe_spot": round(roe_s, 4) if roe_s is not None else None,
            "roe_chuẩn": round(roe_n, 4) if roe_n is not None else None,
            "justified_pb_chuẩn": round(jpb_n, 2) if jpb_n is not None else None,
            "phương_pháp": method,
        })
        return res

    def normalized_cycle(self, symbol: str, min_years: int = 4) -> Dict[str, object]:
        """Chuẩn hóa chu kỳ cho MỘT mã phi ngân hàng → P/E & ROE mid-cycle + justified P/B.

        Bank → bỏ qua (dùng CAMELS + P/B-ROE ở assess, m13). Năm lỗ → tự lấy doanh thu +
        vốn CSH để tính lãi chuẩn hóa trực tiếp.
        """
        symbol = symbol.upper().strip()
        sec = self.sx.sector_of(symbol)
        if sec.get("is_bank"):
            return {"symbol": symbol, "đủ_dữ_liệu": False,
                    "note": "ngân hàng — đọc bằng CAMELS + P/B-ROE (m13), không chuẩn hóa biên"}
        df = self.fx.get_ratios(symbol)
        if df.empty:
            return {"symbol": symbol, "đủ_dữ_liệu": False, "note": "không có dữ liệu ratio"}
        rev = eq = None
        try:
            need_fb = float(df.iloc[-1].get("afterTaxProfitMargin")) <= 0
        except (TypeError, ValueError):
            need_fb = True
        if need_fb:
            rev, eq = self._latest_revenue_equity(symbol)
        r, g = self._rg_for(symbol)
        res = self._cycle_metrics(df, revenue_cur=rev, equity_cur=eq, min_years=min_years, r=r, g=g)
        res["symbol"] = symbol
        return res

    @staticmethod
    def _pb_quality_split(pb_a, jpb_a, pb_b, jpb_b) -> Optional[Dict[str, float]]:
        """Phân rã chiết khấu P/B của A so B: phần 'đáng đời' (do ROE) vs phần 'dư' (cơ hội/rủi ro ẩn).

        chênh_thực = P/B_A/P/B_B − 1 ; chênh_hợp_lý = jP/B_A/jP/B_B − 1 (từ ROE chuẩn hóa).
        dư = thực − hợp_lý: âm ⇒ A rẻ HƠN mức chất lượng cho phép (rẻ cơ hội); ~0 ⇒ rẻ đáng đời.
        """
        if not (pb_a and pb_b and jpb_a and jpb_b) or pb_b <= 0 or jpb_a <= 0 or jpb_b <= 0:
            return None
        actual = pb_a / pb_b - 1
        justified = jpb_a / jpb_b - 1
        return {"chênh_pb_thực": actual, "chênh_pb_hợp_lý": justified, "dư": actual - justified}

    def compare_pair(self, a: str, b: str) -> Dict[str, object]:
        """So TRỰC TIẾP hai mã sau chuẩn hóa chu kỳ — trả lời 'vì sao A rẻ hơn B'."""
        a = a.upper().strip(); b = b.upper().strip()
        na = self.normalized_cycle(a)
        nb = self.normalized_cycle(b)
        out: Dict[str, object] = {"cặp": f"{a} vs {b}", a: na, b: nb, "diễn_giải": []}
        d: List[str] = out["diễn_giải"]
        if not (na.get("đủ_dữ_liệu") and nb.get("đủ_dữ_liệu")):
            d.append(f"Thiếu dữ liệu chuẩn hóa ({a}: {na.get('note','ok') if not na.get('đủ_dữ_liệu') else 'ok'}; "
                     f"{b}: {nb.get('note','ok') if not nb.get('đủ_dữ_liệu') else 'ok'}) → không so được chu kỳ.")
            return out
        d.append(f"Chu kỳ: {a} đang ở biên {na['chu_kỳ']} ({na['biên_hiện_tại']:.1%} vs mid {na['biên_mid']:.1%}); "
                 f"{b} ở biên {nb['chu_kỳ']} ({nb['biên_hiện_tại']:.1%} vs mid {nb['biên_mid']:.1%}).")
        d.append(f"P/E spot: {a} {na['pe_spot']} vs {b} {nb['pe_spot']} → "
                 f"P/E CHUẨN HÓA: {a} {na['pe_chuẩn']} vs {b} {nb['pe_chuẩn']}.")
        # phát hiện đảo thứ hạng khi chuẩn hóa
        if na['pe_spot'] and nb['pe_spot'] and na['pe_chuẩn'] and nb['pe_chuẩn']:
            spot_cheaper = a if na['pe_spot'] < nb['pe_spot'] else b
            norm_cheaper = a if na['pe_chuẩn'] < nb['pe_chuẩn'] else b
            if spot_cheaper != norm_cheaper:
                cyc_sc = na["chu_kỳ"] if spot_cheaper == a else nb["chu_kỳ"]
                d.append(f"⚠️ ĐẢO CHIỀU: spot cho thấy {spot_cheaper} rẻ hơn, nhưng sau chuẩn hóa "
                         f"{norm_cheaper} mới thực rẻ hơn — bội số spot của {spot_cheaper} bị méo bởi biên "
                         f"{'đỉnh' if cyc_sc == 'ĐỈNH' else 'đáy' if cyc_sc == 'ĐÁY' else 'chu kỳ'}.")
        # cầu P/B ↔ ROE chuẩn hóa
        d.append(f"P/B: {a} {na['pb']} vs {b} {nb['pb']}; ROE chuẩn hóa: {a} "
                 f"{_fmt_pct(na['roe_chuẩn'])} vs {b} {_fmt_pct(nb['roe_chuẩn'])}; "
                 f"justified P/B: {a} {na['justified_pb_chuẩn']} vs {b} {nb['justified_pb_chuẩn']}.")
        split = self._pb_quality_split(na['pb'], na['justified_pb_chuẩn'],
                                       nb['pb'], nb['justified_pb_chuẩn'])
        if split:
            thuc, hop_ly, du = split["chênh_pb_thực"], split["chênh_pb_hợp_lý"], split["dư"]
            verdict = ("RẺ CƠ HỘI — chiết khấu vượt mức chất lượng (bị bỏ quên)" if du < -0.05 else
                       "RẺ ĐÁNG ĐỜI — chiết khấu do ROE thấp hơn, đúng mức" if du > 0.05 else
                       "chiết khấu khớp đúng chênh lệch chất lượng")
            d.append(f"{a} có P/B {thuc:+.0%} so {b}; chất lượng (justified P/B từ ROE chuẩn hóa) "
                     f"chênh {hop_ly:+.0%}. Phần dư {du:+.0%} → {verdict}.")
        else:
            d.append("Không phân rã được cầu P/B–ROE (justified P/B ≤ 0 ở ít nhất một mã — ROE chuẩn hóa ≤ g).")
        return out

    def cycle_peer_compare(self, symbol: str, level: str = "icb_l2", max_peers: int = 30,
                           min_valid: int = 4, same_exchange: bool = True,
                           min_mcap_ty: float = 500.0) -> Dict[str, object]:
        """So mã với PEER cùng ngành TRÊN BỘI SỐ CHUẨN HÓA CHU KỲ (không phải spot).

        Trả P/E chuẩn hóa của mã vs MEDIAN peer + cầu P/B–ROE chuẩn hóa → verdict
        rẻ-cơ-hội / rẻ-đáng-đời / không-rẻ so với ngành. Peer dùng phương pháp tỷ lệ biên
        (nhẹ, 1 call/mã); peer năm lỗ hoặc thiếu năm bị BỎ khỏi median (ghi rõ số bỏ).
        """
        symbol = symbol.upper().strip()
        sec = self.sx.sector_of(symbol)
        if sec.get("is_bank"):
            return {"symbol": symbol, "note": "ngân hàng — không áp chuẩn hóa biên (m13 CAMELS)"}
        me = self.normalized_cycle(symbol)
        if not me.get("đủ_dữ_liệu"):
            return {"symbol": symbol, "note": f"mã đích thiếu dữ liệu chuẩn hóa: {me.get('note')}"}
        floor = min_mcap_ty * 1e9
        r, g = self._rg_for(symbol)  # peer cùng ngành → dùng chung r/g của mã đích
        peers = self.sx.peers(symbol, level=level, same_exchange=same_exchange)[:max_peers]
        pe_norm_vals, roe_norm_vals, jpb_vals, pb_vals = [], [], [], []
        used = skipped = 0
        for p in peers:
            try:
                dfp = self.fx.get_ratios(p)
            except Exception:  # noqa: BLE001
                continue
            if dfp.empty:
                continue
            mc = _mcap(dfp.iloc[-1].to_dict())
            if mc is not None and mc < floor:
                skipped += 1
                continue
            m = self._cycle_metrics(dfp, r=r, g=g)  # peer: không fallback năm lỗ
            if not m.get("đủ_dữ_liệu") or m.get("pe_chuẩn") is None:
                skipped += 1
                continue
            pe_norm_vals.append(m["pe_chuẩn"])
            if m.get("pb") is not None:
                pb_vals.append(m["pb"])
            if m.get("roe_chuẩn") is not None:
                roe_norm_vals.append(m["roe_chuẩn"])
            if m.get("justified_pb_chuẩn") is not None:
                jpb_vals.append(m["justified_pb_chuẩn"])
            used += 1

        out: Dict[str, object] = {
            "symbol": symbol, "ngành": f"{sec.get('icb_l2')} ({level})",
            "chu_kỳ_mã": me["chu_kỳ"], "số_peer_dùng": used, "bỏ_qua": skipped,
            "mã": {"pe_spot": me["pe_spot"], "pe_chuẩn": me["pe_chuẩn"], "pb": me["pb"],
                    "roe_chuẩn": me["roe_chuẩn"], "justified_pb_chuẩn": me["justified_pb_chuẩn"]},
            "nhận_định": [],
        }
        n: List[str] = out["nhận_định"]
        if used < min_valid:
            n.append(f"Chỉ {used} peer đủ chuẩn hóa (< {min_valid}) → so peer chuẩn hóa không đáng tin.")
            return out
        med_pe_n = float(np.median(pe_norm_vals))
        med_jpb = float(np.median(jpb_vals)) if jpb_vals else None
        out["median_ngành"] = {"pe_chuẩn": round(med_pe_n, 2),
                                "justified_pb_chuẩn": round(med_jpb, 2) if med_jpb else None,
                                "n_pe": len(pe_norm_vals), "n_jpb": len(jpb_vals)}
        disc_pe = me["pe_chuẩn"] / med_pe_n - 1 if med_pe_n > 0 else None
        if disc_pe is not None:
            v = ("RẺ hơn ngành" if disc_pe < -0.15 else
                 "ĐẮT hơn ngành" if disc_pe > 0.15 else "ngang ngành")
            n.append(f"P/E chuẩn hóa {me['pe_chuẩn']} vs median ngành {med_pe_n:.1f} "
                     f"({disc_pe:+.0%}) → {v} (đã khử méo đỉnh/đáy chu kỳ).")
        # so P/B mã với median P/B ngành, phân rã theo justified P/B ngành
        if pb_vals and me.get("pb"):
            med_pb = float(np.median(pb_vals))
            if med_jpb and me.get("justified_pb_chuẩn"):
                sp = self._pb_quality_split(me["pb"], me["justified_pb_chuẩn"], med_pb, med_jpb)
                if sp:
                    du = sp["dư"]
                    verdict = ("RẺ CƠ HỘI — chiết khấu P/B vượt mức chất lượng ngành (bị bỏ quên)"
                               if du < -0.05 else
                               "RẺ ĐÁNG ĐỜI — P/B thấp tương xứng ROE chuẩn hóa thấp" if du > 0.05 else
                               "P/B khớp đúng chất lượng ngành")
                    n.append(f"P/B {me['pb']} vs median ngành {med_pb:.2f} ({sp['chênh_pb_thực']:+.0%}); "
                             f"chất lượng chênh {sp['chênh_pb_hợp_lý']:+.0%}; dư {du:+.0%} → {verdict}.")
        return out

    @staticmethod
    def _summarize(out: Dict, is_bank: bool, roe: Optional[float], pb: Optional[float]) -> str:
        n_flag = len(out["cờ_rủi_ro"])
        cheap_signals = sum(1 for s in out["nhận_định"] if "RẺ" in s)
        exp_signals = sum(1 for s in out["nhận_định"] if "ĐẮT" in s)
        parts = []
        if cheap_signals and not exp_signals:
            parts.append("Tín hiệu định giá nghiêng RẺ so lịch sử")
        elif exp_signals and not cheap_signals:
            parts.append("Tín hiệu định giá nghiêng ĐẮT so lịch sử")
        else:
            parts.append("Định giá quanh vùng trung bình / hỗn hợp")
        if roe is not None:
            parts.append(f"ROE {roe:.1%}")
        parts.append(f"{n_flag} cờ rủi ro" if n_flag else "không cờ rủi ro nổi bật")
        return "; ".join(parts) + ". (Nhận định có điều kiện, cần kiểm chất lượng & bối cảnh — không phải khuyến nghị)"


def _print_assessment(a: Dict[str, object]) -> None:
    print(f"\n{'='*60}\n{a['symbol']} — {a.get('loại','?')} — kỳ {a.get('kỳ','?')}")
    if "error" in a:
        print("  LỖI:", a["error"]); return
    print(f"  TÓM TẮT: {a['tóm_tắt']}")
    print("  Nhận định:")
    for n in a["nhận_định"]:
        print(f"    • {n}")
    if a["cờ_rủi_ro"]:
        print("  ⚠️ Cờ rủi ro:")
        for f in a["cờ_rủi_ro"]:
            print(f"    ⚠ {f}")
    print(f"  (Giả định: r={a['giả_định']['r (cost of equity)']:.0%}, "
          f"g={a['giả_định']['g (dài hạn)']:.0%})")


def _print_cycle(c: Dict[str, object]) -> None:
    if not c.get("đủ_dữ_liệu"):
        print(f"  {c.get('symbol','?')}: (không chuẩn hóa được) {c.get('note','')}")
        return
    print(f"  {c['symbol']} [{c['chu_kỳ']}]: P/E {c['pe_spot']}→{c['pe_chuẩn']} (chuẩn hóa) | "
          f"P/B {c['pb']} | ROE chuẩn {_fmt_pct(c['roe_chuẩn'])} | "
          f"justified P/B {c['justified_pb_chuẩn']} | biên {_fmt_pct(c['biên_hiện_tại'])}"
          f" vs mid {_fmt_pct(c['biên_mid'])}")
    for f in c.get("cờ", []):
        print(f"      ⚠ {f}")


if __name__ == "__main__":
    import argparse
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="Định giá + chuẩn hóa chu kỳ (m23/m24)")
    ap.add_argument("--pair", nargs=2, metavar=("A", "B"),
                    help="So trực tiếp 2 mã sau chuẩn hóa chu kỳ (vd --pair LCG VCG)")
    ap.add_argument("--cycle", nargs="+", metavar="SYM", help="Chuẩn hóa chu kỳ cho các mã")
    ap.add_argument("--peer", metavar="SYM", help="So peer ngành trên bội số CHUẨN HÓA")
    args = ap.parse_args()
    v = VNValuation()

    if args.pair:
        res = v.compare_pair(*args.pair)
        print(f"\n{'='*66}\nVÌ SAO {args.pair[0]} RẺ HƠN {args.pair[1]}? (chuẩn hóa chu kỳ)\n{'='*66}")
        for line in res["diễn_giải"]:
            print(f"  {line}")
    if args.cycle:
        print(f"\n{'='*66}\nCHUẨN HÓA CHU KỲ\n{'='*66}")
        for sym in args.cycle:
            _print_cycle(v.normalized_cycle(sym))
    if args.peer:
        pc = v.cycle_peer_compare(args.peer)
        print(f"\n{'='*66}\nSO PEER CHUẨN HÓA — {args.peer} ({pc.get('ngành','?')})\n{'='*66}")
        if pc.get("note"):
            print(f"  {pc['note']}")
        for line in pc.get("nhận_định", []):
            print(f"  ◦ {line}")

    if not (args.pair or args.cycle or args.peer):
        # demo mặc định: assess (kiểm không regress) + câu hỏi LCG vs VCG
        for sym in ("FPT", "VCB"):
            _print_assessment(v.assess(sym))
            pc = v.peer_compare(sym)
            print(f"  So peer ngành ({pc['ngành']}, {pc['số_peer_dùng']} peer):")
            for n in pc["nhận_định_peer"]:
                print(f"    ◦ {n}")
        print(f"\n{'='*66}\nDEMO chuẩn hóa chu kỳ: LCG/VCG/HHV\n{'='*66}")
        for sym in ("LCG", "VCG", "HHV"):
            _print_cycle(v.normalized_cycle(sym))
        res = v.compare_pair("LCG", "VCG")
        print(f"\nVÌ SAO LCG RẺ HƠN VCG?")
        for line in res["diễn_giải"]:
            print(f"  {line}")
