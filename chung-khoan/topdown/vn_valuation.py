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

        # Chuỗi năm (quarter rỗng/0) để tính percentile lịch sử
        annual = ratios[ratios.get("quarter").fillna(0) == 0] if "quarter" in ratios else ratios
        if annual.empty:
            annual = ratios
        latest = annual.iloc[-1].to_dict()

        out: Dict[str, object] = {
            "symbol": symbol,
            "kỳ": f"{latest.get('yearReport')}",
            "loại": "Ngân hàng" if self._is_bank(latest) else "Phi ngân hàng",
            "giả_định": {"r (cost of equity)": self.r, "g (dài hạn)": self.g},
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
        if roe is not None and pb is not None and (self.r - self.g) > 0:
            justified_pb = (roe - self.g) / (self.r - self.g)
            ev["justified_P/B (m24)"] = {
                "công thức": "(ROE − g)/(r − g)",
                "ROE": round(roe, 4), "r": self.r, "g": self.g,
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
            if pb > 1 and roe < self.r:
                flags.append(f"P/B>1 ({pb:.2f}) nhưng ROE ({roe:.1%}) < r ({self.r:.0%}) "
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


if __name__ == "__main__":
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    v = VNValuation()
    for sym in ("FPT", "VCB"):
        _print_assessment(v.assess(sym))
        pc = v.peer_compare(sym)
        print(f"  So peer ngành ({pc['ngành']}, {pc['số_peer_dùng']} peer):")
        for n in pc["nhận_định_peer"]:
            print(f"    ◦ {n}")
