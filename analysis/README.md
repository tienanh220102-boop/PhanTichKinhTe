# analysis/ — Causal Inference Pipeline (on-demand)

Tầng phân tích nhân quả của dự án Phân tích Kinh tế. **Chạy tay khi cần** —
KHÔNG nằm trong workflow cron (nặng + không cần mỗi 30 phút).

## Module (swap ruột từng phần, không đập đi xây lại)

| Module | Vai trò | Thay ruột khi nào |
|---|---|---|
| `data_pipeline.py` | `DataPipeline`: fetch WB annual (REST keyless) + yfinance daily; `align()` resample M/Q; `impute()` ffill/interpolate | Thêm nguồn (GSO, IMF) → thêm method fetch mới |
| `causal_dag.py` | `CausalDAG`: đồ thị giả định lãi suất/FDI/ESG/GDP/cú sốc năng lượng; xuất GML (DoWhy-ready); `sign_checks()` smell-test | Đổi giả định → sửa `EDGES` |
| `event_impact.py` | `EventImpact`: counterfactual kiểu CausalImpact bằng statsmodels UnobservedComponents (local level + covariates) | Cần full Bayesian → thay ruột `fit()` bằng tfcausalimpact, interface giữ nguyên |
| `run_event.py` | **CLI tổng quát** cho mọi sự kiện (Fed/OPEC+/địa chính trị); tự lưu `outputs/analysis_<tên>_<ngày>.txt` → tích lũy thư viện event study | Sự kiện mới = 1 lệnh, không cần code |
| `run_fomc_20260429.py` | Demo hoàn chỉnh: DAG + smell test + FOMC 29/04/2026 → ICLN/ESGU | — |

## Quyết định thiết kế (so với blueprint gốc)

- **KHÔNG dùng tfcausalimpact**: kéo TensorFlow ~600MB chỉ để fit BSTS.
  statsmodels UnobservedComponents cho cùng counterfactual (MLE thay posterior).
- **KHÔNG ước lượng DoWhy trên data VN annual**: n≈30 → mọi causal estimate
  là data-snooping. DAG chỉ làm tài liệu giả định + GML sẵn cho tương lai.
- **CausalImpact trên "ESG investment/R&D budget"**: bất khả thi — data annual
  trễ 1-3 năm. Thay bằng proxy thị trường daily (ICLN/ESGU).
- Kết quả event study là **relative event study** (phản ứng bất thường so với
  SPY/XLE) — sự kiện vĩ mô tác động cả covariates nên không tách kênh tuyệt đối.

## Cài đặt

```bash
pip install statsmodels   # duy nhất; pandas/numpy/yfinance/requests đã có
```

## Chạy

```bash
# Sự kiện bất kỳ (ví dụ OPEC+ → WTI, kiểm soát SPY + DXY):
python analysis/run_event.py --name opec_cut --event 2026-06-01 --y CL=F --x SPY,DX-Y.NYB

# Preset có sẵn:
python analysis/run_event.py --preset fomc_20260429

# Demo đầy đủ (DAG + smell test + event study):
python analysis/run_fomc_20260429.py
```

Gợi ý y/covariates theo loại sự kiện: xem docstring đầu `run_event.py`.

Kết quả lần chạy 11/06/2026: cả ICLN lẫn ESGU **không phản ứng bất thường
có ý nghĩa** với FOMC dissent 29/04 sau khi kiểm soát SPY+XLE
(ICLN −1.02% [CI −13.5..+11.4]; ESGU +0.48% [CI −0.2..+1.2]).
