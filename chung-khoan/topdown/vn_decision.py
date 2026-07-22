# -*- coding: utf-8 -*-
"""
BÁO CÁO QUYẾT ĐỊNH ĐẦU TƯ — chân trời cố định (mặc định 2 năm).

Trên nền báo cáo forensic (vn_deepdive), thêm lớp RA QUYẾT ĐỊNH:
  1. Khung giá tham chiếu (bear/base/bull) — NEO vào bội số định giá lịch sử của chính mã +
     giá mục tiêu Vietcap (có nguồn). KHÔNG bịa dự báo; ghi rõ giả định.
  2. Kế hoạch theo dõi định kỳ — tín hiệu XÁC NHẬN (giữ) vs tín hiệu CẢNH BÁO (xem lại/thoát),
     suy từ chính cờ đỏ + điểm cộng + mấu chốt của báo cáo.
  3. Điều kiện thoát sau chân trời.

Triết lý: mã chu kỳ (thép/BĐS) → NEO THEO P/B (P/E méo khi lợi nhuận dao động). Luôn nói rõ
đây là KHUNG THAM CHIẾU theo bội số, không phải lời hứa; quyết định & rủi ro là của nhà đầu tư.

Chạy:  python vn_decision.py HPG            # -> reports/HPG_quyetdinh.html
       python vn_decision.py PVS --years 2
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import os
from typing import Dict, List, Optional

from vn_fundamentals import ensure_utf8_stdout
from vn_deepdive_report import build, _px, _RATING_VI, _CSS, _TOGGLE_JS, _html_shell, _md_inline
from vn_deepdive import DeepDive, _t

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


# ============================================================================
# Khung giá kịch bản — neo vào P/B lịch sử + mục tiêu Vietcap
# ============================================================================
def scenario_prices(dd: DeepDive) -> Optional[Dict[str, object]]:
    m = dd.metrics
    price = (dd.info or {}).get("price")
    bvps = m.get("bvps")
    pb_now = m.get("pb_now"); pb_lo = m.get("pb_lo"); pb_med = m.get("pb_med"); pb_hi = m.get("pb_hi")
    if not (price and bvps and pb_lo and pb_med):
        return None
    tgt = (dd.info or {}).get("target")

    def ret(p):
        return (p / price - 1) if price else None

    # bear: định giá về vùng thấp lịch sử (P/B_lo), giữ giá trị sổ sách hiện tại
    bear = pb_lo * bvps
    # base: định giá lại về trung vị lịch sử
    base = pb_med * bvps
    # bull: về vùng cao lịch sử (nếu có) — phản ánh chu kỳ lên + công suất mới
    bull = (pb_hi or pb_med * 1.3) * bvps
    return {
        "price": price, "target": tgt, "pb_now": pb_now, "bvps": bvps,
        "bear": bear, "bear_ret": ret(bear), "bear_pb": pb_lo,
        "base": base, "base_ret": ret(base), "base_pb": pb_med,
        "bull": bull, "bull_ret": ret(bull), "bull_pb": (pb_hi or pb_med * 1.3),
        "target_ret": ret(tgt) if tgt else None,
    }


# ============================================================================
# Kế hoạch theo dõi — tín hiệu xác nhận vs cảnh báo (suy từ báo cáo)
# ============================================================================
def monitoring_plan(dd: DeepDive) -> Dict[str, List[str]]:
    m = dd.metrics
    confirm: List[str] = []   # giữ/gia tăng
    warn: List[str] = []      # xem lại/thoát

    # XÁC NHẬN — điều kiện cho thấy luận điểm đang đúng
    if m.get("cfo_ni_3y") is not None and m["cfo_ni_3y"] >= 0.8:
        confirm.append("Dòng tiền kinh doanh (CFO) tiếp tục bám sát lợi nhuận (≥80% lãi ròng).")
    confirm.append("Biên lợi nhuận gộp giữ hoặc mở rộng qua các quý (không bị bào mòn).")
    if m.get("rev_g") is not None and m["rev_g"] > 0:
        confirm.append("Doanh thu duy trì tăng trưởng dương so cùng kỳ.")
    if m.get("val_stance") == "rẻ":
        confirm.append("Định giá được thị trường nhận ra dần (P/B nhích về trung vị lịch sử).")

    # XÁC NHẬN / CẢNH BÁO theo CHU KỲ biên (mid-cycle) — cốt lõi với DN chu kỳ
    cyc = m.get("cycle")
    if cyc:
        state = cyc.get("chu_kỳ")
        if state == "ĐÁY":
            confirm.append("Biên lợi nhuận thực sự HỒI PHỤC về mid-cycle qua vài quý — ĐIỀU KIỆN "
                           "CẦN để 'đáy chu kỳ' thành cơ hội. (Backtest 2021-24: mua đáy-margin khi "
                           "CHƯA thấy hồi thường THUA ~2 năm — đợi bằng chứng hồi, đừng đoán.)")
        elif state == "ĐỈNH":
            warn.append("Biên lợi nhuận CO về mid-cycle (lãi hiện ở ĐỈNH, khó duy trì) — lợi nhuận "
                        "và P/E spot sẽ xấu đi dù giá không đổi.")

    # CẢNH BÁO — điều kiện nên xem lại / cân nhắc thoát (rút từ cờ + mấu chốt)
    jl = " ".join(dd.red_flags).lower()
    if "cfo" in jl or "không ra tiền" in jl or (m.get("cfo_ni_3y") or 1) < 0.6:
        warn.append("CFO chuyển âm hoặc tụt sâu dưới lợi nhuận nhiều quý liền (lãi không ra tiền).")
    if "bán chịu" in jl or "phải thu" in jl:
        warn.append("Phải thu khách hàng / số ngày thu tiền (DSO) tiếp tục phình mạnh.")
    if "tồn kho" in jl or "chu kỳ tiền mặt" in jl:
        warn.append("Tồn kho ứ đọng, chu kỳ tiền mặt kéo dài thêm mà doanh số không theo kịp.")
    if m.get("de") is not None and m["de"] > 1:
        warn.append("Đòn bẩy (D/E) tăng mạnh hoặc độ phủ lãi vay tụt dưới 2 lần.")
    if m.get("funding_depends"):
        warn.append("Khó huy động vốn / lãi suất tăng khiến chi phí vốn đội lên.")
    # rủi ro ngành đặc thù
    sec = (dd.sector or "").lower()
    if "thép" in sec or "tài nguyên" in sec or "nguyên vật liệu" in sec:
        warn.append("Giá thép thế giới lao dốc hoặc nhu cầu xây dựng/BĐS chững (rủi ro chu kỳ).")
    elif "dầu" in sec:
        warn.append("Giá dầu giảm sâu kéo tụt biên lợi nhuận (rủi ro chu kỳ hàng hóa).")
    elif "bất động sản" in sec:
        warn.append("Thị trường BĐS đóng băng / tín dụng siết làm chậm bán hàng và thu tiền.")
    if not warn:
        warn.append("Bất kỳ cờ đỏ forensic mới nào xuất hiện ở các kỳ báo cáo sau.")
    return {"confirm": confirm, "warn": warn}


# ============================================================================
# Render HTML decision memo
# ============================================================================
def render_decision(dd: DeepDive, years: int = 2) -> str:
    today = _dt.date.today().isoformat()
    title = f"{dd.symbol}" + (f" — {dd.name}" if dd.name and dd.name != dd.symbol else "")
    i = dd.info or {}
    sp = scenario_prices(dd)
    plan = monitoring_plan(dd)

    P: List[str] = []
    P.append("<button class='toggle' id='tg'>🌙 Tối</button>")
    P.append("<div class='wrap'>")
    P.append(f"<h1>Báo cáo quyết định: {html.escape(title)}</h1>")
    P.append(f"<div class='sub'>Chân trời {years} năm · Lập ngày {today} · Nguồn: BCTC VCI + "
             f"khuyến nghị Vietcap. Không phải khuyến nghị mua/bán — quyết định &amp; rủi ro là của "
             f"nhà đầu tư.</div>")

    # khuyến nghị + giá
    chips = []
    if i.get("price") is not None:
        chips.append(f"<span class='chip'>Giá {_px(i['price'])}</span>")
    if i.get("rating"):
        r = _RATING_VI.get(str(i["rating"]).upper(), str(i["rating"]))
        up = i.get("upside")
        cls = ("b-red" if str(i["rating"]).upper() in ("SELL", "U-PF") else
               "b-green" if str(i["rating"]).upper() in ("BUY", "O-PF") else "b-amber")
        upt = f" {up*100:+.0f}%" if isinstance(up, (int, float)) else ""
        chips.append(f"<span class='chip badge {cls}'>Vietcap: {html.escape(r)}"
                     f" · MT {_px(i.get('target'))}{upt}</span>")
    if chips:
        P.append("<div class='stats'>" + "".join(chips) + "</div>")

    # 1. Luận điểm (tái dùng)
    if dd.thesis:
        P.append("<h2>1. Vì sao chọn mã này</h2>")
        P.append(f"<div class='card thesis'>{html.escape(dd.thesis)}</div>")
        P.append("<div class='bullbear'>")
        P.append("<div class='bb bb-bull'><h4>✅ Điểm hấp dẫn</h4><ul>"
                 + "".join(f"<li>{html.escape(b)}</li>" for b in dd.bull) + "</ul></div>")
        P.append("<div class='bb bb-bear'><h4>⚠️ Rủi ro</h4><ul>"
                 + "".join(f"<li>{html.escape(b)}</li>" for b in (dd.bear or ['Không có cờ đỏ.']))
                 + "</ul></div>")
        P.append("</div>")

    # 2. Khung giá tham chiếu
    P.append(f"<h2>2. Khung giá tham chiếu ({years} năm)</h2>")
    # Cảnh báo CHU KỲ trước khi đọc khung giá — chống mua vì P/E thấp ẢO (đỉnh) / bỏ lỡ (đáy)
    cyc = dd.metrics.get("cycle")
    if cyc and cyc.get("pe_spot") and cyc.get("pe_chuẩn"):
        st = cyc.get("chu_kỳ"); pes, pen = cyc["pe_spot"], cyc["pe_chuẩn"]
        bh, bm = (cyc.get("biên_hiện_tại") or 0) * 100, (cyc.get("biên_mid") or 0) * 100
        if st == "ĐỈNH" and pen > pes * 1.15:
            P.append(f"<div class='card note'>⚠️ <b>Cảnh báo chu kỳ — lãi đang ở ĐỈNH biên "
                     f"({bh:.1f}% vs mid-cycle {bm:.1f}%).</b> P/E spot {pes} trông rẻ nhưng là ẢO: "
                     f"chuẩn hóa về mid-cycle P/E thực ~{pen}. <b>Đừng mua chỉ vì P/E thấp</b> — dùng "
                     f"khung P/B bên dưới và chờ xác nhận biên bền, vì lợi nhuận đỉnh khó duy trì.</div>")
        elif st == "ĐÁY" and pen < pes * 0.85:
            P.append(f"<div class='card note'>🔄 <b>Đang ở ĐÁY chu kỳ biên "
                     f"({bh:.1f}% vs mid-cycle {bm:.1f}%).</b> P/E spot {pes} bị lãi đáy thổi cao; "
                     f"chuẩn hóa mid-cycle P/E ~{pen} — rẻ hơn vẻ ngoài NẾU biên hồi phục. "
                     f"⚠️ <b>NHƯNG 'đáy' KHÔNG phải lý do mua:</b> backtest 2021-24 cho thấy mua "
                     f"mã đáy-margin chờ hồi phục thường THUA ~2 năm, và lọc chất lượng KHÔNG cứu "
                     f"được. Chỉ vào khi có BẰNG CHỨNG biên đang hồi thật (vài quý), đừng đoán 'sẽ hồi'.</div>")
    if sp:
        rows = [
            ("🔴 Bi quan (bear)", sp["bear"], sp["bear_ret"], sp["bear_pb"],
             "Chu kỳ ngành xấu, định giá về vùng THẤP lịch sử"),
            ("⚪ Cơ sở (base)", sp["base"], sp["base_ret"], sp["base_pb"],
             "Định giá lại về TRUNG VỊ lịch sử khi kết quả bình thường hóa"),
            ("🟢 Lạc quan (bull)", sp["bull"], sp["bull_ret"], sp["bull_pb"],
             "Chu kỳ lên + công suất/lợi nhuận mới, định giá về vùng CAO"),
        ]
        tr = ""
        for nm, px, rt, pb, note in rows:
            rtc = ("+" if (rt or 0) >= 0 else "")
            tr += (f"<tr><td>{nm}</td><td>{_px(px)}</td>"
                   f"<td>{rtc}{rt*100:.0f}%</td><td>P/B {pb:.2f}</td>"
                   f"<td class='note'>{note}</td></tr>")
        if sp.get("target"):
            tr += (f"<tr style='font-weight:600'><td>🎯 Mục tiêu Vietcap</td><td>{_px(sp['target'])}</td>"
                   f"<td>+{sp['target_ret']*100:.0f}%</td><td>—</td>"
                   f"<td class='note'>Quan điểm giới phân tích (có nguồn)</td></tr>")
        P.append("<div class='tblwrap'><table><thead><tr><th>Kịch bản</th><th>Giá tham chiếu</th>"
                 "<th>Lợi nhuận</th><th>Bội số</th><th>Điều kiện</th></tr></thead><tbody>"
                 + tr + "</tbody></table></div>")
        P.append(f"<div class='explain'><span class='lbl'>Cách đọc khung giá</span>"
                 f"<p class='line'>Các mốc NEO vào dải P/B lịch sử của chính {html.escape(dd.symbol)} "
                 f"(hiện {sp['pb_now']:.2f}, giá trị sổ sách ~{_px(sp['bvps'])}/cp) áp lên giá trị sổ "
                 f"sách hiện tại — dùng P/B vì với mã chu kỳ, P/E méo khi lợi nhuận dao động. Đây là "
                 f"KHUNG THAM CHIẾU theo bội số, KHÔNG phải dự báo chắc chắn; giá trị sổ sách còn tăng "
                 f"theo lợi nhuận giữ lại nên vùng giá thực có thể cao hơn.</p>"
                 f"<p class='line'>⚠️ <b>% lợi nhuận tính từ giá {_px(sp['price'])} — là ẢNH CHỤP VCI "
                 f"(không real-time).</b> Giá mục tiêu (cột giữa) không đổi theo giá thị trường; nhưng "
                 f"% lời/lỗ đổi theo điểm mua thực. Lấy giá LIVE trên bảng để tính lại trước khi hành động.</p></div>")
    else:
        P.append("<div class='card note'>Không đủ dữ liệu định giá lịch sử để dựng khung giá.</div>")

    # 3. Ba kịch bản điều kiện
    if dd.scenarios:
        P.append("<h2>3. Điều kiện của mỗi kịch bản</h2>")
        P.append("<div class='card'>" + "".join(f"<p class='line'>{_md_inline(s)}</p>"
                                                 for s in dd.scenarios) + "</div>")

    # 4. Kế hoạch theo dõi
    P.append(f"<h2>4. Kế hoạch theo dõi trong {years} năm</h2>")
    P.append("<div class='bullbear'>")
    P.append("<div class='bb bb-bull'><h4>✅ Tín hiệu XÁC NHẬN (giữ / gia tăng)</h4><ul>"
             + "".join(f"<li>{html.escape(c)}</li>" for c in plan["confirm"]) + "</ul></div>")
    P.append("<div class='bb bb-bear'><h4>🚩 Tín hiệu CẢNH BÁO (xem lại / cân nhắc thoát)</h4><ul>"
             + "".join(f"<li>{html.escape(w)}</li>" for w in plan["warn"]) + "</ul></div>")
    P.append("</div>")
    P.append("<div class='explain'><span class='lbl'>Nhịp rà soát</span>"
             "<p class='line'>Chạy lại báo cáo này mỗi quý khi doanh nghiệp công bố BCTC (và khi có "
             "tin lớn). So các tín hiệu trên với số mới: nghiêng về XÁC NHẬN thì giữ theo kế hoạch; "
             "chạm nhiều tín hiệu CẢNH BÁO thì xem lại luận điểm, đừng chờ tới hạn mới quyết.</p></div>")

    # 5. Điều kiện thoát
    P.append(f"<h2>5. Điều kiện thoát sau {years} năm</h2>")
    P.append("<div class='card'><ul>"
             "<li><b>Kịch bản cơ sở/lạc quan xảy ra</b> → chốt lời quanh vùng giá tham chiếu, "
             "hoặc gia hạn nếu luận điểm còn nguyên và định giá chưa đắt.</li>"
             "<li><b>Kịch bản bi quan xảy ra</b> → đây là lúc kỷ luật: nếu các tín hiệu cảnh báo "
             "thành hiện thực, cân nhắc thoát sớm để bảo toàn vốn thay vì gồng tới hạn.</li>"
             "<li><b>Ràng buộc rút vốn cứng ở mốc 2 năm</b> có nghĩa: nếu đúng lúc đó thị trường/chu "
             "kỳ đang xấu, có thể phải bán ở giá thấp — đây là rủi ro gắn liền với kỳ vọng lợi nhuận cao.</li>"
             "</ul></div>")

    P.append("<div class='foot'>Báo cáo quyết định sinh tự động từ dữ liệu đã công bố. Khung giá là "
             "tham chiếu theo bội số lịch sử + mục tiêu Vietcap (có nguồn), KHÔNG phải cam kết lợi "
             "nhuận. Đầu tư cổ phiếu có thể mất vốn. Đây KHÔNG phải khuyến nghị mua/bán — hãy tự "
             "đánh giá và/hoặc hỏi tư vấn được cấp phép trước khi xuống tiền.</div>")
    P.append("</div>")
    return _html_shell(f"Quyết định: {title}", "".join(P))


def main() -> None:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser(description="Báo cáo quyết định đầu tư (khung giá + kế hoạch theo dõi).")
    ap.add_argument("symbol")
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--out", default=REPORTS_DIR)
    args = ap.parse_args()
    sym = args.symbol.upper().strip()
    print(f"⏳ Dựng báo cáo quyết định {sym} (chân trời {args.years} năm) ...")
    dd = build(sym, with_valuation=True)
    if dd.error:
        print("❌", dd.error); return
    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, f"{sym}_quyetdinh.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(render_decision(dd, years=args.years))
    print(f"✅ {p}")
    sp = scenario_prices(dd)
    if sp:
        print(f"   Giá {_px(sp['price'])} | bear {_px(sp['bear'])} ({sp['bear_ret']*100:+.0f}%) | "
              f"base {_px(sp['base'])} ({sp['base_ret']*100:+.0f}%) | "
              f"bull {_px(sp['bull'])} ({sp['bull_ret']*100:+.0f}%) | "
              f"Vietcap MT {_px(sp['target'])}")


if __name__ == "__main__":
    main()
