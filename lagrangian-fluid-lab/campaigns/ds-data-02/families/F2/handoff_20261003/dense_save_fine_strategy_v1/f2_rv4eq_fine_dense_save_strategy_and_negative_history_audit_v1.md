# DS-DATA-02 Family F2: Fine-Resolution Dense-Save Strategy & Negative History Audit v1

**Document Identifier:** `f2-rv4eq-fine-dense-save-strategy-and-negative-history-audit-v1`  
**Date:** 2026-10-03  
**Family:** F2 (Matched Sloshing / Moving Boundary Dynamics)  
**Author:** F2 Family Delegated Owner (`gemini-3.8-flash-high`, high effort)  
**Target Case:** `F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001`  
**Base Case:** `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001`  
**Physical Geometry Hash:** `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef` (strictly preserved)  
**Motion File Digest:** `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` (bitwise identical)  
**Status:** PROSPECTIVE SOLVER STRATEGY ONLY — No family GPU launch. Staged for Root resource reservation.

---

## 1. Executive Summary & Scientific Motivation

Under the frozen DS-DATA-02 quality contract for Family F2, the save interval allowance is strictly pinned:
$$\Delta t_{\text{save, max}} = 0.0007336390799938275\text{ s} \quad (\approx 0.0007336\text{ s})$$

The accepted baseline fine run (`F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001`) was executed with:
$$\text{TimeOut} = 0.010\text{ s} \quad (401\text{ frames over } 4.0\text{ s})$$
Because $0.010\text{ s} > 0.0007336\text{ s}$, the baseline simulation diagnostic fails the save interval allowance by $\approx 13.6\times$.

To address this temporal resolution gap rigorously without relaxing quality gates or synthesizing an unearned pass, this proposal defines a **source-driven dense-save numerical candidate**:
- **Output Interval (`TimeOut`):** $0.001\text{ s}$ ($1.0\text{ ms}$)
- **Total Output Frames:** $4001\text{ frames}$ ($t \in [0.000, 4.000]\text{ s}$)
- **Effective Half-Savewidth:** $\Delta t_{\text{save}} / 2 = 0.0005\text{ s}$ ($0.5\text{ ms}$)
- **Contract Compliance:** $0.0005\text{ s} < 0.0007336391\text{ s}$ ($\sim 31.8\%$ below the frozen contract threshold)

By reducing the save interval to $1.0\text{ ms}$, the half-savewidth strictly satisfies the quality contract's temporal requirement while preserving the exact continuum physical geometry and discrete motion controls bit-for-bit.

---

## 2. Historical Audit of Equal Products & Negative History

Before submitting any computational request, a strict audit of existing campaign history was conducted to eliminate redundant computation, prevent disk exhaustion, and protect foreign processes:

### 2.1. Historical Filename Discrepancy Note (`actual 401 != dense 4001`)
- The historical case directory name `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001` contains the text string `SAVE001`.
- However, inspection of the actual solver execution receipt ([`qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/execution-receipt.json`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/execution-receipt.json)) and solver configuration XML proves that:
  ```xml
  <parameter key="TimeMax" value="4" />
  <parameter key="TimeOut" value="0.01" />
  ```
  The simulation emitted exactly **401 frames**, NOT dense 4001 frames.
- **Finding:** No 4001-frame dense run has ever been executed for fine-resolution OFFSET F2. The string `SAVE001` in the historical directory was a naming convention, not a $1.0\text{ ms}$ output configuration.

### 2.2. Prior Half-Save Precedents in F2
- In medium resolution ($dp = 0.008\text{ m}$), a dense half-save test was previously executed:  
  `F2H10V2_OFFSET_V1_MEDIUM_RV4D1_HALF_SAVE0005` (8001 frames over 4.0s, $dt = 0.0005\text{ s}$).
- Execution metrics from receipt:
  - GPU seconds: $412.8\text{ s}$ on NVIDIA RTX 6000 Ada.
  - Raw storage generated: $37,414,873,331\text{ bytes}$ ($\approx 37.4\text{ GB}$).
  - Converted HDF5 storage: $\approx 22\text{ GB}$.

### 2.3. Negative History & Storage Risk Analysis for Fine Resolution
- Fine resolution ($dp = 0.005\text{ m}$) contains $1,833,408$ total particles ($196,608$ fluid particles).
- Baseline fine (401 frames) generated $29.4\text{ GB}$ of raw BI4 files alone.
- Scaling from 401 frames to 4001 frames represents a **$10\times$ increase in I/O output**:
  $$4001\text{ frames} \times \sim 73.3\text{ MB/frame} \approx 293.3\text{ GB}$$
- Adding log files, boundary summary VTK files, and scratch space, a single dense fine run demands $\approx 315\text{ GB}$ ($338,228,674,560\text{ bytes}$) of disk storage.
- **Historical Failure Mode:** In prior uncoordinated attempts across other families, launching dense-save runs without atomic parent-budget reservation exhausted disk storage, dropping Home free space below $500\text{ GiB}$ and triggering emergency job cancellations.
- **Policy Enforcement:**
  1. The Family Owner **must never launch GPU solvers directly**.
  2. No blind reruns: all requests are submitted to Root dispatcher via frozen requests with fully bounded cost and storage metrics.
  3. Execution is gated by Root's live UUID inventory, shared lease outside worktrees, and atomic parent-budget reservation.

---

## 3. Physical Invariance: Numerical Candidate vs Physical Case

This proposed run is strictly a **numerical discretization candidate**, NOT a new physical case. All physical definitions are inherited bit-for-bit without modification:

