# F3 Historical Macro Scope Reuse and New Label Time Uncertainty Root Audit

## 1. Executive Summary

This formal root audit establishes the exact scientific boundaries for:
1. Reusing the 8 historical plain tank cases (`f3-legacy-plain-00`, `dev_06`, `dev_08`, `dev_12`, `dev_16`, `dev_20`, `dev_26`, `dev_31`).
2. Quantifying temporal uncertainty in first-passage and residence transport labels across historical versus new weak dual-axis spatial convergence references.

---

## 2. Historical Macro Scope Reuse Qualification

All 8 historical plain cases have undergone complete end-to-end data pipeline processing:
- Direct BI4-to-HDF5 conversion (`direct-v1`) with full particle trajectory states.
- Exact floating-point identity and state verification against legacy reference files (`subset-compare-v1`, maximum difference = 0.0).
- Full typed native transport label sidecars (`native-labels-v1`).
- Saved-state particle distribution preview renderings (`preview-v1`).

### Scope Boundaries:
- **Admitted Scope**: Validated baseline evidence for 1D single-axis horizontal sloshing under drive amplitude variation $a_x \in [0.903g, 1.097g]$.
- **Boundary Restrictions**:
  1. *No Cross-Axis Mechanics*: Because $a_y = 0$, these cases cannot be claimed as representative of 3D coupled dual-axis sloshing.
  2. *Single Discretization*: All 8 cases use a single grid spacing ($dp = 0.0075\text{ m}$); they cannot be used to establish spatial grid convergence.
  3. *Reference Status*: They serve as historical baseline evidence only, not as superseding numerical references for F3.

---

## 3. Label Temporal Uncertainty Analysis

First-passage times across monitoring planes ($x = 0$, $y = 0$, $z = 0.51$) are discretely bracketed by the saved interval $[t_{k-1}, t_k]$:

| Property | Historical Legacy Plain Cases | New Weak Dual-Axis Reference Matrix |
| :--- | :--- | :--- |
| Discretization $dp$ | Single: $0.0075\text{ m}$ | 3 Resolutions: $0.00818\text{ m}$, $0.0075\text{ m}$, $0.006\text{ m}$ |
| Excitation Mechanics | Single-axis $a_x \approx 0.90\text{--}1.10g$ | Coupled dual-axis $a_x = 0.06g, a_y = 0.04g$ |
| Target Output Cadence $\Delta t$ | $0.0100\text{ s}$ | $0.0025\text{ s}$ |
| Actual Frame Interval Range | $[0.009999\text{ s}, 0.010022\text{ s}]$ | $[0.002500\text{ s}, 0.002500\text{ s}]$ |
| Total Time Window | $8.35\text{ s}$ (836 frames) | $10.00\text{ s}$ (4,001 frames) |
| First-Passage Bracket Uncertainty | $\mathbf{\le 0.010022\text{ s}}$ | $\mathbf{\le 0.002500\text{ s}}$ (**4.0x precision gain**) |
| Open-Top Exit Rate | 0 | 0 (100% contained) |
| Fluid Mass Conservation | $14.5800\text{ kg}$ (0 exclusions) | $14.5800\text{ kg}$ (0 exclusions across all 3 resolutions) |

---

## 4. Root Approval and Recommendations

1. **Formal Acceptance**:
   - The 8 legacy plain cases are formally approved as historical baseline evidence.
   - The weak dual-axis 3-resolution matrix is approved as the spatial convergence and high-cadence temporal reference for F3.
2. **Contract Compliance**:
   - Both datasets satisfy the Q-I zero-loss structural contract (`NpOut = 0`).
   - The 4x finer temporal resolution of the weak dual reference reduces label timing error to $\pm 1.25\text{ ms}$, resolving all prior timing ambiguities.
