# -*- coding: utf-8 -*-
"""
BÁO CÁO DANH MỤC + KÍCH THƯỚC VỊ THẾ — từ "chọn 1 mã" sang "quyết định đầu tư".

Vấn đề: giữ LCG + HHV + VCG (đều đầu tư công) KHÔNG phải đa dạng hóa — cùng rủi ro giải
ngân, tương quan giá 0.6–0.8, đổ đèo cùng lúc. Module này:
  1. Đo TƯƠNG QUAN giá thật (return ngày ~1 năm) + gom CỤM (corr cao HOẶC cùng ngành ICB).
  2. Chia tỷ trọng ĐỀU NHAU rồi cắt theo TRẦN mã + TRẦN cụm (water-filling; dư → tiền mặt).
     Triết lý: ít giả định, khó overfit — chống "đa dạng giả" bằng trần cụm, không tối ưu
     mean-variance (khuếch đại sai số ước lượng).
  3. Vùng giá VÀO/THOÁT: tái dùng khung P/B kịch bản (bear/base/bull) của vn_decision.
  4. Rủi ro danh mục: HHI, số vị thế hiệu dụng, biến động danh mục vs bình quân, và verdict
     ĐA DẠNG THẬT hay GIẢ.

KHÔNG phải khuyến nghị mua/bán. Trần & tương quan là công cụ kiểm soát rủi ro, không bảo
chứng lợi nhuận. Xem [[reference_quant_validation_pipeline]] (validation là phòng thủ).

Chạy:  python vn_portfolio.py LCG,HHV,VCG
       python vn_portfolio.py LCG,HHV,VCG,VNM,FPT --capital 100   # 100 triệu đồng
       python vn_portfolio.py LCG,HHV,VCG --name-cap 0.25 --cluster-cap 0.40 --corr 0.6
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from vn_data import VCIClient, ensure_utf8_stdout
from vn_sectors import VCISectors
from vn_deepdive_report import build, _px, _html_shell, _md_inline
from vn_decision import scenario_prices

logger = logging.getLogger(__name__)
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
TRADING_DAYS = 252


# ============================================================================
# Tương quan & biến động từ giá
# ============================================================================
def price_stats(symbols: List[str], days: int = 400
                ) -> Tuple[pd.DataFrame, pd.Series, int]:
    """Trả (ma_trận_tương_quan, biến_động_năm_hóa, số_phiên_chung) từ return ngày.

    Giá VCI đã điều chỉnh cổ tức/chia tách (đã kiểm ở vn_backtest). Align theo ngày chung.
    """
    cli = VCIClient()
    data = cli.get_ohlcv(symbols, days=days)
    closes = pd.DataFrame({s: data[s].set_index("date")["close"]
                           for s in symbols if s in data and not data[s].empty})
    closes = closes.dropna()
    if closes.shape[0] < 30 or closes.shape[1] < 2:
        return pd.DataFrame(), pd.Series(dtype=float), closes.shape[0]
    rets = closes.pct_change().dropna()
    corr = rets.corr()
    vol = rets.std() * math.sqrt(TRADING_DAYS)  # năm hóa
    return corr, vol, closes.shape[0]


# ============================================================================
# Gom cụm rủi ro: corr cao HOẶC cùng ngành ICB (union-find)
# ============================================================================
def cluster_positions(symbols: List[str], corr: pd.DataFrame, sectors: Dict[str, str],
                      corr_thresh: float = 0.6) -> Dict[str, int]:
    """Gom mã thành cụm: nối 2 mã nếu tương quan ≥ ngưỡng HOẶC cùng ngành ICB L2.

    Cùng cụm = cùng rủi ro hệ thống (chủ đề/catalyst chung) → không tính là đa dạng.
    """
    parent = {s: s for s in symbols}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            same_sec = (sectors.get(a) and sectors.get(a) == sectors.get(b))
            hi_corr = (not corr.empty and a in corr.index and b in corr.columns
                       and pd.notna(corr.at[a, b]) and corr.at[a, b] >= corr_thresh)
            if same_sec or hi_corr:
                union(a, b)
    # đánh số cụm 0..K theo thứ tự xuất hiện
    roots, cid = {}, {}
    for s in symbols:
        r = find(s)
        if r not in roots:
            roots[r] = len(roots)
        cid[s] = roots[r]
    return cid


# ============================================================================
# Chia tỷ trọng: ĐỀU NHAU + trần mã + trần cụm (water-filling)
# ============================================================================
def size_equal_capped(symbols: List[str], clusters: Dict[str, int],
                      name_cap: float = 0.25, cluster_cap: float = 0.40,
                      max_iter: int = 500) -> Tuple[Dict[str, float], float]:
    """Chia đều 1/N rồi cắt theo trần mã & trần cụm; phần dư (không đặt được) → tiền mặt.

    Vòng lặp: (1) kẹp mã vượt trần mã; (2) co cụm vượt trần cụm; (3) rải phần dư cho mã
    CÒN dư địa (chưa chạm trần mã VÀ thuộc cụm chưa chạm trần cụm). Hết chỗ rải → tiền mặt.
    """
    n = len(symbols)
    if n == 0:
        return {}, 1.0
    w = {s: 1.0 / n for s in symbols}
    cset = sorted(set(clusters.values()))

    def cluster_total(cid):
        return sum(w[s] for s in symbols if clusters[s] == cid)

    for _ in range(max_iter):
        excess = 0.0
        # (1) trần mã
        for s in symbols:
            if w[s] > name_cap + 1e-12:
                excess += w[s] - name_cap
                w[s] = name_cap
        # (2) trần cụm
        for cid in cset:
            tot = cluster_total(cid)
            if tot > cluster_cap + 1e-12:
                scale = cluster_cap / tot
                for s in symbols:
                    if clusters[s] == cid:
                        excess += w[s] * (1 - scale)
                        w[s] *= scale
        if excess <= 1e-9:
            break
        # (3) rải phần dư cho mã còn dư địa (cả trần mã lẫn trần cụm)
        cl_head = {cid: max(0.0, cluster_cap - cluster_total(cid)) for cid in cset}
        eligible = [s for s in symbols
                    if w[s] < name_cap - 1e-9 and cl_head[clusters[s]] > 1e-9]
        if not eligible:
            return w, excess  # dư → tiền mặt
        add = excess / len(eligible)
        for s in eligible:
            w[s] += add
    cash = max(0.0, 1.0 - sum(w.values()))
    return w, cash


# ============================================================================
# Cấu trúc & dựng danh mục
# ============================================================================
@dataclass
class Position:
    symbol: str
    name: str = ""
    sector: str = ""
    cluster: int = 0
    weight: float = 0.0
    vol: Optional[float] = None
    price: Optional[float] = None
    val_stance: str = ""
    val_detail: str = ""
    cycle: str = ""
    n_flags: int = 0
    scenario: Optional[dict] = None
    error: str = ""


@dataclass
class Portfolio:
    symbols: List[str]
    positions: List[Position] = field(default_factory=list)
    cash: float = 0.0
    corr: pd.DataFrame = field(default_factory=pd.DataFrame)
    n_sessions: int = 0
    capital_trieu: Optional[float] = None
    # rủi ro danh mục
    hhi: float = 0.0
    eff_n: float = 0.0
    port_vol: Optional[float] = None
    wavg_vol: Optional[float] = None
    div_ratio: Optional[float] = None
    avg_corr_held: Optional[float] = None
    largest_cluster_w: float = 0.0
    largest_cluster_members: List[str] = field(default_factory=list)
    diversified: bool = True
    warnings: List[str] = field(default_factory=list)


def build_portfolio(symbols: List[str], capital_trieu: Optional[float] = None,
                    name_cap: float = 0.25, cluster_cap: float = 0.40,
                    corr_thresh: float = 0.6, corr_days: int = 400) -> Portfolio:
    symbols = [s.upper().strip() for s in symbols if s.strip()]
    pf = Portfolio(symbols=symbols, capital_trieu=capital_trieu)

    # 1. giá → tương quan + biến động
    corr, vol, n_sess = price_stats(symbols, days=corr_days)
    pf.corr, pf.n_sessions = corr, n_sess

    # 2. deep-dive từng mã (tên/ngành/định giá/chu kỳ/cờ/khung giá)
    sectors: Dict[str, str] = {}
    dds: Dict[str, object] = {}
    for s in symbols:
        try:
            dd = build(s, with_valuation=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("Deep-dive %s lỗi: %s", s, e)
            dd = None
        dds[s] = dd
        if dd is not None and not dd.error:
            sectors[s] = dd.sector or ""

    # 3. gom cụm + chia tỷ trọng
    clusters = cluster_positions(symbols, corr, sectors, corr_thresh=corr_thresh)
    weights, cash = size_equal_capped(symbols, clusters, name_cap=name_cap,
                                      cluster_cap=cluster_cap)
    pf.cash = cash

    # 4. dựng Position
    for s in symbols:
        dd = dds.get(s)
        pos = Position(symbol=s, cluster=clusters.get(s, 0), weight=weights.get(s, 0.0),
                       vol=float(vol[s]) if (not vol.empty and s in vol) else None)
        if dd is None or dd.error:
            pos.error = (dd.error if dd else "không dựng được deep-dive")
            pf.positions.append(pos)
            continue
        m = dd.metrics or {}
        pos.name = dd.name or s
        pos.sector = dd.sector or ""
        pos.price = (dd.info or {}).get("price")
        pos.val_stance = m.get("val_stance", "")
        pos.val_detail = m.get("val_stance_detail", "")
        pos.cycle = (m.get("cycle") or {}).get("chu_kỳ", "") if m.get("cycle") else ""
        pos.n_flags = len(dd.red_flags or [])
        pos.scenario = scenario_prices(dd)
        pf.positions.append(pos)

    _portfolio_risk(pf, vol)
    return pf


def _portfolio_risk(pf: Portfolio, vol: pd.Series) -> None:
    held = [p for p in pf.positions if p.weight > 1e-6]
    w = np.array([p.weight for p in held])
    if w.sum() <= 0:
        return
    # HHI & số vị thế hiệu dụng (trên phần đã đầu tư, chuẩn hóa)
    wn = w / w.sum()
    pf.hhi = float((wn ** 2).sum())
    pf.eff_n = 1.0 / pf.hhi if pf.hhi > 0 else 0.0

    # cụm lớn nhất
    cl_w: Dict[int, float] = {}
    for p in held:
        cl_w[p.cluster] = cl_w.get(p.cluster, 0.0) + p.weight
    if cl_w:
        big = max(cl_w, key=cl_w.get)
        pf.largest_cluster_w = cl_w[big]
        pf.largest_cluster_members = [p.symbol for p in held if p.cluster == big]

    # biến động danh mục vs bình quân (dùng corr + vol)
    syms = [p.symbol for p in held]
    if not pf.corr.empty and all(s in pf.corr.index for s in syms) and not vol.empty:
        v = np.array([vol.get(s, np.nan) for s in syms])
        if not np.isnan(v).any():
            C = pf.corr.loc[syms, syms].values
            cov = np.outer(v, v) * C
            pv = float(np.sqrt(wn @ cov @ wn))
            wav = float(wn @ v)
            pf.port_vol, pf.wavg_vol = pv, wav
            pf.div_ratio = wav / pv if pv > 0 else None
            # tương quan bình quân có trọng số (cặp)
            num = den = 0.0
            for i in range(len(syms)):
                for j in range(i + 1, len(syms)):
                    ww = wn[i] * wn[j]
                    num += ww * C[i, j]
                    den += ww
            pf.avg_corr_held = num / den if den > 0 else None

    # verdict đa dạng thật/giả
    warns = []
    if pf.largest_cluster_w >= 0.5 and len(pf.largest_cluster_members) >= 2:
        warns.append(
            f"Cụm lớn nhất ({'+'.join(pf.largest_cluster_members)}) chiếm "
            f"{pf.largest_cluster_w*100:.0f}% vốn đầu tư — cùng rủi ro hệ thống, KHÔNG phải đa "
            f"dạng thật. Coi như MỘT cược lớn.")
    if pf.avg_corr_held is not None and pf.avg_corr_held >= 0.5:
        warns.append(
            f"Tương quan bình quân giữa các vị thế {pf.avg_corr_held:.2f} (cao) — danh mục dễ "
            f"cùng lên/xuống, hiệu quả phân tán rủi ro thấp.")
    if pf.div_ratio is not None and pf.div_ratio < 1.15:
        warns.append(
            f"Hệ số phân tán {pf.div_ratio:.2f} (~1 nghĩa là gần như không giảm được rủi ro nhờ "
            f"đa dạng) — các mã dao động gần như đồng pha.")
    pf.diversified = not warns
    pf.warnings = warns


# ============================================================================
# Vùng giá vào/thoát từ khung P/B kịch bản
# ============================================================================
def _entry_exit(pos: Position) -> Tuple[str, str]:
    sp = pos.scenario
    if not sp or not sp.get("price") or not sp.get("base"):
        return ("—", "—")
    price, base, bull = sp["price"], sp["base"], sp.get("bull")
    tgt = sp.get("target")
    # vào: mua dưới vùng cơ sở (biên an toàn)
    if price <= base:
        entry = f"Giá {_px(price)} đã Ở/DƯỚI vùng cơ sở {_px(base)} → vùng vào hợp lý (biên an toàn)."
    elif price <= base * 1.12:
        entry = f"Giá {_px(price)} gần vùng cơ sở {_px(base)} → có thể vào từng phần."
    else:
        entry = f"Giá {_px(price)} TRÊN vùng cơ sở {_px(base)} → chờ chỉnh về ≤ {_px(base)} rồi vào."
    if pos.cycle == "ĐỈNH":
        entry += " ⚠️ Lãi ở ĐỈNH chu kỳ — thận trọng, đừng vào vì P/E thấp ảo."
    # thoát: quanh bull / mục tiêu Vietcap
    ex = []
    if bull:
        ex.append(f"chốt dần quanh {_px(bull)}")
    if tgt:
        ex.append(f"mục tiêu Vietcap {_px(tgt)}")
    exit_ = ("Cân nhắc " + " hoặc ".join(ex) + "; thoát sớm nếu chạm tín hiệu cảnh báo.") if ex else "—"
    return (entry, exit_)


# ============================================================================
# Render HTML
# ============================================================================
def _corr_cell(v: float) -> str:
    if pd.isna(v):
        return "<td>—</td>"
    if v >= 0.6:
        bg = "#f9d5d5"
    elif v >= 0.3:
        bg = "#fdeccf"
    else:
        bg = "#d8efdc"
    fg = "#111"
    return f"<td style='background:{bg};color:{fg};text-align:center'>{v:.2f}</td>"


def render_portfolio(pf: Portfolio) -> str:
    today = _dt.date.today().isoformat()
    held = [p for p in pf.positions if p.weight > 1e-6]
    cap = pf.capital_trieu
    P: List[str] = []
    P.append("<button class='toggle' id='tg'>🌙 Tối</button>")
    P.append("<div class='wrap'>")
    P.append(f"<h1>Danh mục & kích thước vị thế</h1>")
    n_clusters = len(set(p.cluster for p in held))
    P.append(f"<div class='sub'>{len(held)} mã · {n_clusters} cụm rủi ro · "
             f"{pf.n_sessions} phiên tương quan · Lập {today}"
             + (f" · Vốn {cap:.0f} triệu đ" if cap else "")
             + ". KHÔNG phải khuyến nghị — trần & tương quan là kiểm soát rủi ro, không bảo "
             "chứng lợi nhuận.</div>")

    # 1. Cảnh báo đa dạng hóa (điểm cốt lõi)
    P.append("<h2>1. Danh mục này có đa dạng THẬT không?</h2>")
    if pf.warnings:
        P.append("<div class='card' style='border-left:4px solid #d33'>"
                 "<b>⚠️ ĐA DẠNG HÓA GIẢ — cần lưu ý:</b><ul>"
                 + "".join(f"<li>{html.escape(w)}</li>" for w in pf.warnings)
                 + "</ul></div>")
    else:
        P.append("<div class='card' style='border-left:4px solid #2a2'>"
                 "✅ Các vị thế phân tán hợp lý (tương quan thấp, không cụm nào áp đảo).</div>")
    # bảng cụm
    cl_map: Dict[int, List[str]] = {}
    for p in held:
        cl_map.setdefault(p.cluster, []).append(p.symbol)
    cl_rows = ""
    for cid, mem in sorted(cl_map.items()):
        cw = sum(p.weight for p in held if p.cluster == cid)
        sec = next((p.sector for p in held if p.cluster == cid and p.sector), "")
        tag = "MỘT cược (không đa dạng nội bộ)" if len(mem) >= 2 else "độc lập"
        cl_rows += (f"<tr><td>Cụm {cid+1}</td><td>{'+'.join(mem)}</td>"
                    f"<td>{html.escape(sec)}</td><td>{cw*100:.0f}%</td><td class='note'>{tag}</td></tr>")
    P.append("<div class='tblwrap'><table><thead><tr><th>Cụm</th><th>Mã</th><th>Ngành</th>"
             "<th>% vốn</th><th>Ghi chú</th></tr></thead><tbody>" + cl_rows + "</tbody></table></div>")
    P.append("<div class='explain'><span class='lbl'>Vì sao gom cụm</span>"
             "<p class='line'>Hai mã vào cùng cụm nếu tương quan giá cao (≥0.6) HOẶC cùng ngành — "
             "tức chịu chung một rủi ro hệ thống (chu kỳ/chính sách/catalyst). Giữ nhiều mã cùng "
             "cụm KHÔNG giảm rủi ro như tưởng: chúng lên/xuống cùng nhau. Trần cụm buộc tổng vốn "
             "vào một cụm không vượt ngưỡng — phần dư để tiền mặt hoặc dành cho cụm khác.</p></div>")

    # 2. Tỷ trọng đề xuất
    P.append("<h2>2. Tỷ trọng đề xuất (chia đều + trần mã/cụm)</h2>")
    rows = ""
    for p in sorted(held, key=lambda x: -x.weight):
        money = ""
        if cap and p.price:
            amt = cap * p.weight  # triệu đồng
            shares = int(round((amt * 1e6) / p.price / 100.0)) * 100  # làm tròn lô 100
            money = f"<td>{amt:.1f} tr</td><td>{shares:,} cp</td>"
        elif cap:
            money = "<td>—</td><td>—</td>"
        stance = p.val_detail or p.val_stance or "—"
        cyc = f" · {p.cycle}" if p.cycle else ""
        flags = f"{p.n_flags} cờ" if p.n_flags else "sạch"
        rows += (f"<tr><td><b>{p.symbol}</b></td><td>{html.escape(p.name)}</td>"
                 f"<td>Cụm {p.cluster+1}</td><td><b>{p.weight*100:.1f}%</b></td>{money}"
                 f"<td class='note'>{html.escape(stance)}{cyc}; {flags}</td></tr>")
    if pf.cash > 1e-6:
        money = f"<td>{cap*pf.cash:.1f} tr</td><td>—</td>" if cap else ""
        rows += (f"<tr style='font-weight:600'><td>💵 Tiền mặt</td><td>—</td><td>—</td>"
                 f"<td>{pf.cash*100:.1f}%</td>{money}"
                 f"<td class='note'>phần trần cắt ra — chờ cơ hội / mã ngoài cụm</td></tr>")
    money_hdr = "<th>Vốn</th><th>Số CP</th>" if cap else ""
    P.append("<div class='tblwrap'><table><thead><tr><th>Mã</th><th>Tên</th><th>Cụm</th>"
             f"<th>Tỷ trọng</th>{money_hdr}<th>Định giá · chu kỳ · cờ</th></tr></thead><tbody>"
             + rows + "</tbody></table></div>")
    if cap:
        P.append(f"<div class='explain'><span class='lbl'>Số cổ phiếu</span><p class='line'>Làm "
                 f"tròn lô 100, tính từ giá ẢNH CHỤP VCI (không real-time) — lấy giá LIVE để tính "
                 f"lại trước khi đặt lệnh.</p></div>")

    # 3. Ma trận tương quan
    if not pf.corr.empty:
        syms = [p.symbol for p in held if p.symbol in pf.corr.index]
        if len(syms) >= 2:
            P.append("<h2>3. Ma trận tương quan (return ngày)</h2>")
            hdr = "".join(f"<th>{s}</th>" for s in syms)
            body = ""
            for a in syms:
                cells = "".join(_corr_cell(pf.corr.at[a, b]) if a != b
                                else "<td style='background:#e8e8e8;text-align:center'>1.00</td>"
                                for b in syms)
                body += f"<tr><th>{a}</th>{cells}</tr>"
            P.append(f"<div class='tblwrap'><table><thead><tr><th></th>{hdr}</tr></thead><tbody>"
                     + body + "</tbody></table></div>")
            P.append("<div class='explain'><span class='lbl'>Đọc bảng</span><p class='line'>Đỏ = "
                     "tương quan cao (≥0.6, cùng lên xuống, ít tác dụng phân tán); vàng = vừa; "
                     "xanh = thấp (đa dạng thật). Càng nhiều ô đỏ, danh mục càng gần MỘT cược.</p></div>")

    # 4. Vùng giá vào/thoát
    P.append("<h2>4. Vùng giá vào / thoát (khung P/B kịch bản)</h2>")
    ee = ""
    for p in sorted(held, key=lambda x: -x.weight):
        entry, exit_ = _entry_exit(p)
        ee += (f"<tr><td><b>{p.symbol}</b></td><td class='note'>{html.escape(entry)}</td>"
               f"<td class='note'>{html.escape(exit_)}</td></tr>")
    P.append("<div class='tblwrap'><table><thead><tr><th>Mã</th><th>Vùng VÀO</th>"
             "<th>Vùng THOÁT</th></tr></thead><tbody>" + ee + "</tbody></table></div>")
    P.append("<div class='explain'><span class='lbl'>Cơ sở vùng giá</span><p class='line'>Neo vào "
             "khung P/B lịch sử (bear/base/bull) như báo cáo quyết định: vào dưới vùng cơ sở để có "
             "biên an toàn, chốt dần quanh vùng cao/ mục tiêu Vietcap. KHÔNG phải dự báo — là mốc "
             "tham chiếu; lấy giá LIVE để quyết.</p></div>")

    # 5. Rủi ro danh mục
    P.append("<h2>5. Thước đo rủi ro danh mục</h2>")
    chips = [f"<span class='chip'>Số vị thế hiệu dụng ~{pf.eff_n:.1f}/{len(held)}</span>",
             f"<span class='chip'>Cụm lớn nhất {pf.largest_cluster_w*100:.0f}%</span>"]
    if pf.avg_corr_held is not None:
        chips.append(f"<span class='chip'>Tương quan bình quân {pf.avg_corr_held:.2f}</span>")
    if pf.port_vol is not None:
        chips.append(f"<span class='chip'>Biến động DM {pf.port_vol*100:.0f}%/năm "
                     f"(bình quân mã {pf.wavg_vol*100:.0f}%)</span>")
    if pf.div_ratio is not None:
        chips.append(f"<span class='chip'>Hệ số phân tán {pf.div_ratio:.2f}</span>")
    P.append("<div class='stats'>" + "".join(chips) + "</div>")
    P.append("<div class='explain'><span class='lbl'>Ý nghĩa</span><p class='line'>Số vị thế hiệu "
             "dụng thấp hơn số mã = vốn dồn vào vài mã. Biến động danh mục < bình quân từng mã nhờ "
             "đa dạng; nếu XẤP XỈ bằng (hệ số phân tán ~1) thì đa dạng gần như vô ích vì các mã "
             "đồng pha. Đây là lý do trần cụm quan trọng hơn số lượng mã.</p></div>")

    P.append("<div class='foot'>Danh mục sinh tự động từ dữ liệu đã công bố. Tỷ trọng là khung "
             "kiểm soát rủi ro (chia đều + trần), KHÔNG tối ưu lợi nhuận và KHÔNG phải khuyến nghị "
             "mua/bán. Đầu tư cổ phiếu có thể mất vốn — tự đánh giá và/hoặc hỏi tư vấn được cấp "
             "phép trước khi xuống tiền.</div>")
    P.append("</div>")
    return _html_shell("Danh mục & vị thế", "".join(P))


def _print_summary(pf: Portfolio) -> None:
    held = [p for p in pf.positions if p.weight > 1e-6]
    print(f"\n{'='*64}\nDANH MỤC {len(held)} mã · {pf.n_sessions} phiên tương quan")
    print(f"{'='*64}")
    for p in sorted(held, key=lambda x: -x.weight):
        line = f"  {p.symbol:5} {p.weight*100:5.1f}%  cụm {p.cluster+1}"
        if p.cycle:
            line += f"  [{p.cycle}]"
        if p.val_stance:
            line += f"  {p.val_stance}"
        if p.error:
            line += f"  (LỖI: {p.error})"
        print(line)
    if pf.cash > 1e-6:
        print(f"  {'TIỀN':5} {pf.cash*100:5.1f}%  (trần cắt ra)")
    print(f"\n  Cụm lớn nhất: {'+'.join(pf.largest_cluster_members)} = {pf.largest_cluster_w*100:.0f}%")
    if pf.avg_corr_held is not None:
        print(f"  Tương quan bình quân: {pf.avg_corr_held:.2f} | hệ số phân tán: "
              f"{pf.div_ratio:.2f}" if pf.div_ratio else "")
    print("  " + ("✅ ĐA DẠNG hợp lý" if pf.diversified else "⚠️ ĐA DẠNG GIẢ:"))
    for w in pf.warnings:
        print(f"    ⚠ {w}")


def main() -> None:
    ensure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="Báo cáo danh mục + kích thước vị thế.")
    ap.add_argument("symbols", help="Danh sách mã, phân tách bằng dấu phẩy (vd LCG,HHV,VCG)")
    ap.add_argument("--capital", type=float, default=None, help="Tổng vốn (triệu đồng) để ra tiền/mã")
    ap.add_argument("--name-cap", type=float, default=0.25, help="Trần tỷ trọng mỗi mã (mặc định 0.25)")
    ap.add_argument("--cluster-cap", type=float, default=0.40, help="Trần tỷ trọng mỗi cụm (0.40)")
    ap.add_argument("--corr", type=float, default=0.6, help="Ngưỡng tương quan gom cụm (0.6)")
    ap.add_argument("--corr-days", type=int, default=400, help="Số ngày lịch lấy giá (400 ~ 250 phiên)")
    ap.add_argument("--out", default=REPORTS_DIR)
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()
    syms = [s for s in args.symbols.replace(";", ",").split(",") if s.strip()]
    print(f"⏳ Dựng danh mục {len(syms)} mã: {', '.join(syms)} ...")
    pf = build_portfolio(syms, capital_trieu=args.capital, name_cap=args.name_cap,
                         cluster_cap=args.cluster_cap, corr_thresh=args.corr,
                         corr_days=args.corr_days)
    _print_summary(pf)
    if not args.no_html:
        os.makedirs(args.out, exist_ok=True)
        p = os.path.join(args.out, "danhmuc_" + "_".join(s.upper() for s in syms[:5]) + ".html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(render_portfolio(pf))
        print(f"\n✅ HTML: {p}")


if __name__ == "__main__":
    main()
