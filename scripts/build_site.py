# -*- coding: utf-8 -*-
"""Build static website (docs/) tu cac file trong outputs/.

Chay sau cac agent trong workflow; GitHub Pages serve tu main:/docs.
Pure stdlib, idempotent: cung outputs -> cung site.
"""
import html
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / 'outputs'
DOCS = ROOT / 'docs'
REPORTS_DIR = DOCS / 'reports'

VN_TZ = timezone(timedelta(hours=7))

SESSION_LABELS = {
    'morning': 'Phiên sáng',
    'evening': 'Phiên tối',
    'weekly': 'Tổng kết tuần',
    'weekly_commodity': 'Tổng kết tuần',
}

SIGNAL_CLASS = {
    'MUA': 'buy', 'BÁN': 'sell', 'GIỮ': 'hold',
    'TĂNG': 'buy', 'GIẢM': 'sell', 'SIDEWAY': 'hold',
}

# Cac nhom hang hoa theo dung header trong report
CATEGORIES = [
    ('NĂNG LƯỢNG', 'Năng lượng'),
    ('KIM LOẠI QUÝ', 'Kim loại quý'),
    ('NÔNG SẢN', 'Nông sản'),
    ('KIM LOẠI CÔNG NGHIỆP', 'KL công nghiệp'),
]

CSS = '''
:root { --bg:#0f1419; --card:#1a2129; --border:#2a3441; --text:#d8dee6;
        --muted:#8a96a3; --accent:#4fc3f7; --buy:#26a69a; --sell:#ef5350; --hold:#ffa726; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif;
       line-height:1.6; padding:16px; max-width:860px; margin:0 auto; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
header { margin-bottom:24px; }
header h1 { font-size:1.5rem; }
header .sub { color:var(--muted); font-size:.85rem; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px;
        padding:18px; margin-bottom:18px; }
.card h2 { font-size:1.05rem; margin-bottom:10px; color:var(--accent); }
.badge { display:inline-block; padding:1px 10px; border-radius:12px; font-size:.8rem;
         font-weight:600; color:#fff; }
.badge.buy { background:var(--buy); } .badge.sell { background:var(--sell); }
.badge.hold { background:var(--hold); color:#222; } .badge.na { background:var(--border); }
.field { margin:2px 0; }
.field .k { color:var(--muted); }
ul { padding-left:20px; margin:6px 0; }
table { width:100%; border-collapse:collapse; font-size:.88rem; }
th, td { padding:6px 8px; text-align:left; border-bottom:1px solid var(--border); }
th { color:var(--muted); font-weight:600; }
.archive li { margin:4px 0; }
.archive .tag { color:var(--muted); font-size:.82rem; }
footer { color:var(--muted); font-size:.78rem; text-align:center; margin-top:28px; }
.back { display:inline-block; margin-bottom:14px; }
pre.raw { white-space:pre-wrap; font-family:inherit; }
@media (max-width:600px) { body { padding:10px; } th, td { padding:5px 4px; } }
'''


def esc(s):
    return html.escape(s, quote=False)


def inline_md(s):
    """**bold** -> <strong>, sau khi da escape."""
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', esc(s))


def badge(value):
    cls = SIGNAL_CLASS.get(value.strip().upper().replace('SIDEWAYS', 'SIDEWAY'), 'na')
    return '<span class="badge %s">%s</span>' % (cls, esc(value.strip()))


def is_section_header(line):
    """Header bat dau bang emoji (ky tu ngoai BMP-letter) va ngan."""
    if not line or len(line) > 90:
        return False
    if ': ' in line or ' = ' in line:  # dong chu thich/du lieu, khong phai header
        return False
    first = line[0]
    return ord(first) > 0x2000 and not first.isalnum()


def render_txt_report(text):
    """Chuyen report .txt thanh HTML: header emoji -> h2, field -> styled row, * -> li."""
    out, in_list = [], False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append('</ul>')
            in_list = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            close_list()
            continue
        if is_section_header(line):
            close_list()
            out.append('</div><div class="card"><h2>%s</h2>' % esc(line))
            continue
        if line.startswith('* '):
            if not in_list:
                out.append('<ul>')
                in_list = True
            out.append('<li>%s</li>' % inline_md(line[2:].lstrip('* ').strip()))
            continue
        close_list()
        m = re.match(r'^(Xu hướng|Tín hiệu)\s*:\s*(.+)$', line)
        if m:
            out.append('<div class="field"><span class="k">%s:</span> %s</div>'
                       % (esc(m.group(1)), badge(m.group(2))))
            continue
        m = re.match(r'^(Ngưỡng giá|Phân tích|Rủi ro|Khuyến nghị)\s*:\s*(.+)$', line)
        if m:
            out.append('<div class="field"><span class="k">%s:</span> %s</div>'
                       % (esc(m.group(1)), inline_md(m.group(2))))
            continue
        out.append('<p>%s</p>' % inline_md(line))
    close_list()
    body = ''.join(out)
    # render_txt_report mo card bang cach dong card truoc -> bo '</div>' dau, them '</div>' cuoi
    if body.startswith('</div>'):
        body = body[len('</div>'):]
    else:
        body = '<div class="card">' + body
    return body + '</div>'


def page(title, body, back_link=True):
    back = '<a class="back" href="../index.html">&larr; Trang chủ</a>' if back_link else ''
    return ('<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s</title><link rel="stylesheet" href="%sstyle.css"></head><body>'
            '%s<header><h1>%s</h1></header>%s'
            '<footer>Phân tích Kinh tế — báo cáo tự động, không phải khuyến nghị đầu tư.</footer>'
            '</body></html>'
            % (esc(title), '../' if back_link else '', back, esc(title), body))


