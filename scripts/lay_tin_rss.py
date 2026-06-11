"""
Cào RSS thực tế, không cần API key.
Output: in ra stdout dạng JSON.
"""
import json, html, sys, io
import requests
import xml.etree.ElementTree as ET

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BANKING_KEYWORDS = [
    'lãi suất','lai suat','lãi vay','tiền gửi','huy động',
    'tín dụng','tin dung','room','hạn mức','tăng trưởng tín dụng',
    'chính sách tiền tệ','nhnn','ngân hàng nhà nước',
    'ngân hàng','bidv','vietcombank','vietinbank','agribank',
    'techcombank','vpbank','mbbank','acb','sacombank','tpbank',
    'nợ xấu','tỷ giá','thanh khoản',
    'bất động sản','bat dong san','bds','nhà đất','căn hộ','chung cư',
    'đất nền','khu công nghiệp','nhà ở xã hội','vay mua nhà',
    'tp.hcm','tp hcm','hồ chí minh','bình dương','đồng nai',
    'long an','bà rịa','vũng tàu','phía nam',
]

RSS_FEEDS = [
    ('VnExpress BĐS',  'https://vnexpress.net/rss/bat-dong-san.rss'),
    ('VnExpress Kinh tế','https://vnexpress.net/rss/kinh-doanh.rss'),
    ('Thanh Niên KT',  'https://thanhnien.vn/rss/kinh-te.rss'),
    ('VietnamNet KT',  'https://vietnamnet.vn/rss/kinh-doanh.rss'),
    ('VOV Kinh tế',    'https://vov.vn/rss/kinh-te.rss'),
]

results = []
for source, url in RSS_FEEDS:
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(r.content)
        for item in list(root.iter('item'))[:50]:
            title = html.unescape(item.findtext('title', '')).strip()
            link  = item.findtext('link', '').strip()
            desc  = html.unescape(item.findtext('description', '')).strip()
            pub   = item.findtext('pubDate', '').strip()
            text  = (title + ' ' + desc).lower()
            if any(kw in text for kw in BANKING_KEYWORDS):
                results.append({
                    'source': source, 'title': title,
                    'link': link, 'desc': desc[:300], 'pub': pub
                })
        print(f'OK {source}: {len([x for x in results if x["source"]==source])} bai', file=sys.stderr)
    except Exception as e:
        print(f'LOI {source}: {e}', file=sys.stderr)

print(json.dumps(results, ensure_ascii=False, indent=2))
