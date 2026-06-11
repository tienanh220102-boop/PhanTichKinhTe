# -*- coding: utf-8 -*-
"""
CausalDAG — tang gia dinh nhan qua, viet ra giay truoc khi cham vao so lieu.

VAI TRO THUC TE (quan trong — doc truoc khi dung):
  Voi du lieu vi mo VN annual (n ≈ 30 quan sat), MOI uoc luong nhan qua
  (DoWhy estimate, causal discovery tu dong) deu vo nghia thong ke.
  DAG o day la TAI LIEU GIA DINH co cau truc:
    1. Buoc LLM/nguoi phan tich noi ro minh tin X → Y vi sao
    2. Suy ra cac kiem tra "smell test" kha thi voi n nho
       (dau tuong quan co dung huong ky vong khong — KHONG phai causal proof)
    3. Xuat GML — neu sau nay co du lieu quarterly dai hon (IMF IFS tra phi,
       GSO), cam thang vao DoWhy ma khong viet lai

Cau truc swap duoc: them/bot canh chi sua EDGES, khong dung code khac.
"""
import itertools
import pandas as pd

# (nguon, dich, gia_dinh — ly do kinh te luan)
EDGES = [
    ('policy_rate', 'fdi',
     'Lai suat cao → chi phi von cao + ty gia manh → FDI vao giam (do tre 2-4 quy)'),
    ('policy_rate', 'gdp',
     'Kenh truyen dan tien te chuan: lai suat → tin dung/dau tu → san luong (tre 2-6 quy)'),
    ('policy_rate', 'esg_inv',
     'Du an xanh tham dung von (NPV nhay voi discount rate) → lai suat cao danh manh hon vao green capex'),
    ('fdi', 'gdp',
     'FDI → von + cong nghe + viec lam → GDP (VN: FDI ~4-5% GDP, dong gop xuat khau lon)'),
    ('fdi', 'esg_inv',
     'FDI 2026 mang theo mandate ESG/SDG cua tap doan me → keo chuan dau tu xanh noi dia'),
    ('esg_inv', 'gdp',
     'Dau tu xanh la cau phan cua tong dau tu → GDP; hieu ung nang suat dai han hon'),
    ('energy_shock', 'policy_rate',
     'Cu soc gia nang luong (Trung Dong 2026) → lam phat → NHTW giu/tang lai suat (confounder ngoai sinh)'),
    ('energy_shock', 'esg_inv',
     'Gia hoa thach cao → dong luc chuyen doi xanh tang (hieu ung thay the) — canh nguoc dau voi kenh lai suat'),
    ('energy_shock', 'gdp',
     'Chi phi dau vao tang → san luong giam ngan han'),
]

NODES_VN = {
    'policy_rate':  'Lãi suất điều hành',
    'fdi':          'Dòng vốn FDI vào',
    'esg_inv':      'Đầu tư xanh/ESG (proxy)',
    'gdp':          'GDP / Sản lượng công nghiệp',
    'energy_shock': 'Cú sốc giá năng lượng (ngoại sinh)',
}


class CausalDAG:
    def __init__(self, edges=EDGES):
        self.edges = edges
        self.nodes = sorted({e[0] for e in edges} | {e[1] for e in edges})

    def parents(self, node):
        return sorted({s for s, d, _ in self.edges if d == node})

    def to_gml(self):
        """GML string — DoWhy CausalModel(graph=...) nhan truc tiep."""
        lines = ['graph [', '  directed 1']
        for n in self.nodes:
            lines.append(f'  node [ id "{n}" label "{n}" ]')
        for s, d, _ in self.edges:
            lines.append(f'  edge [ source "{s}" target "{d}" ]')
        lines.append(']')
        return '\n'.join(lines)

    def assumptions_table(self):
        """Bang gia dinh de dua vao bao cao / prompt LLM."""
        return '\n'.join(f'- {NODES_VN.get(s, s)} → {NODES_VN.get(d, d)}: {a}'
                         for s, d, a in self.edges)

    def sign_checks(self, df):
        """Smell test kha thi voi n nho: dau tuong quan (truoc/sau sai phan)
        co khop huong gia dinh khong. KHONG phai kiem dinh nhan qua.

        df: DataFrame cot trung ten node (sau align/impute). Tra ve DataFrame.
        """
        rows = []
        d1 = df.diff()   # sai phan bac 1 — giam spurious correlation do trend chung
        for s, d, _ in self.edges:
            if s not in df or d not in df:
                continue
            n = df[[s, d]].dropna().shape[0]
            rows.append({
                'edge':       f'{s} → {d}',
                'corr_level': round(df[s].corr(df[d]), 2),
                'corr_diff':  round(d1[s].corr(d1[d]), 2),
                'n':          n,
                'luu_y':      'n<30 — chi xem dau, khong xem do lon' if n < 30 else '',
            })
        return pd.DataFrame(rows)

    def backdoor_note(self, treatment, outcome):
        """Voi DAG nay, neu sau nay uoc luong treatment→outcome thi phai
        adjust tap cha cua treatment (tru node nam tren duong truyen)."""
        adj = [p for p in self.parents(treatment)]
        return (f'Uoc luong {treatment} → {outcome}: adjustment set toi thieu = '
                f'{adj or "rong (treatment ngoai sinh trong DAG nay)"}')