def extract_signals(text):
    """Lay (xu huong, tin hieu) cho tung nhom hang hoa tu report."""
    sig = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if is_section_header(line):
            current = None
            for key, label in CATEGORIES:
                if key in line.upper() or key in line:
                    current = label
                    break
        elif current:
            m = re.match(r'^(Xu hướng|Tín hiệu)\s*:\s*(.+)$', line)
            if m:
                sig.setdefault(current, {})[m.group(1)] = m.group(2).strip()
    return sig


def classify(path):
    """Tra ve (date_str, sort_key, label, kind) cho 1 file output."""
    name = path.name
    m = re.match(r'^report_(\d{4}-\d{2}-\d{2})_(\w+)\.txt$', name)
    if m:
        session = m.group(2)
        order = {'morning': 0, 'evening': 1}.get(session, 2)
        return m.group(1), (m.group(1), order), SESSION_LABELS.get(session, session), 'commodity'
    m = re.match(r'^banking_(\d{4}-\d{2}-\d{2})\.html$', name)
    if m:
        return m.group(1), (m.group(1), 3), 'Ngân hàng & BĐS', 'banking'
    m = re.match(r'^analysis_.+_(\d{4}-\d{2}-\d{2})\.txt$', name)
    if m:
        topic = name[len('analysis_'):-len('_%s.txt' % m.group(1))].replace('_', ' ')
        return m.group(1), (m.group(1), 4), 'Phân tích: %s' % topic, 'analysis'
    return None


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS / 'style.css').write_text(CSS, encoding='utf-8')
    (DOCS / '.nojekyll').write_text('', encoding='utf-8')

    items = []  # (date, sort_key, label, kind, href, text|None)
    for path in OUTPUTS.iterdir():
        info = classify(path)
        if not info:
            continue
        date_str, sort_key, label, kind = info
        slug = path.stem + '.html'
        if kind == 'banking':
            shutil.copyfile(path, REPORTS_DIR / slug)
            items.append((date_str, sort_key, label, kind, 'reports/' + slug, None))
        else:
            text = path.read_text(encoding='utf-8')
            title = '%s — %s' % (label, date_str)
            (REPORTS_DIR / slug).write_text(
                page(title, render_txt_report(text)), encoding='utf-8')
            items.append((date_str, sort_key, label, kind, 'reports/' + slug, text))

    items.sort(key=lambda x: x[1], reverse=True)
    if not items:
        print('Khong co output nao de build site')
        return

    # Bao cao hang hoa moi nhat hien thi ngay tren trang chu
    latest = next((it for it in items if it[3] == 'commodity'), None)
    sections = []

    if latest:
        sections.append('<div class="card"><h2>Mới nhất: %s — %s</h2>'
                        '<a href="%s">Xem báo cáo đầy đủ &rarr;</a></div>'
                        % (esc(latest[2]), latest[0], latest[4]))
        sig = extract_signals(latest[5])
        if sig:
            rows = ''.join(
                '<tr><td>%s</td><td>%s</td><td>%s</td></tr>'
                % (esc(label),
                   badge(sig[label].get('Xu hướng', '—')) if label in sig else '—',
                   badge(sig[label].get('Tín hiệu', '—')) if label in sig else '—')
                for _, label in CATEGORIES)
            sections.append('<div class="card"><h2>Tín hiệu phiên mới nhất</h2>'
                            '<table><tr><th>Nhóm</th><th>Xu hướng</th><th>Tín hiệu</th></tr>'
                            '%s</table></div>' % rows)
        sections.append(render_txt_report(latest[5]))

    # Lich su tin hieu (toi da 14 report hang hoa gan nhat)
    history = [it for it in items if it[3] == 'commodity'][:14]
    if len(history) > 1:
        rows = []
        for date_str, _, label, _, href, text in history:
            sig = extract_signals(text)
            cells = ''.join(
                '<td>%s</td>' % (badge(sig[cat].get('Tín hiệu', '—')) if cat in sig else '—')
                for _, cat in CATEGORIES)
            rows.append('<tr><td><a href="%s">%s<br><span class="tag">%s</span></a></td>%s</tr>'
                        % (href, date_str, esc(label), cells))
        head = ''.join('<th>%s</th>' % esc(c) for _, c in CATEGORIES)
        sections.append('<div class="card"><h2>Lịch sử tín hiệu</h2>'
                        '<table><tr><th>Phiên</th>%s</tr>%s</table></div>'
                        % (head, ''.join(rows)))

    # Archive day du
    arch = ''.join(
        '<li><a href="%s">%s</a> <span class="tag">%s</span></li>'
        % (href, date_str, esc(label))
        for date_str, _, label, _, href, _ in items)
    sections.append('<div class="card archive"><h2>Tất cả báo cáo</h2><ul>%s</ul></div>' % arch)

    now_vn = datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M')
    body = ('<header><h1>Phân tích Kinh tế</h1>'
            '<div class="sub">Hàng hóa &middot; Ngân hàng &amp; BĐS &middot; '
            'cập nhật %s (giờ VN)</div></header>%s' % (now_vn, ''.join(sections)))
    index_html = ('<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width, initial-scale=1">'
                  '<title>Phân tích Kinh tế</title>'
                  '<link rel="stylesheet" href="style.css"></head><body>%s'
                  '<footer>Báo cáo sinh tự động bởi AI agent — không phải khuyến nghị đầu tư.</footer>'
                  '</body></html>' % body)
    (DOCS / 'index.html').write_text(index_html, encoding='utf-8')
    print('Build site OK: %d reports -> docs/' % len(items))


if __name__ == '__main__':
    main()
