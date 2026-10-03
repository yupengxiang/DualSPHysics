# F3 Adaptive Control Domain Prospective Staging (v2)

**Handoff Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2`  
**Campaign**: DS-DATA-02  
**Family**: F3 (Open-Top Rectangular Tank Sloshing)  
**Authority**: Root Followup 036 Continuation under F3 isolated worktree `ds-data-02-f6` (Gemini 3.8 Flash High authorized; overrides legacy Luna metadata)  
**Governance & Claim Boundary**: Entire control domain is `prospective`. `launch_allowed: false`, `q_n_status: not_granted`, `production_approval: none`. Nothing launchable without Root review and dispatch. Consumed assets and v1 preserved.

---

## 1. Executive Summary & Root Followup 036 Scope

Under **Root Followup 036**, this handoff delivers the repaired and qualified **v2** prospective amplitude control domain staging for Family F3. Strict operational and negative boundaries apply:
- **No recursive agents**: All work is scoped to this direct F3 invocation.
- **No solver / GenCase / array analysis / material model runs**: Actual numerical computation is exclusively owned by the Root shared strict runner.
- **No cleanup or main merges**: Baseline assets and historical evidence are strictly preserved; v1 (`adaptive_control_domain_prospective_v1`) is preserved untouched.
- **No resource ledger writes or production claims**: Campaign status remains `Q-N 0/336`, production approval `none`.
- **Synthetic testing only**: Transformer algorithms are verified strictly via in-memory synthetic unit test fixtures; no real CSV arrays are materialized or committed to git outside the Root dispatcher guard.

---

## 2. Root Rejection of v1 Transformer and v2 Comprehensive Repairs

### What Root Rejected in v1
Root identified that the v1 transformer (`format_coord`) contained several critical flaws:
1. **Small-value .2E quantization**: Formatting small numbers with `.2E` truncated the mantissa to 2 decimal places, changing forcing amplitudes by up to ~0.5%.
2. **Unauthorized deadband clamping**: Coordinates with $|val| < 10^{-15}$ were clamped to `"0"`, and values near gravity $|val - g_z| < 10^{-12}$ were clamped to `"-9.81E+00"` without physical or numerical justification.
3. **Silent row omission**: Malformed records with fewer than 7 tokens were silently dropped with `continue`.
4. **Missing integrity guards**: No checks for finite values, non-monotonic time, time window bounds, or expected row count.
5. **Destructive write mode**: Output files were opened with mode `"w"`, risking silent file overwrite.

### How v2 Repairs the Transformer (`transform_forcing.py`)
1. **Full Roundtrip `.17g` Precision**: Coordinate formatting uses `f"{val:.17g}"`, which guarantees exact IEEE-754 double precision full roundtrip (`float(f"{val:.17g}") == val`) across all finite values without quantization.
2. **No Arbitrary Clamping**: Clamps at $10^{-15}$ and $10^{-12}$ have been completely eliminated. Tiny physical values and near-gravity values are preserved exactly.
3. **Strict Integrity Guards**:
   - **All 7 Fields Finite**: Validates `math.isfinite` on time and all 6 spatial/angular accelerations.
   - **Strictly Increasing Time**: Enforces $t_k > t_{k-1}$ at every record.
   - **Expected Row Count Guard**: Reconciles exactly 167,001 data rows against the nominal sloshing series.
   - **Time Window Guard**: Enforces exact window coverage across $[0.0, 8.35]$ s.
   - **Immediate Malformed Rejection**: Rows with unexpected token counts or non-numeric entries raise `ValueError` immediately (no silent dropping).
4. **Exact Preserved Time Strings**: The input `time_str` (column 1) is passed through verbatim without string reformatting or float roundoff.
5. **Zero-Drive Formula & Numerical $A=1.0$ Identity**:
   $$\vec{a}_{\mathrm{lin}}(t) = \vec{g} + A \cdot (\vec{a}_{\mathrm{nom}}(t) - \vec{g})$$
   $$\vec{\alpha}(t) = A \cdot \vec{\alpha}_{\mathrm{nom}}(t)$$
   where $\vec{g} = (0, 0, -9.81)\ \mathrm{m/s^2}$. When nominal drive is zero ($\vec{a}_{\mathrm{lin}} = \vec{g}, \vec{\alpha} = \vec{0}$), the output evaluates to nominal zero drive for any amplitude $A$. When $A=1.0$, exact numerical identity is strictly preserved.
6. **Exclusive Non-Overwrite Mode**: Output files are opened with mode `"x"` (exclusive creation), raising `FileExistsError` if the destination exists.
7. **Pinned Nominal Digest**: `6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3`.
8. **Synthetic Test Fixtures**: 12 comprehensive synthetic unit tests exercising tiny values ($10^{-22}$), large values ($8.76 \times 10^{14}$), non-finite tokens (`NaN`, `Inf`), malformed records, signed zero (`-0.0`), close-to-gravity offsets ($-9.81 + 10^{-13}$), monotonic time violation, row count checks, and non-overwrite guards without materializing large CSVs.

---

## 3. Corrected Physics Review & Codebase Analysis

### DualSPHysics `JDsAccInput` Source & Kernel Mechanics
An exhaustive review of official DualSPHysics v5.4 source code ([`JDsAccInput.cpp`](file:///home/jade/Projects/DualSPHysics/src/source/JDsAccInput.cpp) and [`JDsAccInput_ker.cu`](file:///home/jade/Projects/DualSPHysics/src/source/JDsAccInput_ker.cu)) confirms:
1. **Right-Endpoint Velocity Integration**:
   At each CSV time record $k$, linear and angular velocities are integrated natively:
   $$\vec{v}_{\mathrm{lin}}[k] = \vec{v}_{\mathrm{lin}}[k-1] + \vec{a}_{\mathrm{lin}}[k] \cdot \Delta t$$
   $$\vec{v}_{\mathrm{ang}}[k] = \vec{v}_{\mathrm{ang}}[k-1] + \vec{\alpha}[k] \cdot \Delta t$$
   followed by continuous linear interpolation between discrete CSV records.
2. **Rotating Frame Mechanics**:
   On GPU ([`JDsAccInput_ker.cu`](file:///home/jade/Projects/DualSPHysics/src/source/JDsAccInput_ker.cu)), the acceleration applied to fluid particles includes:
   - Euler acceleration: $\vec{\alpha} \times (\vec{r}_i - \vec{r}_{\mathrm{cog}})$
   - Centripetal acceleration: $\vec{\omega} \times (\vec{\omega} \times (\vec{r}_i - \vec{r}_{\mathrm{cog}}))$
   - Coriolis acceleration: $2\vec{\omega} \times (\vec{v}_i - \vec{v}_{\mathrm{lin}})$
3. **Activation Condition Correction**:
   We do **not** claim that the angular branch turns on *only* for nonzero instantaneous $\vec{\alpha}$ if actual velocity also activates. In rotating frame mechanics and in numerical solver architecture, angular inertial forces inherently couple both instantaneous angular acceleration $\vec{\alpha}$ and accumulated angular velocity $\vec{\omega}$. Both participate in frame physics.

### Removal of Mathematically Unjustified Drift Claims
- Prior drafts asserted that imposing zero yaw acceleration ($\alpha_z = 0$) prevents all rotational drift.
- **Mathematical Correction**: In 3D kinematics, finite rotations in $\mathrm{SO}(3)$ are non-commutative. Non-holonomic kinematic coupling between roll ($\omega_x$) and pitch ($\omega_y$) induces orientation/yaw drift over time even if $\omega_z(0) = 0$ and $\alpha_z(t) \equiv 0$ (evident from Euler angle kinematics: $\dot{\psi} = \omega_y \frac{\sin \phi}{\cos \theta} + \omega_z \frac{\cos \phi}{\cos \theta} \neq 0$).
- Any assertion that $\alpha_z = 0$ prevents all rotational drift is mathematically unjustified and has been formally removed.

### Correction of Overbroad Claims Regarding Internal Baffles
- Prior drafts claimed that internal baffles render spatial cell integrals, center-of-mass chords, and free-surface quantiles "mathematically invalid".
- **Mathematical Correction**: Global volumetric quantities like the fluid Center of Mass ($\vec{r}_{\mathrm{COM}} = \frac{1}{M}\int \vec{r}\rho\,dV$) and 1D coordinate quantiles remain mathematically well-defined even with internal baffles.
- However, **event-crossing legality** (such as passage across spatial partition chords, exit tracking, transit thresholds, and wall-normal distance operators) requires an updated internal-wall operator that accounts for internal boundary geometry and non-convex fluid trajectories.
- The disqualification of internal baffles is that event-crossing legality requires an internal-wall operator update that has not been defined or qualified, not that COM or quantiles themselves are mathematically invalid.

### Plain Container Qualification Status
- The plain container is **not yet wholly qualified**. In Root Followup 032 (`root_registered_adaptive_spatial_macro_032`), coarse ($dp=0.010$ m) vs fine ($dp=0.006$ m) exceeded the 5% spatial budget on kinetic energy (6.28%), mean velocity (6.26%), and common support velocity (6.03%).
- Consequently, the campaign remains `Q-N 0/336`, and this proposal is strictly prospective (`claim_status: prospective_proposal_only`).

---

## 4. Retained Root Macro Evidence & Commensurate $dp=0.005$ m Anchor

### Root Followup 032 Retained Negative Macro Evidence
1. **Coarse vs Medium ($0.010$ vs $0.0075$ m)**: **PASS** (max deviation 3.45% on mean velocity, KE 3.18% $\le 5\%$).
2. **Medium vs Fine ($0.0075$ vs $0.0060$ m)**: **PASS** (max deviation 3.12% on KE, mean velocity 2.86% $\le 5\%$).
3. **Coarse vs Fine ($0.010$ vs $0.0060$ m)**: **FAILED (Budget Exceeded)** (KE 6.28%, mean velocity 6.26%, common support velocity 6.03% > 5%).

### Commensurate Fine Reference Anchor ($dp=0.005$ m) Provenance
Root Followup 033 / 034 / 035 established the commensurate fine reference anchor at $dp=0.005$ m:
- **Actual GenCase 033 & QA 034 Receipt Proof**:
  - `native_particles`: **277,272**
  - `native_fluid`: **116,640**
  - `native_fixed`: **160,632**
  - `official_CSV_fluid_mass_sum_kg`: 14.580001 kg (continuous target 14.58 kg)
  - Verified from [`native-initial-qa.json`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_CELL3_LONG_DP005_ADAPTIVE_CFL05_COEF005/root-cell3-dp005-additional-official-native-initial-qa-034/native-initial-qa.json).
- **Nominal Solver 035**: Execution almost completed (telemetry and typed postprocessing underway in Root 036).
- **Strict Boundary**: **DO NOT fabricate future endpoint native proof**. While the nominal reference anchor ($A=1.00$) at $dp=0.005$ m is verified by Gen033/QA034, all future scaled amplitude endpoints ($A=0.90, 0.97, 1.10$) are prospective requests with actual counts, hashes, and solver proofs pending Root dispatch.

---

## 5. Staged Prospective Amplitude Control Domain (All `launch_allowed: false`)

### Discretizations and Physical Invariance
- **Candidate DP**: `0.006 m` (integer grid: $150 \times 30 \times 15$ fluid cells, 67,500 predicted fluid particles).
- **Reference DP**: `0.005 m` (integer grid: $180 \times 36 \times 18$ fluid cells, 116,640 anchor fluid particles).
- **Physical Invariance**: Physical mother geometry ($0.9 \times 0.18 \times 0.51$ m, water depth $0.09$ m, continuum mass $14.58$ kg) and automatic EOS (`hswl auto="true"`, `speedsound auto="true"`) are DP-independent.

### Staged Cases Matrix

| Case ID | Resolution | DP (m) | Amplitude ($A$) | Role | Expected Fluid | GenCase Request | Solver Request |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `F3_CELL3_LONG_DP006_A0P90_ADAPTIVE_CFL05_COEF005` | Candidate | 0.006 | 0.90 | Endpoint Low | 67,500 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/gencase_cpu_dp006_a0p90_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/solver_gpu_dp006_a0p90_request.json) |
| `F3_CELL3_LONG_DP006_A0P97_ADAPTIVE_CFL05_COEF005` | Candidate | 0.006 | 0.97 | Independent Internal | 67,500 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/gencase_cpu_dp006_a0p97_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/solver_gpu_dp006_a0p97_request.json) |
| `F3_CELL3_LONG_DP006_A1P10_ADAPTIVE_CFL05_COEF005` | Candidate | 0.006 | 1.10 | Endpoint High | 67,500 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/gencase_cpu_dp006_a1p10_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/solver_gpu_dp006_a1p10_request.json) |
| `F3_CELL3_LONG_DP005_A0P90_ADAPTIVE_CFL05_COEF005` | Reference | 0.005 | 0.90 | Endpoint Low | 116,640 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/gencase_cpu_dp005_a0p90_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/solver_gpu_dp005_a0p90_request.json) |
| `F3_CELL3_LONG_DP005_A0P97_ADAPTIVE_CFL05_COEF005` | Reference | 0.005 | 0.97 | Independent Internal | 116,640 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/gencase_cpu_dp005_a0p97_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/solver_gpu_dp005_a0p97_request.json) |
| `F3_CELL3_LONG_DP005_A1P10_ADAPTIVE_CFL05_COEF005` | Reference | 0.005 | 1.10 | Endpoint High | 116,640 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/gencase_cpu_dp005_a1p10_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/requests/solver_gpu_dp005_a1p10_request.json) |

All 12 requests enforce `launch_allowed: false`, `q_n_status: not_assessed`, and `production_approval: none`.

---

## 6. Retention of Negative Lagrangian Transport Evidence

- In Root Followup 015/016 (`root-cell3-genuine-adaptive-paired-transport-v3-016`), paired adaptive transport comparison under CFL halving revealed:
  - **1,388 UID particle fate switches** out of 11,215 passage particles (**12.38% switching fraction**).
  - Trajectory tracking of discrete Lagrangian particles across discretizations is inherently ill-posed under turbulent sloshing regimes.
- This negative finding is strictly retained in [`binding.json`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/binding.json) without fabricated CDF gates or artificial chaos bands.

---

## 7. Bounded Resource Estimates & Safety Floors

- **Candidate DP 0.006m**: GenCase ~0.72s / 31MB; Solver ~720s (12.0 min) / 6.2GB storage / 2.8GB VRAM.
- **Reference DP 0.005m**: GenCase ~2.5s / 52MB; Solver ~1,330s (22.2 min) / 10.5GB storage / 4.6GB VRAM.
- **Full Prospective Campaign (6 Cases)**:
  - Projected GPU Wall Time: ~3.42 hours (conservative budget ceiling: 12.0 hours).
  - Projected NVMe Storage: ~66.8 GB (conservative budget ceiling: 105.0 GB).
- **Safety Floors**: Home partition floor $\ge 500$ GiB; Root NVMe floor $\ge 100$ GiB.
- **GPU Protection Policy**: Foreign GPUs (0, 1, 3, 4) strictly isolated; execution allowed only on leased Root-owned GPUs (2, 5, 6, 7).

---

## 8. Verification & Audit

The entire v2 staged prospective package is audited by [`audit_prospective_domain.py`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v2/audit_prospective_domain.py):
1. `binding.json`: Schema `ds02.f3.adaptive-control-domain-prospective.v2`, case definitions, and claim boundaries validated.
2. `definitions/`: All 8 XML definitions validated (CFL 0.05, CoefDtMin 0.005, automatic EOS `hswl auto="true"`, `speedsound auto="true"`).
3. `requests/`: All 12 runner requests validated (`launch_allowed: false`, valid schemas, existing inputs).
4. `transform_forcing.py`: 12 synthetic unit test fixtures passed; pinned nominal forcing digest `6f42660a...` verified.
5. `second_mechanism_proposal.json`: Corrected physics review, removed $\alpha_z$ drift claim, corrected baffle event-crossing legality, and prospective status validated.
6. `resource_estimates.json`: Real receipt data and bounded scaling projections validated.
