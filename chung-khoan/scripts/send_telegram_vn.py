# -*- coding: utf-8 -*-
"""
Gửi digest phân tích chứng khoán VN sang Telegram (kênh chung của repo).

Đọc báo cáo + bản tin dịch chuyển giá do pipeline tạo, dựng một bản tin gọn tiếng Việt,
gắn nhãn rõ "PHÂN TÍCH CHỨNG KHOÁN VN" để tách với nhóm hàng hóa / ngân hàng, rồi gửi
qua Telegram Bot API. Dùng secret sẵn có của repo: TELEGRAM_TOKEN + TELEGRAM_CHAT.
"""

import os
import re
import sys
import glob
import time
import html
import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT", "").strip()
REPORTS = os.environ.get("REPORTS_DIR", "reports")


def run_url():
    s = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    r = os.environ.get("GITHUB_REPOSITORY", "")
    rid = os.environ.get("GITHUB_RUN_ID", "")
    return f"{s}/{r}/actions/runs/{rid}" if r and rid else ""


def read_latest_report():
    files = sorted(glob.glob(os.path.join(REPORTS, "report_*.md")))
    if not files:
        files = sorted(glob.glob(os.path.join(REPORTS, "*.md")))
        files = [f for f in files if "dich-chuyen" not in f]
    return files[-1] if files else None


def extract_summary(md_path):
    """Lấy khối 'Summary' (các dòng 1 mã 1 tín hiệu) từ báo cáo."""
    if not md_path or not os.path.exists(md_path):
        return []
    txt = open(md_path, encoding="utf-8").read()
    lines = txt.splitlines()
    head = ""
    for ln in lines:
        if ln.strip().startswith(">") and ("Buy" in ln or "Analyzed" in ln or "phân tích" in ln):
            head = ln.strip("> ").strip()
            break
    out = []
    grab = False
    for ln in lines:
        if re.match(r"^#+\s*.*Summary", ln) or "分析结果摘要" in ln or "Tóm tắt" in ln:
            grab = True
            continue
        if grab:
            if ln.startswith("---") or re.match(r"^#+\s", ln):
                break
            s = ln.strip()
            if s:
                out.append(s)
    return [head] + out if head else out


def extract_movers(md_path, section, top=5):
    """Lấy vài dòng từ 1 mục của bản tin dịch chuyển giá."""
    if not md_path or not os.path.exists(md_path):
        return []
    txt = open(md_path, encoding="utf-8").read()
    blocks = re.split(r"\n##\s+", txt)
    rows = []
    for b in blocks:
        if section in b:
            for ln in b.splitlines():
                m = re.match(r"\|\s*([A-Z0-9]{2,4})\s*\|\s*([^|]+)\|[^|]*\|\s*([\d,]+)\s*\|\s*([+-][\d.]+%)", ln)
                if m:
                    rows.append(f"{m.group(1)} {m.group(4).strip()}")
                if len(rows) >= top:
                    break
    return rows


def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    # chia nhỏ dưới 4096 ký tự
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            parts.append(cur); cur = ""
        cur += line + "\n"
    if cur:
        parts.append(cur)
    ok = True
    for i, p in enumerate(parts):
        r = requests.post(url, data={"chat_id": CHAT, "text": p,
                                     "parse_mode": "HTML", "disable_web_page_preview": "true"}, timeout=30)
        if r.status_code != 200:
            print(f"[telegram] lỗi phần {i+1}: {r.status_code} {r.text[:200]}", file=sys.stderr)
            ok = False
        time.sleep(0.5)
    return ok


def main():
    if not TOKEN or not CHAT:
        print("[telegram] Thiếu TELEGRAM_TOKEN/TELEGRAM_CHAT — bỏ qua gửi.", file=sys.stderr)
        return 0
    rep = read_latest_report()
    movers_md = os.path.join(REPORTS, "dich-chuyen-gia.md")
    summary = extract_summary(rep)
    gain = extract_movers(movers_md, "Tăng mạnh nhất")
    lose = extract_movers(movers_md, "Giảm mạnh nhất")
    surge = extract_movers(movers_md, "Bùng khối lượng")

    from datetime import datetime
    parts = [f"📈 <b>PHÂN TÍCH CHỨNG KHOÁN VN</b> — {datetime.now():%Y-%m-%d}",
             "<i>HOSE/HNX/UPCoM · tự động, tham khảo, không phải khuyến nghị</i>", ""]
    if summary:
        parts.append("🎯 <b>Shortlist &amp; tín hiệu</b>")
        for s in summary[:32]:
            parts.append(html.escape(s.replace("**", "")))
        parts.append("")
    parts.append("📊 <b>Dịch chuyển giá nổi bật</b>")
    if gain: parts.append("🟢 Tăng: " + html.escape(", ".join(gain)))
    if lose: parts.append("🔴 Giảm: " + html.escape(", ".join(lose)))
    if surge: parts.append("⚡ Bùng KL: " + html.escape(", ".join(surge)))
    u = run_url()
    if u:
        parts.append("")
        parts.append(f'📄 Báo cáo đầy đủ (artifact): <a href="{u}">mở run</a>')

    text = "\n".join(parts)
    print(text, file=sys.stderr)
    ok = send(text)
    print("[telegram] gửi " + ("OK" if ok else "THẤT BẠI"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