| Parameter / Entity | Value in Baseline Fine (`SAVE001`) | Value in Dense-Save Candidate (`DENSE_SAVE001`) | Status |
| :--- | :--- | :--- | :--- |
| **Physical Geometry Hash** | `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef` | `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef` | Bitwise Preserved |
| **Motion Control Digest** | `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` | `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` | Bitwise Identical |
| **Initial Fluid Denominator** | $196,608$ fluid particles | $196,608$ fluid particles | Exact Match |
| **Initial Continuum Domain** | $0.32 \times 0.24 \times 0.32\text{ m}^3$ ($24.576\text{ kg}$) | $0.32 \times 0.24 \times 0.32\text{ m}^3$ ($24.576\text{ kg}$) | Continuous Match |
| **Receiver Lower Corner** | $[0.45, -0.16, 0.0]\text{ m}$ ($y = +0.14\text{ m}$ offset) | $[0.45, -0.16, 0.0]\text{ m}$ ($y = +0.14\text{ m}$ offset) | Exact Match |
| **Receiver Dimensions** | $[1.10, 0.60, 0.45]\text{ m}$ | $[1.10, 0.60, 0.45]\text{ m}$ | Exact Match |
| **Cup Lower Corner** | $[0.0, -0.15, 0.65]\text{ m}$ | $[0.0, -0.15, 0.65]\text{ m}$ | Exact Match |
| **Cup Dimensions** | $[0.425, 0.30, 0.45]\text{ m}$ | $[0.425, 0.30, 0.45]\text{ m}$ | Exact Match |
| **Catch Tray Dimensions** | $4.00 \times 2.00 \times 0.15\text{ m}$ | $4.00 \times 2.00 \times 0.15\text{ m}$ | Exact Match |
| **Viscosity & Sound Speed** | $\nu = 0.03\text{ m}^2/\text{s}$, $c_s = 25\times$ | $\nu = 0.03\text{ m}^2/\text{s}$, $c_s = 25\times$ | Exact Match |
| **Output Interval (`TimeOut`)** | `0.01` s (401 frames) | `0.001` s (4001 frames) | **Refined for Temporal Compliance** |

---

## 4. Fully Bounded Solver Request Cost & Storage

The runner request (`requests/f2_rv4eq_fine_dense_save_solver_request_v1.json`) defines strict, conservative resource ceilings:

1. **Storage Bound:**
   - Raw BI4 stream (4001 frames): $\approx 293.3\text{ GB}$
   - Logging and diagnostic arrays: $\approx 1.0\text{ GB}$
   - Safety margin ($10\%$): $\approx 20.7\text{ GB}$
   - **`estimated_storage_bytes`:** $338,228,674,560\text{ bytes}$ ($315\text{ GiB}$)
2. **GPU Memory Bound:**
   - Single-precision particle state arrays ($1.833\text{M}$ particles): $\approx 1.2\text{ GB}$
   - Cell division and neighbor search data structures: $\approx 2.5\text{ GB}$
   - CUDA context and kernel scratch: $\approx 1.5\text{ GB}$
   - **`estimated_peak_gpu_mib`:** $16,384\text{ MiB}$ ($16\text{ GiB}$)
3. **Execution Time Bound:**
   - Baseline fine (401 frames) took $553\text{ s}$ on RTX 6000 Ada.
   - SPH compute kernels scale with simulation time ($4.0\text{ s}$ unchanged), but disk I/O scales $10\times$.
   - Projected GPU execution duration: $\sim 750 - 900\text{ s}$ ($\sim 12 - 15\text{ minutes}$).
   - **`max_wall_seconds`:** $3,600\text{ s}$ ($1.0\text{ hour}$ hard wall timeout).
4. **CPU Threads:** $4$ threads for host memory management and disk write coordination.

---

## 5. Eventual Adaptive Half-Stepping Strategy

While this dense-save candidate employs a uniform output interval ($\Delta t_{\text{save}} = 0.001\text{ s}$), it establishes the foundational spatial-temporal dataset required to assess an eventual **adaptive half-stepping candidate** independently:

1. **Uniform Baseline as Reference:** The uniform $1.0\text{ ms}$ output provides a continuous, unbiased time series of center-of-mass, kinetic energy, and spatial receiver capture trajectories.
2. **Adaptive Stepping Assessment:** An eventual adaptive time-stepping candidate can adjust output frequency based on local acceleration gradients (e.g. dense output during cup rotation and ballistic flight, coarser output during late settling).
3. **Independent Evaluation:** The adaptive candidate will be submitted and evaluated independently, using this uniform dense run as the ground-truth numerical reference.

---

## 6. Staged Deliverables

1. **Strategy Report:** [`f2_rv4eq_fine_dense_save_strategy_and_negative_history_audit_v1.md`](file:///home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/dense_save_fine_strategy_v1/f2_rv4eq_fine_dense_save_strategy_and_negative_history_audit_v1.md)
2. **Sidecar Metadata:** [`f2_rv4eq_fine_dense_save_strategy_sidecar_v1.json`](file:///home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/dense_save_fine_strategy_v1/f2_rv4eq_fine_dense_save_strategy_sidecar_v1.json)
3. **Case Definition XML:** [`F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001.xml`](file:///home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/dense_save_fine_strategy_v1/definitions/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001.xml)
4. **Prospective Runner Request:** [`f2_rv4eq_fine_dense_save_solver_request_v1.json`](file:///home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/dense_save_fine_strategy_v1/requests/f2_rv4eq_fine_dense_save_solver_request_v1.json)
5. **Synthetic Unit Tests:** [`test_f2_rv4eq_fine_dense_save_strategy_v1.py`](file:///home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/tests/test_f2_rv4eq_fine_dense_save_strategy_v1.py)
