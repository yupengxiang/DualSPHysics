# Prospective Registered DP 0.006m Adaptive Reference Preparation (v1)

## Overview & Provenance

This directory contains the prospective definition, continuum/discrete-geometry bindings, diff explanation, launch suggestions, and runner request specifications for the fine reference anchor candidate:
- **Case ID**: `F3_CELL3_LONG_DP006_ADAPTIVE_CFL05_COEF005`
- **Resolution**: $DP = 0.006\,\text{m}$
- **Role**: Fine reference anchor completing the historically registered spatial reference ladder $[0.010, 0.0075, 0.006]\,\text{m}$ defined in `F3-CELL3-PROTOCOL.json`.
- **Relationship to DP 0.015m**: DP 0.015m authored in Root Followup 030 is an auxiliary coarse diagnostic forming a 6:4:3 integer triad $(0.015, 0.010, 0.0075)$ for rapid bounds checking ($<10\,\text{min}$ GPU runtime); it does not replace the historically registered reference ladder $[0.010, 0.0075, 0.006]$.

## Directory Structure

```
registered_dp006_adaptive_reference_v1/
├── README.md                                             # This document
├── audit_dp006_preparation.py                            # Automated 39-check audit script
├── binding.json                                          # Prospective continuum, discrete geometry & recipe binding
├── diff_explanation.json                                 # Detailed diff vs fine anchor, historical fixed-step & coarse diagnostic
├── launch_suggestions.json                               # Root launch suggestions, resource budgets, and verification checks
├── definitions/
│   ├── F3_CELL3_LONG_DP006_ADAPTIVE_CFL05_COEF005_Def.xml# Canonical case definition XML
│   └── F3_CELL3_plain_0p006_Def.xml                      # Plain alias matching naming convention
└── requests/
    ├── gencase_cpu_dp006_request.json                    # CPU GenCase runner request suggestion (launch_allowed=false)
    └── solver_gpu_dp006_request.json                     # GPU Solver runner request suggestion (launch_allowed=false)
```

## Physical Mother Continuum Geometry & Discrete Alignment

1. **Continuum Tank & Water Fill**:
   - Tank interior: $[-0.45, 0.45]\,\text{m} \times [-0.09, 0.09]\,\text{m} \times [0.0, 0.51]\,\text{m}$ ($0.9\,\text{m} \times 0.18\,\text{m} \times 0.51\,\text{m}$).
   - Water column depth: $0.09\,\text{m}$, continuum volume $V_{\text{fluid}} = 0.01458\,\text{m}^3$.
   - Continuum mass ($\rho_0 = 1000\,\text{kg/m}^3$): $M_{\text{fluid}} = 14.580000\,\text{kg}$.
   - Prescribed body acceleration: `CaseSloshingAccData.csv` (SHA256: `6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3`), acceleration centre $(0.45, 0.0, 0.0)$, `globalgravity=0`.
   - Boundary specification: 5 closed faces (bottom, left, right, front, back) with 3 wall layers (`layers vdp="0,1,2"`), open top face, mDBC no-slip (`-mdbc_noslip:1`), `NoPenetration=1`.

2. **Discrete Spacing Alignment**:
   - $L_x / DP = 0.90 / 0.006 = 150$ cells (exact integer, 0 remainder).
   - $L_y / DP = 0.18 / 0.006 = 30$ cells (exact integer, 0 remainder).
   - $d_z / DP = 0.09 / 0.006 = 15$ cells (exact integer, 0 remainder).
   - $H_z / DP = 0.51 / 0.006 = 85$ cells (exact integer, 0 remainder).
   - Fluid particle count: $150 \times 30 \times 15 = 67,500$ particles.
   - Discrete volume: $67,500 \times (0.006\,\text{m})^3 = 0.01458\,\text{m}^3$ (exact match, $0.0\%$ deviation).
   - Nominal discrete mass: $67,500 \times (1000 \times 0.006^3) = 14.58\,\text{kg}$ (exact match, $0.0\%$ deviation).
   - **Discretization mismatch**: None. No coordinate stretching, cell clipping, or mass rescaling applied.

