# -*- coding: utf-8 -*-
"""
Pipeline TỔNG HỢP: ghép 5 lớp phân tích thành MỘT báo cáo top-down chạy được.

Luồng "từ tổng quát đến chi tiết" (khớp cách giới phân tích làm, nền CFA L2):

  1. NHỊP THỊ TRƯỜNG  (vn_topdown.market_pulse, m37)
       VN-Index / HNX / UPCoM: trend vs MA50/MA200, RSI14, %thay đổi.
  2. VŨ TRỤ THANH KHOẢN  (vn_topdown.liquid_universe)
       Lọc N mã giao dịch sôi động nhất (GTGD) — nền cho mọi bước sau, tránh quét rác.
  3. XẾP HẠNG NGÀNH  (vn_topdown.sector_ranking, m23)
       Median P/E, P/B, ROE theo ngành ICB → ngành nào rẻ + sinh lời cao.
  4. ĐỊNH GIÁ MÃ TRỌNG ĐIỂM  (vn_valuation.assess / peer_compare, m23/m24/m13/m14)
       Drill K mã: percentile lịch sử + justified P/B + CAMELS bank + cờ value-trap.

Xuất báo cáo Markdown vào reports/YYYY-MM-DD_phantich.md và in tóm tắt ra console.
Không LLM, không key — thuần dữ liệu + lý luận định lượng, tái lập được (cùng ngày ra cùng số).

Chạy:
    python vn_report.py                    # mặc định: liquid 100, drill 12, không peer
    python vn_report.py --drill 20 --peers # so peer ngành cho mỗi mã (tốn API hơn nhiều)
    python vn_report.py --symbols FPT,VCB,HPG   # chỉ drill danh sách chỉ định
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
from collections import OrderedDict, deque
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from vn_data import ensure_utf8_stdout
from vn_topdown import VNTopDown
from vn_valuation import VNValuation
from vn_events import VCIEvents, fmt_event

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent / "reports"


# --------------------------------------------------------------------------- #
# Tiện ích render Markdown
# --------------------------------------------------------------------------- #
def _fmt(v, nd: int = 2) -> str:
    """Format số gọn cho bảng; None/NaN -> '—'."""
    if v is None:
        return "—"
    if isinstance(v, float):
        if pd.isna(v):
            return "—"
        return f"{v:,.{nd}f}"
    return str(v)


def _df_to_md(df: pd.DataFrame, cols: Optional[List[str]] = None,
              headers: Optional[Dict[str, str]] = None) -> str:
    """Bảng Markdown từ DataFrame (đã format sẵn giá trị dạng chuỗi)."""
    if df is None or df.empty:
        return "_Không có dữ liệu._"
    cols = cols or list(df.columns)
    headers = headers or {}
    head = "| " + " | ".join(headers.get(c, c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [head, sep]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Diễn giải nhịp thị trường thành một câu
# --------------------------------------------------------------------------- #
def _read_market(pulse: Dict[str, Dict]) -> str:
    vni = pulse.get("VN-Index")
    if not vni:
        return "Không lấy được VN-Index."
    rsi = vni.get("RSI14")
    trend = vni.get("trend", "?")
    chg20 = vni.get("%_20p")
    bits = [f"VN-Index đang **{trend}**"]
    if chg20 is not None:
        bits.append(f"20 phiên {chg20:+.1f}%")
    if rsi is not None:
        if rsi >= 70:
            zone = "quá mua"
        elif rsi <= 30:
            zone = "quá bán"
        else:
            zone = "trung tính"
        bits.append(f"RSI14 {rsi} ({zone})")
    return "; ".join(bits) + "."


# --------------------------------------------------------------------------- #
# Chọn ngành trọng điểm từ bảng xếp hạng (rẻ + sinh lời cao)
# --------------------------------------------------------------------------- #
def _focus_sectors(rank: pd.DataFrame, n: int = 3) -> List[str]:
    """Ngành hấp dẫn = ROE median cao mà P/E median không quá đắt.

    Xếp theo ROE giảm dần (bảng đã sort sẵn), lấy top-n có pe_median hợp lệ & < 25.
    """
    if rank is None or rank.empty:
        return []
    sub = rank[rank["pe_median"].notna() & (rank["pe_median"] < 25)]
    if sub.empty:
        sub = rank
    return sub["sector"].head(n).tolist()


# --------------------------------------------------------------------------- #
# Pipeline chính
# --------------------------------------------------------------------------- #
class VNReport:
    def __init__(self, sector_level: str = "icb_l1"):
        self.td = VNTopDown()
        # dùng chung client fundamentals/sectors giữa top-down và valuation (đỡ handshake lại)
        self.val = VNValuation(fx=self.td.fx, sx=self.td.sx)
        self.ev = VCIEvents()
        self.sector_level = sector_level
        # gom dữ liệu có cấu trúc để tái dùng cho digest Telegram (điền trong build())
        self.data: Dict[str, object] = {}

    def build(self, liquid_top: int = 100, drill: int = 12,
              boards: Optional[List[str]] = None, with_peers: bool = False,
              symbols: Optional[List[str]] = None,
              max_per_sector: Optional[int] = None,
              with_events: bool = True) -> str:
        today = dt.date.today().isoformat()
        self.data = {"ngày": today, "nhịp": {}, "ngành_trọng_điểm": [], "mã": []}
        parts: List[str] = []
        parts.append(f"# Báo cáo phân tích top-down TTCK Việt Nam — {today}\n")
        parts.append("_Phân tích định lượng theo khung CFA L2 (m37 vĩ mô · m23 bội số · "
                     "m24 residual income · m13 ngân hàng · m14 chất lượng). "
                     "Không phải khuyến nghị mua/bán._\n")

        # ---- 1. Nhịp thị trường ----
        logger.info("1/4 Nhịp thị trường...")
        pulse = self.td.market_pulse()
        self.data["nhịp"] = pulse
        parts.append("## 1. Nhịp thị trường (m37)\n")
        parts.append("> " + _read_market(pulse) + "\n")
        prows = []
        for name, p in pulse.items():
            prows.append({
                "Chỉ số": name,
                "Đóng cửa": _fmt(p.get("đóng_cửa"), 1),
                "%5p": _fmt(p.get("%_5p"), 2),
                "%20p": _fmt(p.get("%_20p"), 2),
                "vsMA50%": _fmt(p.get("vs_MA50_%"), 1),
                "vsMA200%": _fmt(p.get("vs_MA200_%"), 1),
                "RSI14": _fmt(p.get("RSI14"), 1),
                "Xu hướng": p.get("trend", "?"),
            })
        parts.append(_df_to_md(pd.DataFrame(prows)) + "\n")

        # ---- 2. Vũ trụ thanh khoản ----
        logger.info("2/4 Vũ trụ thanh khoản (top %d)...", liquid_top)
        liq = self.td.liquid_universe(top=liquid_top, boards=boards)
        parts.append(f"## 2. Vũ trụ thanh khoản (top {len(liq)} theo GTGD)\n")
        if not liq.empty:
            board_ct = liq["board"].value_counts().to_dict()
            parts.append("Phân bố sàn: " +
                         ", ".join(f"{k} {v}" for k, v in board_ct.items()) + ".\n")
            top_show = liq.head(15).copy()
            top_show["GTGD_tỷ"] = top_show["gtgd_tb_ty"].map(lambda x: _fmt(x, 1))
            parts.append(_df_to_md(
                top_show, cols=["symbol", "board", "name", "GTGD_tỷ"],
                headers={"symbol": "Mã", "board": "Sàn", "name": "Tên",
                         "GTGD_tỷ": "GTGD TB (tỷ)"}) + "\n")

        # ---- 3. Xếp hạng ngành ----
        logger.info("3/4 Xếp hạng ngành (%s)...", self.sector_level)
        universe = liq["symbol"].tolist() if not liq.empty else []
        rank = self.td.sector_ranking(universe, level=self.sector_level)
        focus = _focus_sectors(rank)
        self.data["ngành_trọng_điểm"] = focus
        parts.append(f"## 3. Xếp hạng ngành ({self.sector_level})\n")
        if not rank.empty:
            if focus:
                parts.append("**Ngành trọng điểm** (ROE cao + P/E không quá đắt): "
                             + ", ".join(f"`{s}`" for s in focus) + ".\n")
            rshow = rank.copy()
            for c in ("pe_median", "pb_median", "roe_median", "vốn_hóa_ty"):
                if c in rshow.columns:
                    nd = 0 if c == "vốn_hóa_ty" else (1 if c == "roe_median" else 2)
                    rshow[c] = rshow[c].map(lambda x, nd=nd: _fmt(x, nd))
            parts.append(_df_to_md(
                rshow, cols=["sector", "số_mã", "pe_median", "pb_median",
                             "roe_median", "vốn_hóa_ty"],
                headers={"sector": "Ngành", "số_mã": "Số mã",
                         "pe_median": "P/E median", "pb_median": "P/B median",
                         "roe_median": "ROE% median", "vốn_hóa_ty": "Vốn hóa (tỷ)"}) + "\n")
        else:
            parts.append("_Không dựng được xếp hạng ngành._\n")

        # ---- 4. Chọn mã drill ----
        smap = self.td.sx.get_industry_map()
        if symbols:
            drill_syms = [s.upper().strip() for s in symbols]
        else:
            drill_syms = self._pick_drill(liq, smap, focus, drill,
                                          max_per_sector=max_per_sector)
        parts.append(f"## 4. Định giá {len(drill_syms)} mã trọng điểm (m23/m24/m13/m14)\n")
        parts.append("_Mỗi mã: đắt/rẻ theo percentile lịch sử, justified P/B (residual income), "
                     "cờ rủi ro chất lượng; ngân hàng đọc bằng CAMELS._\n")

        for i, sym in enumerate(drill_syms, 1):
            logger.info("4/4 Định giá %d/%d: %s", i, len(drill_syms), sym)
            md, rec = self._assess_block(sym, smap, with_peers, with_events)
            parts.append(md)
            self.data["mã"].append(rec)

        # ---- Giả định & lưu ý ----
        parts.append("## Giả định & lưu ý\n")
        parts.append(f"- Cost of equity r = **{self.val.r:.0%}**, tăng trưởng dài hạn "
                     f"g = **{self.val.g:.0%}** (giả định cho TTCK VN, chỉnh được — "
                     "ảnh hưởng trực tiếp justified P/B).")
        parts.append("- Percentile lịch sử tính trên chính chuỗi năm của từng mã "
                     "(chưa chuẩn hóa theo chu kỳ ngành).")
        parts.append("- Số liệu định giá từ VCI (Vietcap); có thể trễ so với kỳ báo cáo mới nhất.")
        parts.append("- Đây là công cụ HỖ TRỢ ĐỌC, không phải khuyến nghị đầu tư.\n")

        report = "\n".join(parts)
        return report

    # ---- Digest Telegram tất định (đọc self.data sau khi build) — dễ hiểu cho người mới ----
    def digest(self) -> str:
        d = self.data
        if not d:
            return "Chưa có dữ liệu (gọi build() trước)."
        L: List[str] = [f"📊 PHÂN TÍCH TOP-DOWN TTCK VN — {d.get('ngày','')}"]

        # 1) Nhịp thị trường (một câu dễ hiểu)
        vni = (d.get("nhịp") or {}).get("VN-Index")
        if vni:
            L.append("")
            L.append(f"🌐 Thị trường: VN-Index {vni.get('đóng_cửa')}, "
                     f"20 phiên {_fmt(vni.get('%_20p'),1)}%, RSI {vni.get('RSI14')} — "
                     f"{vni.get('trend','?')}")
        focus = d.get("ngành_trọng_điểm") or []
        if focus:
            L.append(f"🏭 Ngành trọng điểm: {', '.join(focus)}")

        stocks = d.get("mã") or []
        # 2) Cảnh báo rủi ro (mã có cờ) — cho người mới biết chỗ nào cần né
        risky = [s for s in stocks if s.get("cờ_rủi_ro")]
        if risky:
            L.append("")
            L.append("⚠️ Cần thận trọng:")
            for s in risky[:5]:
                L.append(f"• {s['symbol']} ({s.get('ngành') or '?'}): {s['cờ_rủi_ro'][0]}")

        # 3) Định giá nghiêng RẺ (cơ hội đáng soi) — không phải khuyến nghị
        cheap = [s for s in stocks if s.get("tóm_tắt") and "RẺ" in s["tóm_tắt"]
                 and not s.get("cờ_rủi_ro")]
        if cheap:
            L.append("")
            L.append("💡 Định giá nghiêng RẺ so lịch sử (cần tự kiểm chất lượng):")
            for s in cheap[:6]:
                nm = f" — {s['tên']}" if s.get("tên") else ""
                L.append(f"• {s['symbol']}{nm} ({s.get('ngành') or '?'})")

        # 4) Sự kiện nổi bật: cổ tức sắp GDKHQ + KQKD
        today = dt.date.today()
        div_lines, kq_lines = [], []
        for s in stocks:
            for e in s.get("sự_kiện", []):
                if e.get("code") == "DIV" and e.get("GDKHQ") and e["GDKHQ"] >= today:
                    vps = f" {e['giá_trị_cp']:,.0f}đ/cp" if e.get("giá_trị_cp") else ""
                    div_lines.append(f"• {s['symbol']}: cổ tức{vps}, GDKHQ {e['GDKHQ'].strftime('%d/%m')}")
            for n in s.get("tin", []):
                t = n.get("tiêu_đề", "")
                if any(k in t.lower() for k in ("kết quả kinh doanh", "kqkd", "lợi nhuận",
                                                "trúng thầu", "trúng gói", "ký hợp đồng")):
                    kq_lines.append(f"• [{n['ngày'].strftime('%d/%m')}] {t}")
        if div_lines:
            L.append("")
            L.append("💰 Cổ tức sắp chốt quyền:")
            L.extend(div_lines[:6])
        if kq_lines:
            L.append("")
            L.append("📰 KQKD / hợp đồng đáng chú ý:")
            L.extend(kq_lines[:6])

        L.append("")
        L.append("_Công cụ hỗ trợ đọc theo khung CFA, KHÔNG phải khuyến nghị mua/bán._")
        return "\n".join(L)

    # ---- chọn mã drill: RẢI ĐỀU theo ngành (round-robin) để không lệch 1 ngành ----
    def _pick_drill(self, liq: pd.DataFrame, smap: pd.DataFrame,
                    focus: List[str], k: int,
                    max_per_sector: Optional[int] = None) -> List[str]:
        """Chọn K mã, mỗi lượt lấy 1 mã/ngành (ngành trọng điểm trước, trong ngành theo
        thanh khoản), lặp tới đủ K. Round-robin ⇒ bank không lấp hết slot dù thanh khoản
        cao. `max_per_sector` (nếu đặt) chặn cứng số mã mỗi ngành.
        """
        if liq.empty:
            return []
        df = liq.merge(smap[["symbol", self.sector_level]], on="symbol", how="left")
        df = df.rename(columns={self.sector_level: "_sector"})
        df["_sector"] = df["_sector"].fillna("?")

        # Hàng đợi mỗi ngành, GIỮ thứ tự thanh khoản (liq đã sort giảm dần)
        queues: "OrderedDict[str, deque]" = OrderedDict()
        for sym, sec in zip(df["symbol"], df["_sector"]):
            queues.setdefault(sec, deque()).append(sym)

        # Thứ tự duyệt ngành: trọng điểm trước (theo focus), rồi ngành khác theo lần xuất hiện
        first_seen = list(queues.keys())
        ordered = [s for s in focus if s in queues] + \
                  [s for s in first_seen if s not in focus]

        picks: List[str] = []
        counts: Dict[str, int] = {}
        while len(picks) < k:
            progressed = False
            for s in ordered:
                if len(picks) >= k:
                    break
                if max_per_sector is not None and counts.get(s, 0) >= max_per_sector:
                    continue
                if queues[s]:
                    picks.append(queues[s].popleft())
                    counts[s] = counts.get(s, 0) + 1
                    progressed = True
            if not progressed:
                break
        return picks

    # ---- khối định giá cho một mã: trả (markdown, record có cấu trúc) ----
    def _assess_block(self, sym: str, smap: pd.DataFrame, with_peers: bool,
                      with_events: bool):
        sec_row = smap[smap["symbol"] == sym]
        sec_l1 = sec_l2 = name = None
        if not sec_row.empty:
            r = sec_row.iloc[0]
            sec_l1, sec_l2, name = r.get("icb_l1"), r.get("icb_l2"), r.get("name")
        sec_txt = f" · {sec_l1 or '?'} › {sec_l2 or '?'}"
        rec: Dict[str, object] = {"symbol": sym, "tên": name, "ngành": sec_l1,
                                  "tóm_tắt": None, "cờ_rủi_ro": [], "sự_kiện": [], "tin": []}
        lines = [f"### {sym}{sec_txt}\n"]
        try:
            a = self.val.assess(sym)
        except Exception as e:  # noqa: BLE001
            rec["tóm_tắt"] = f"lỗi định giá: {e}"
            return "\n".join(lines) + f"\n_Lỗi định giá: {e}_\n", rec
        if "error" in a:
            rec["tóm_tắt"] = a["error"]
            return "\n".join(lines) + f"\n_{a['error']}_\n", rec

        rec["tóm_tắt"] = a["tóm_tắt"]
        rec["cờ_rủi_ro"] = list(a.get("cờ_rủi_ro", []))
        lines.append(f"**Tóm tắt:** {a['tóm_tắt']}\n")
        if a.get("nhận_định"):
            lines.append("Nhận định:")
            for n in a["nhận_định"]:
                lines.append(f"- {n}")
            lines.append("")
        if a.get("cờ_rủi_ro"):
            lines.append("⚠️ Cờ rủi ro:")
            for f in a["cờ_rủi_ro"]:
                lines.append(f"- {f}")
            lines.append("")

        if with_peers:
            try:
                pc = self.val.peer_compare(sym, level="icb_l2")
                if pc.get("nhận_định_peer"):
                    lines.append(f"So với peer ngành ({pc.get('ngành')}, "
                                 f"{pc.get('số_peer_dùng')} peer):")
                    for n in pc["nhận_định_peer"]:
                        lines.append(f"- {n}")
                    lines.append("")
            except Exception as e:  # noqa: BLE001
                lines.append(f"_So peer lỗi: {e}_\n")

        # ---- Sự kiện & tin doanh nghiệp gần đây ----
        if with_events:
            try:
                r_ev = self.ev.recent(sym)
                rec["sự_kiện"] = r_ev.get("sự_kiện", [])
                rec["tin"] = r_ev.get("tin", [])
                if r_ev["sự_kiện"] or r_ev["tin"]:
                    lines.append("Sự kiện & tin gần đây:")
                    for e in r_ev["sự_kiện"]:
                        lines.append(f"- 📌 {fmt_event(e)}")
                    for n in r_ev["tin"]:
                        lines.append(f"- 📰 [{n['ngày'].strftime('%d/%m')}] {n['tiêu_đề']}")
                    lines.append("")
            except Exception as e:  # noqa: BLE001
                lines.append(f"_Lấy sự kiện lỗi: {e}_\n")
        return "\n".join(lines), rec


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Báo cáo phân tích top-down TTCK VN")
    ap.add_argument("--liquid", type=int, default=100,
                    help="Số mã trong vũ trụ thanh khoản (mặc định 100)")
    ap.add_argument("--drill", type=int, default=12,
                    help="Số mã định giá sâu (mặc định 12)")
    ap.add_argument("--boards", type=str, default=None,
                    help="Lọc sàn, vd 'HOSE,HNX,UPCoM' (mặc định: cả 3)")
    ap.add_argument("--symbols", type=str, default=None,
                    help="Chỉ drill danh sách chỉ định, vd 'FPT,VCB,HPG' (bỏ qua bước chọn tự động)")
    ap.add_argument("--per-sector", type=int, default=None,
                    help="Chặn cứng số mã drill mỗi ngành (mặc định: không chặn, chỉ rải round-robin)")
    ap.add_argument("--peers", action="store_true",
                    help="Bật so sánh peer ngành cho mỗi mã (tốn nhiều API hơn)")
    ap.add_argument("--no-events", action="store_true",
                    help="Tắt phần sự kiện & tin doanh nghiệp (mặc định: bật)")
    ap.add_argument("--telegram", action="store_true",
                    help="Gửi digest tất định qua Telegram (cần TELEGRAM_TOKEN/TELEGRAM_CHAT)")
    ap.add_argument("--digest-out", type=str, default=None,
                    help="Lưu digest Telegram ra file (để xem/kiểm trước khi gửi)")
    ap.add_argument("--sector-level", type=str, default="icb_l1",
                    help="Cấp ICB xếp hạng ngành (icb_l1..icb_l4)")
    ap.add_argument("--out", type=str, default=None, help="Đường dẫn file .md (mặc định reports/)")
    args = ap.parse_args()

    ensure_utf8_stdout()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    boards = [b.strip() for b in args.boards.split(",")] if args.boards else None
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    rep = VNReport(sector_level=args.sector_level)
    md = rep.build(liquid_top=args.liquid, drill=args.drill, boards=boards,
                   with_peers=args.peers, symbols=symbols,
                   max_per_sector=args.per_sector, with_events=not args.no_events)

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else REPORTS_DIR / f"{dt.date.today().isoformat()}_phantich.md"
    out_path.write_text(md, encoding="utf-8")
    print("\n" + "=" * 60)
    print("Đã lưu báo cáo:", out_path)

    # Digest Telegram (tất định, keyless)
    digest = rep.digest()
    if args.digest_out:
        dp = Path(args.digest_out)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text(digest, encoding="utf-8")
        print("Đã lưu digest:", args.digest_out)
    if args.telegram:
        from vn_telegram import send_message
        ok = send_message(digest)
        print("Gửi Telegram:", "✅ OK" if ok else "❌ thất bại (xem log)")
    print("=" * 60)
    print("\n----- DIGEST -----\n" + digest)


if __name__ == "__main__":
    main()
