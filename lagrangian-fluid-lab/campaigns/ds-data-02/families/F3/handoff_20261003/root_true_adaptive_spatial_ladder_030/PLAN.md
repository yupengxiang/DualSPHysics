# F3 True Adaptive Spatial Ladder Preparation Plan (Round 030)

## 1. Executive Summary & Root History Provenance

This deliverable establishes the genuine adaptive **spatial ladder** candidate numerical family for the F3 family under campaign `DS-DATA-02`. All preparation is source-only, bounded by Root guard policies (no unguided solver or GenCase execution; synthetic fixtures and validation scripts only).

### 1.1 Root Latest Successful Full-History Results
- **Saved-Frequency Macros (Attempt 021)**:
  - Integration folder: `families/F3/handoff_20261003/root_actual_adaptive_saved_frequency_macro_021`.
  - Result: All 7 registered 1% time/output budgets **PASS**.
  - Largest common-support velocity / $U$: `0.001517874828701138` (well below 0.01 budget).
  - Baseline nominal (836 frames) vs dense (4,176 frames) at same CFL 0.05 and CoefDtMin 0.005 over the complete physical window $[0, 8.35]\,\text{s}$.
- **Saved-Frequency Native Canonical Transport (Attempt 022)**:
  - Report path: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_CELL3_LONG_DP0075_ADAPTIVE_SAVE_FREQUENCY_TRANSPORT_001/root-cell3-same-recipe-full-native-saved-transport-v2-022/saved-transport-report.json`.
  - Result: Execution returncode 0 under strict complete configuration, expected full frames, exact 108,000 UID (34,560 fluid), native particle masses, and source receipts.
  - Chords & fate: 11,936 joint observed x-exchange crossing events; **zero fate switches** between nominal and dense saved observations; all dense crossing intervals fall strictly inside nominal brackets with average bracket tightening $5.0001956464\times$.
  - Time offset: Mean absolute crossing time difference $3.3052 \times 10^{-5}\,\text{s}$, maximum $0.0043427\,\text{s}$; residence time $p_{95} = 2.8438 \times 10^{-4}\,\text{s}$.
  - Descriptive characterization: Canonical crossing chords are piecewise-linear discrete crossing approximations, **not** continuous CFD ground truth or CDF qualification. Endpoint overshoot $8.350008979\,\text{s}$ preserved. 835 nominal instants inside $[0, 8.35]\,\text{s}$ have time offset 0 and destination agreement 1.0; this agreement does not constitute a proof of bitwise identical trajectory continuation.
  - Historical context: Historical true-half macro-017 passed all 1% time budgets, but paired transport root-015 retained 1,388 fate switches and $0.15598\,\text{s}$ mean absolute time offset.
  - Global status: Campaign qualification remains **Q-N 0/336**; no qualified domain exists yet.

---

## 2. Genuine Adaptive Spatial Ladder Design

To establish a candidate numerical family for spatial convergence, we define a 3-resolution ladder anchored on the exact current CELL3 physical mother geometry and forcing, sharing the adaptive baseline recipe (CFL 0.05, CoefDtMin 0.005, unclamped Symplectic, Wendland kernel, mDBC no-slip, NoPenetration enabled).

### 2.1 Physical Mother Continuum Geometry & Forcing
- **Container Interior**: Length $L_x = 0.9\,\text{m}$ ($-0.45$ to $+0.45\,\text{m}$), Width $L_y = 0.18\,\text{m}$ ($-0.09$ to $+0.09\,\text{m}$), Height $L_z = 0.51\,\text{m}$ ($0.0$ to $0.51\,\text{m}$).
- **Still Water Column**: Depth $d = 0.09\,\text{m}$, continuum volume $V = 0.9 \times 0.18 \times 0.09 = 0.01458\,\text{m}^3$.
- **Reference Density**: $\rho_0 = 1000\,\text{kg/m}^3 \implies M_{\text{fluid}}^{\text{continuum}} = 14.580000\,\text{kg}$.
- **Whole-Field Forcing**: Prescribed body acceleration from `CaseSloshingAccData.csv` (SHA256: `6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3`), acceleration centre $(0.45, 0.0, 0.0)$, `globalgravity=0`.
- **Physical Boundary Conditions**: 5 closed faces (bottom, left, right, front, back) with 3 layers of mDBC boundary particles (`layers vdp="0,1,2"`), open top face.

### 2.2 Commensurate 3-Resolution Spatial Ladder Triad
The ladder is formed strictly by changing particle spacing $DP$ from the fine adaptive baseline $DP = 0.0075\,\text{m}$, choosing commensurate grid spacings $DP = 0.015\,\text{m}$ (Coarse) and $DP = 0.010\,\text{m}$ (Medium):

| Property | Coarse (DP 0.015m) | Medium (DP 0.010m) | Fine (DP 0.0075m, Anchor) | Commensurate Relationship |
| :--- | :--- | :--- | :--- | :--- |
| **Case ID** | `F3_CELL3_LONG_DP0150_ADAPTIVE_CFL05_COEF005` | `F3_CELL3_LONG_DP0100_ADAPTIVE_CFL05_COEF005` | `F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005` | Triad: 6 : 4 : 3 |
| **Grid Spacing ($DP$)** | $0.015\,\text{m}$ ($2\times$ Fine) | $0.010\,\text{m}$ ($4/3\times$ Fine) | $0.0075\,\text{m}$ ($1\times$) | Commensurate integers |
| **Pointref** | $(0.0075, 0.0075, 0.0075)$ | $(0.005, 0.005, 0.005)$ | $(0.00375, 0.00375, 0.00375)$ | Exactly $DP / 2$ |
| **Fluid Grid ($N_x \times N_y \times N_z$)** | $60 \times 12 \times 6$ cells | $90 \times 18 \times 9$ cells | $120 \times 24 \times 12$ cells | Integer cell counts |
| **Fluid Particles** | **4,320** | **14,580** | **34,560** | Exact 3D cell centers |
| **Boundary Particles** | **19,944** | **42,480** | **73,440** | 3 mDBC wall layers |
| **Total Particles** | **24,264** | **57,060** | **108,000** | Strict 3D formulation |
| **Particle Mass ($m_p = \rho_0 DP^3$)** | $0.003375\,\text{kg}$ | $0.001000\,\text{kg}$ | $0.000421875\,\text{kg}$ | Native particle mass |
| **Initial Native Fluid Mass** | **14.580000 kg** | **14.580000 kg** | **14.58000038 kg** | Matches continuum 14.58 kg |
| **Smoothing Length $h$** | $0.02388256\,\text{m}$ | $0.01592170\,\text{m}$ | $0.01194128\,\text{m}$ | $h = 0.91924 \sqrt{3} DP$ |
| **Estimated Wall Time** | $\sim 600\,\text{s}$ ($\le 2\,\text{h}$ cap) | $\sim 1,200\,\text{s}$ ($\le 2\,\text{h}$ cap) | $1,976\,\text{s}$ (actual Attempt 007) | Fast bounded candidates |
| **Estimated Raw Output** | $\sim 1.0\,\text{GB}$ | $\sim 2.0\,\text{GB}$ | $3.8\,\text{GB}$ (actual Attempt 007) | Minimal disk impact |
| **Status** | Prepared, GenCase request ready | Prepared, GenCase request ready | Completed (Attempt 007/008/009/021/022) | Full history available |

### 2.3 Strict Physical Equivalence & Validation of Pre-existing Inputs
1. **Geometry & Forcing Parity**:
   - The continuum mother bounding box, fluid fill box, and 5-face shell geometry are identical across all resolutions.
   - Forcing is identical: prescribed linear and angular body acceleration from `CaseSloshingAccData.csv`.
   - Periodic boundaries: `periodic_boundary = false`; all outer boundaries are closed tank walls except the open top face.
2. **Pre-existing Medium ($DP = 0.010\,\text{m}$) GenCase BI4 Verification**:
   - `cell3/F3_CELL3_plain_0p01/F3_CELL3_plain_0p01.bi4` (SHA256: `07444b30c5c956e88651667b591a6ca0ba08bff3e9b9435c80a2fc8437482d38`) contains exactly 57,060 particles (14,580 fluid, 42,480 fixed).
   - Generating from `definitions/F3_CELL3_plain_0p010_Def.xml` reproduces this exact physical particle geometry.
3. **Prohibition on Reusing Historical Fixed-Dt Solver Results**:
   - Historical run `F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen` in `l1-resume` had `CoefDtMin = 0.05` and `cflnumber = 0.05`, causing 100% floor-clamping (acting as fixed-dt equivalent).
   - As mandated by the task boundary: **Do NOT reuse fixed-dt solver results as adaptive equivalent**.
   - The medium case in the genuine adaptive spatial ladder adopts `CoefDtMin = 0.005`, decoupling the floor by $10\times$ and allowing natural adaptive SPH timestepping.
4. **Non-Normalization Policy**:
   - Native particle mass and continuum reference mass are reported separately.
   - No posthoc weight scaling or artificial mass normalization is permitted.

---

## 3. Frozen F3 Macro & Transport Spatial Contracts

### 3.1 Macro Spatial Observables (7 Metrics)
Evaluated using the frozen canonical operator `scripts/f3_observation_v2.py`:
1. `tv`: Total variation metric on fixed $60\,\text{mm}$ spatial grid bins.
2. `com_l2_over_length`: Center-of-mass $L_2$ distance divided by tank length $L = 0.9\,\text{m}$.
3. `q90_over_length`: 90th mass percentile $x$-position offset divided by $L = 0.9\,\text{m}$.
4. `mean_velocity_over_U`: Mass-weighted velocity offset divided by characteristic velocity $U = \sqrt{g \cdot d} = \sqrt{9.81 \cdot 0.09} \approx 0.9396\,\text{m/s}$.
5. `energy_difference`: Normalized kinetic energy discrepancy relative to $0.5 M_0 U^2$.
6. `common_support_velocity_over_U`: Velocity error restricted to mutually occupied spatial bins.
7. `unmatched_support_mass`: Total fluid mass fraction occupying disjoint bins.

### 3.2 Budgets & Thresholds
- **Time/Output Error Budget**: $0.01$ ($1\%$). (Already proven PASS across all 7 metrics in Attempt 021).
- **Spatial Reference Budget**: $0.05$ ($5\%$).
- **Transport Observables**: Canonical crossing chords across $x=0$, signed/net exchange mass $M_{\text{net}}(t)$, destination agreement, bracket tightening, fate switches, residence time $p_{95}$.
- **Descriptive CDF Label**: All transport CDF metrics are classified as **descriptive only**; no artificial 5% CDF gate or arbitrary per-UID chaos tolerance is invented.

---

## 4. Compute, Storage, and Dispatch Budget

All requests are pre-registered and bounded by strict resource quotas:
- **Home Storage Floor**: $500\,\text{GiB}$ (current available: $\sim 3.8\,\text{TiB}$).
- **Root NVMe Floor**: $100\,\text{GiB}$.
- **GPU Budget**: $\sim 46\,\text{h}$ remaining walltime; qualification quota $\sim 67$ cases.
- **Per-Case Runtime Cap**: Each coarse/medium candidate is bounded to `max_wall_seconds = 7200` ($\le 2\,\text{h}$). Actual expected execution times are $\sim 10\,\text{min}$ for coarse and $\sim 20\,\text{min}$ for medium.
- **Estimated Storage Costs**:
  - Coarse: $\sim 1.0\,\text{GB}$ solver `.bi4` frames, $\sim 0.65\,\text{GB}$ converted `.h5`.
  - Medium: $\sim 2.0\,\text{GB}$ solver `.bi4` frames, $\sim 1.5\,\text{GB}$ converted `.h5`.
- **GPU Device Dispatch**: Requests use placeholder `{LEASED_GPU_DEVICE_ID}`. The Root runtime dispatcher dynamically assigns an owned GPU (`2, 5, 6, 7`) while protecting foreign system processes on GPUs (`0, 1, 3, 4`).

---

## 5. Prospective Points of Comparison & Qualification Path

### 5.1 Prospective Comparison Dimensions
1. **Spatial Convergence Order**: Compute empirical convergence order $p$ across Coarse $\to$ Medium $\to$ Fine:
   $$p = \frac{\ln\left(\frac{\|E_{\text{coarse}} - E_{\text{medium}}\|}{\|E_{\text{medium}} - E_{\text{fine}}\|}\right)}{\ln(r)}$$
   Verify whether all 7 macro metrics remain within the registered 5% spatial budget.
2. **Boundary Layer Shear & Particle Retention**: With 3 layers of mDBC boundary particles on 5 walls, assess whether near-wall fluid particles remain confined to physical streamlines or show resolution-dependent boundary layer escape.
3. **Transport Fate & Exchange Dynamics**: Evaluate whether crossing chords across $x=0$ and net exchange mass $M_{\text{net}}(t)$ converge smoothly as spatial resolution refines from $DP=0.015\,\text{m}$ to $DP=0.0075\,\text{m}$.
4. **Adaptive Floor Margin**: Confirm that native timesteps satisfy $dt_{\text{min}} > \text{CoefDtMin} \cdot h / c_s$, guaranteeing $0\%$ floor clamping and zero DT adjustments across all spatial resolutions.

### 5.2 Independent Qualification Path for Both Mechanism Backgrounds
- **Background 1 (CELL3 Prescribed Sloshing)**:
  - Framework: Fixed tank computational coordinates, whole-field body acceleration.
  - Qualification path: Complete 3-resolution spatial ladder ($0.015, 0.010, 0.0075\,\text{m}$) + 2-cadence temporal ladder ($0.01, 0.002\,\text{s}$) + quarter-dt/CFL sensitivity.
  - Parameter endpoint domain: Drive amplitude $\Gamma \in \{0.6, 0.9, 1.2\}$, fill fraction $\in \{0.18, 0.27, 0.36\}$, frequency ratio $f/f_n \in \{0.8, 1.0, 1.2\}$.
- **Background 2 (Eccentric Baffle & Channel Exchange)**:
  - Framework: Moving tank world coordinates, rigid body motion.
  - Qualification path: Complete 3-resolution spatial ladder ($0.012, 0.008, 0.006\,\text{m}$) + fixed-dt half-minimum step study.
  - Parameter endpoint domain: Drive amplitude $\Gamma \in \{0.6, 0.9, 1.2\}$, fill fraction $\in \{0.18, 0.27, 0.36\}$, frequency ratio $f/f_n \in \{0.8, 1.0, 1.2\}$.
- **Rejection of Study Alias Counting**:
  - The 336-case label is an unassessed global space ($Q\text{-}N = 0/336$).
  - Sampling cadences, integration variants, and postprocessing permutations are validation instruments, **not** separate physical cases. No claim of progress is made by counting study aliases.

---

## 6. Authored Deliverables Inventory

| Path | Type | SHA256 | Description |
| :--- | :--- | :--- | :--- |
| `definitions/F3_CELL3_plain_0p015_Def.xml` | XML | `cce8f23ac8649e7f2c5380bf3c158dc8302fec0c228d882e1f5c3c1e79e78307` | Coarse ($DP=0.015\,\text{m}$) definition |
| `definitions/F3_CELL3_plain_0p010_Def.xml` | XML | `e444c9ab6632fc72117dfaef5bde8542f01b52825af648e316b15c77b7ae7c30` | Medium ($DP=0.010\,\text{m}$) definition |
| `definitions/F3_CELL3_plain_0p0075_Def.xml` | XML | `f4e5321e8fd3528ab08ea1c604d422e9dffbce7c6dae6397a13c6a52253efa64` | Fine ($DP=0.0075\,\text{m}$) definition |
| `requests/gencase_cpu_coarse_dp015_request.json` | Request | `ds02.runner-request.v2` | CPU GenCase request for Coarse ($DP=0.015\,\text{m}$) |
| `requests/gencase_cpu_medium_dp010_request.json` | Request | `ds02.runner-request.v2` | CPU GenCase request for Medium ($DP=0.010\,\text{m}$) |
| `requests/solver_gpu_coarse_dp015_request.json` | Request | `ds02.runner-request.v2` | GPU solver request for Coarse ($DP=0.015\,\text{m}$) |
| `requests/solver_gpu_medium_dp010_request.json` | Request | `ds02.runner-request.v2` | GPU solver request for Medium ($DP=0.010\,\text{m}$) |
| `contracts/spatial_ladder_contract.json` | Contract | `ds02.f3.adaptive-spatial-ladder-contract.v1` | Formal spatial ladder contract |
| `prospective_points_of_comparison.json` | Document | `ds02.root.prospective-spatial-ladder-comparison.v1` | Prospective comparison points & qualification path |
| `audit_spatial_ladder_preparation.py` | Script | Python 3 | 7-point audit and validation script |
| `tests/test_ds_data02_f3_true_adaptive_spatial_ladder_synthetic.py` | Test | pytest | Comprehensive synthetic test suite (10/10 PASS) |