## Genuine Adaptive Recipe vs Historical Contrast

- **Numerical Formulation**: Symplectic integrator (`StepAlgorithm=2`), Wendland kernel (`Kernel=2`), `CFL=0.05`, `CoefDtMin=0.005`, `DtFixed=0`, `TimeMax=8.35`, `TimeOut=0.01` (836 native typed frames).
- **Historical Contrast**: Historical case `F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen` set `CoefDtMin=0.05`, equal to `CFL=0.05`, clamping the timestep 100% of the time to $dt_{\min} = \text{coefdtmin} \cdot h / c_s$ (an effectively fixed-dt simulation). The genuine adaptive recipe sets `CoefDtMin=0.005`, decoupling the floor by $10\times$ and allowing dynamic CFL timestepping. Historical fixed-step solver outputs must NOT be reused as adaptive reference evidence.
- **AutomaticEOS Policy**: Official GenCase AutomaticEOS is strictly preserved. Generated constants $B$, $h$, and native particle mass remain unknown until actual GenCase execution by Root. No invented constants, no bitwise equality assertions across DP, and no post-hoc mass rescaling.

## Order Estimation Policy

- The registered reference ladder consists of nodes $[0.010, 0.0075, 0.006]\,\text{m}$.
- Refinement ratios are non-uniform:
  - $r_{21} = 0.010 / 0.0075 = 4/3 \approx 1.3333$
  - $r_{32} = 0.0075 / 0.006 = 5/4 = 1.2500$
- Because $r_{21} \ne r_{32}$, standard constant-$r$ logarithmic formulas are unphysical and rejected. Convergence evaluation must use generalized non-uniform order estimation or evaluate metric compliance directly against the frozen 5% spatial reference budget from `f3_observation_v2.py`.

## Root Launch Suggestions & Resource Bounds

1. **CPU GenCase Request**:
   - `requests/gencase_cpu_dp006_request.json`
   - Resources: 2 CPU threads, max wall time 300s, storage $\sim 128\,\text{MiB}$.
   - Staging: `{attempt_root}/prepared`.
2. **GPU Solver Request**:
   - `requests/solver_gpu_dp006_request.json`
   - Resources: Leased GPU reservation using placeholder `{LEASED_GPU_DEVICE_ID}` restricted to Root-owned GPUs `[2, 5, 6, 7]`. Foreign GPUs `[0, 1, 3, 4]` strictly protected.
   - Wall time budget: $\le 7,200\,\text{s}$ (2 hours cap); estimated runtime $\sim 1,800\text{--}2,500\,\text{s}$ ($\sim 30\text{--}42\,\text{min}$ based on $2.1\times$ computational scaling over fine DP 0.0075m).
   - Storage budget: $\sim 8.5\,\text{GiB}$ BI4 raw output, well within scratch space floors.
   - Command: `DualSPHysics5.4_linux64 -mdbc_noslip:1 ... -tmax:8.35 -tout:0.01`.
   - Expected native output: Exactly 836 typed frames.
3. **Execution Flags**:
   - All requests specify `"launch_allowed": false` and `"launch_owner": "root"` ensuring authority boundaries are respected.

## Claim Boundaries

| Category | Status | Details |
| :--- | :--- | :--- |
| **Q-I (Input Qualification)** | **Completed** | Clean case definitions, parameter parity with anchor, exact integer spacing alignment, runner requests authored, 39/39 audit checks passed. |
| **Native Array Evidence** | **Pending Root Dispatch** | No GenCase or GPU solver execution executed by worktree agent; awaits Root runner dispatch. |
| **Q-N (Numerical Qualification)**| **Not Granted** | Requires verified evidence across full registered ladder, transport metrics, and parameter endpoints; campaign qualification remains **Q-N 0/336**. |
| **Production Approval** | **None** | No production grant authorized. |
