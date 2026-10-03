# F3 Adaptive Control Domain Prospective Staging (v1)

**Handoff Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1`  
**Campaign**: DS-DATA-02  
**Family**: F3 (Open-Top Rectangular Tank Sloshing)  
**Authority**: Root Followup 035 Continuation under F3 isolated worktree `ds-data-02-f6` (Gemini 3.8 Flash High as launcher)  
**Governance & Claim Boundary**: Entire control domain is `prospective`. `launch_allowed: false`, `q_n_status: not_granted`, `production_approval: none`. Nothing launchable without Root review.

---

## 1. Executive Summary & Root Macro Evidence Audit

In **Root Followup 032** (`root_registered_adaptive_spatial_macro_032`), Root audited the 3-DP spatial ladder (`0.010m`, `0.0075m`, `0.006m`) under genuine adaptive timestepping (`CFL=0.05`, `CoefDtMin=0.005`) across the full `[0.0, 8.35]` s window against the frozen 5% spatial reference budget across all 7 protocol metrics:

1. **Coarse vs Medium (`0.010m` vs `0.0075m`)**: **PASS**  
   - Maximum deviation: `0.034487` (3.45%, governing metric: `mean_velocity_over_U`).  
   - Kinetic energy deviation: `0.031775` (3.18%). All 7 metrics strictly within 5% budget.
2. **Medium vs Fine (`0.0075m` vs `0.0060m`)**: **PASS**  
   - Maximum deviation: `0.031241` (3.12%, governing metric: `energy_difference`).  
   - Mean velocity deviation: `0.028642` (2.86%). All 7 metrics strictly within 5% budget.
3. **Coarse vs Fine (`0.010m` vs `0.0060m`)**: **FAILED (Budget Exceeded)**  
   - Kinetic energy deviation (`energy_difference`): `0.062779` (6.28% > 5.0%).  
   - Mean velocity deviation (`mean_velocity_over_U`): `0.062644` (6.26% > 5.0%).  
   - Common support local velocity (`common_support_velocity_over_U`): `0.060270` (6.03% > 5.0%).  
   - **Verdict**: Whole Q-N qualification is NOT granted; production approval remains `none`.

Consequently, Root initiated **Root Followup 033** (`root_additional_commensurate_adaptive_input_033`) to introduce a commensurate finer reference at **`dp = 0.005m`** (`F3_CELL3_LONG_DP005_ADAPTIVE_CFL05_COEF005`), preserving the physical mother geometry (`0.9 x 0.18 x 0.51 m`, water depth `0.09 m`) and configured automatic EOS (`hswl auto="true"`, `speedsound auto="true"`). All future particle counts, EOS parameters $B$ and $h$, and hashes remain predictions until actual GenCase execution by Root.

---

## 2. Staged Prospective Amplitude Control Domain

Per `F3-CELL3-PROTOCOL.json`, this module stages the prospective amplitude control domain spanning endpoint and internal amplitudes across candidate and reference discretizations:
- **Candidate DP**: `0.006 m`
- **Reference DP**: `0.005 m`
- **Control Amplitudes**:
  - Endpoint Low: $A = 0.90$
  - Independent Internal: $A = 0.97$
  - Endpoint High: $A = 1.10$
  - (Nominal Anchor: $A = 1.00$, previously anchored in Root 028 and Root 033)

### Zero-Drive Gravity Relation & Version-Physics Forcing
All scaled forcing files obey the exact zero-drive body acceleration relation defined in the frozen protocol:
$$\vec{a}_{\mathrm{lin}}(t) = \vec{g} + A \cdot (\vec{a}_{\mathrm{nom}}(t) - \vec{g})$$
$$\vec{\alpha}(t) = A \cdot \vec{\alpha}_{\mathrm{nom}}(t)$$
where $\vec{g} = (0.0, 0.0, -9.81)\ \mathrm{m/s^2}$, and nominal zero drive is $\vec{a}_{\mathrm{lin}} = (0, 0, -9.81)\ \mathrm{m/s^2}$, $\vec{\alpha} = (0, 0, 0)\ \mathrm{rad/s^2}$.

### Solver Kinematics & GPU Frame Mechanics
- **Native Right-Endpoint Integration**: As implemented in official DualSPHysics [`JDsAccInput.cpp`](file:///home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source/JDsAccInput.cpp#L250-L265), velocities are integrated natively at step $k$:
  $$\vec{v}_{\mathrm{lin}}[k] = \vec{v}_{\mathrm{lin}}[k-1] + \vec{a}_{\mathrm{lin}}[k] \cdot (t[k] - t[k-1])$$
  $$\vec{v}_{\mathrm{ang}}[k] = \vec{v}_{\mathrm{ang}}[k-1] + \vec{\alpha}[k] \cdot (t[k] - t[k-1])$$
  followed by linear interpolation between discrete CSV records.
- **GPU Coriolis Frame Physics**: As implemented in official [`JDsAccInput_ker.cu`](file:///home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source/JDsAccInput_ker.cu), rotating frame terms (Euler, Coriolis, centrifugal) are calculated explicitly per-component on GPU. No rigid-frame approximations or external kinematic overrides are introduced.
- **Pinned Nominal Forcing SHA256**: `6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3` (`CaseSloshingAccData.csv`, 167,001 rows, window `[0.0, 8.35]` s).
- **Pure Standard-Library Transformer**: Provided in [`transform_forcing.py`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/transform_forcing.py). Large CSV arrays are **NOT** materialized or committed to git, avoiding repository bloat.

### Staged Cases (All `launch_allowed: false`)

| Case ID | Resolution | DP (m) | Amplitude ($A$) | Role | Expected Fluid Particles | GenCase Request | Solver Request |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `F3_CELL3_LONG_DP006_A0P90_ADAPTIVE_CFL05_COEF005` | Candidate | 0.006 | 0.90 | Endpoint Low | 67,500 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/gencase_cpu_dp006_a0p90_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/solver_gpu_dp006_a0p90_request.json) |
| `F3_CELL3_LONG_DP006_A0P97_ADAPTIVE_CFL05_COEF005` | Candidate | 0.006 | 0.97 | Independent Internal | 67,500 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/gencase_cpu_dp006_a0p97_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/solver_gpu_dp006_a0p97_request.json) |
| `F3_CELL3_LONG_DP006_A1P10_ADAPTIVE_CFL05_COEF005` | Candidate | 0.006 | 1.10 | Endpoint High | 67,500 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/gencase_cpu_dp006_a1p10_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/solver_gpu_dp006_a1p10_request.json) |
| `F3_CELL3_LONG_DP005_A0P90_ADAPTIVE_CFL05_COEF005` | Reference | 0.005 | 0.90 | Endpoint Low | 116,640 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/gencase_cpu_dp005_a0p90_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/solver_gpu_dp005_a0p90_request.json) |
| `F3_CELL3_LONG_DP005_A0P97_ADAPTIVE_CFL05_COEF005` | Reference | 0.005 | 0.97 | Independent Internal | 116,640 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/gencase_cpu_dp005_a0p97_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/solver_gpu_dp005_a0p97_request.json) |
| `F3_CELL3_LONG_DP005_A1P10_ADAPTIVE_CFL05_COEF005` | Reference | 0.005 | 1.10 | Endpoint High | 116,640 | [GenCase Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/gencase_cpu_dp005_a1p10_request.json) | [Solver Req](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/requests/solver_gpu_dp005_a1p10_request.json) |

---

## 3. Second Mechanism Scientific Proposal (Bounded 2-Axis Acceleration)

Per task instructions, we propose **one scientifically distinct second physical mechanism background** without authoring or launching unreviewed control:

### Disqualification of Internal Baffles
- **Internal Wall Geometry**: Introducing an internal baffle (vertical, inclined, or perforated) introduces interior solid boundary surfaces dividing the fluid domain.
- **Invalidation of Plain Observation Operator**: The frozen observation operator (`f3_legacy_plain_full_transport_config.v1.json`, `f3_observation_v2.py`) was formulated specifically for an unobstructed 5-wall rectangular box. Its spatial cell integrals, center-of-mass chords, free-surface quantiles ($q_{90}$ over length), and fluid partition zones assume convex fluid paths.
- **Physical Boundary Layer Artifacts**: An internal wall introduces internal contact lines, wetting hysteresis, local singular shear, artificial wake turbulence, and geometric shadow zones where the plain rectangular integration operator yields non-physical artifacts. Blind reuse of the plain operator on a baffled container is mathematically and scientifically invalid.

### Proposed Legitimate Mechanism: Bounded Two-Axis Physical Acceleration
- **Domain Parity**: The container remains the exact identical plain 5-wall open-top rectangular tank ($0.9 \times 0.18 \times 0.51$ m, depth $0.09$ m). The observation operator remains topologically and geometrically valid without internal wall artifacts.
- **Coupled 3D Kinematics**:
  - Linear acceleration: $\vec{a}_{\mathrm{lin}}(t) = (a_x(t), a_y(t), a_z(t))$ with $a_y(t)$ providing a bounded transverse excitation, and $a_z(t) = -9.81\ \mathrm{m/s^2}$.
  - Angular acceleration: $\vec{\alpha}(t) = (\alpha_x(t), \alpha_y(t), 0)$, coupling pitch (around Y) and roll (around X) with zero yaw to prevent rotational drift.
  - Zero initial conditions: $\vec{v}(0) = \vec{0}$, $\vec{\omega}(0) = \vec{0}$, with a smooth $C^2$ envelope on transverse excitation.
- **Solver Kinematics & Coriolis Mechanics**:
  - `JDsAccInput.cpp` parses the 7-column CSV and integrates linear and angular velocities natively.
  - `JDsAccInput_ker.cu` activates the full 3D inertial acceleration kernel whenever any angular acceleration component is nonzero, computing exact Coriolis ($2\vec{\omega} \times \vec{v}_{\mathrm{rel}}$), Euler ($\dot{\vec{\omega}} \times \vec{r}$), and centrifugal ($\vec{\omega} \times (\vec{\omega} \times \vec{r})$) accelerations without modifying solver binaries.
- **New Observables & Event Coverage**:
  - Coupled longitudinal ($f_{1,0}$) and transverse ($f_{0,1}$) sloshing modes generating 3D swirling waves, diagonal wave runup, and lateral wall pressure peaks.
  - Kinetic energy decomposition: $E_k(t) = E_{kx}(t) + E_{ky}(t) + E_{kz}(t)$.
  - True 3D Lagrangian transport and transverse mixing across the $Y=0$ centerline.
  - Requirement for bilateral transverse surface elevation gauges at $Y = \pm 0.08$ m.
- **Baseline Study Requirements Before Control Authorization**:
  - Commensurate spatial convergence ladder ($dp = 0.0075, 0.006, 0.005$ m).
  - Genuine adaptive timestepping verification ($CFL=0.05$ vs $0.025$ with $CoefDtMin=0.005$) confirming zero minimum-timestep clamping.
  - 8.35s full-window macro energy, momentum, and free-surface boundary evaluation within 5% budget.
- **Separation from Amplitude Controls**: Amplitude scaling variations ($A \in \{0.90, 0.97, 1.10\}$) belong strictly to Mechanism 1 and are **NOT** counted as Mechanism 2.

---

## 4. Retention of Prior Negative Lagrangian Transport Evidence

In Root Followup 015/016 (`root-cell3-genuine-adaptive-paired-transport-v3-016`), genuine adaptive paired transport comparison between baseline ($CFL=0.05, CoefDtMin=0.005$) and half-CFL ($CFL=0.025, CoefDtMin=0.0025$) revealed:
- **1,388 UID particle fate switches** at $t = 8.35$ s out of 11,215 jointly observed passage particles (**12.38% switching fraction**).
- Individual Lagrangian particle trajectories exhibit high sensitivity to numerical timestep discretization in turbulent sloshing regimes, proving that discrete UID trajectory pairing across discretizations is ill-posed.
- **Negative Evidence Policy**: This negative finding is strictly retained in the dataset documentation and [`binding.json`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/binding.json). No artificial CDF gates, chaos bands, or synthetic containment metrics are fabricated.

---

## 5. Bounded Resource Estimates (Based on Recent Receipts)

Derived directly from actual execution receipts of `dp = 0.006m` (`F3_CELL3_LONG_DP006_ADAPTIVE_CFL05_COEF005`, Root 028–031) and `dp = 0.0075m` (`root-cell3-adaptive-floor-native-transport-labels-014`):

### Per-Case Actuals & Projections

| Stage | Candidate DP 0.006m (67.5k fluid) | Reference DP 0.005m (116.6k fluid) | Bounded Limit Budget | Resource Type |
| :--- | :---: | :---: | :---: | :---: |
| **GenCase** | 0.72 s / 31 MB | ~2.2 s / ~52 MB | $\le 300\ \mathrm{s}\ /\ 512\ \mathrm{MB}$ | 2 CPU threads |
| **Native Solver (GPU)** | 720.06 s (12.0 min) / 6.2 GB / 2.8 GB VRAM | ~1,330 s (22.2 min) / 10.5 GB / 4.6 GB VRAM | $\le 7,200\ \mathrm{s}\ /\ 16\ \mathrm{GB}\ /\ 8\ \mathrm{GB}\ \mathrm{VRAM}$ | 1 GPU (Leased 2, 5, 6, or 7) + 4 CPU threads |
| **Converter (NVMe Typed)** | 196.67 s (3.3 min) / 2.4 GB | ~380 s (6.3 min) / ~4.2 GB | $\le 1,200\ \mathrm{s}\ /\ 6\ \mathrm{GB}$ | 2 CPU threads |
| **Transport Labels** | ~135 s (2.3 min) / ~30 MB | ~260 s (4.3 min) / ~50 MB | $\le 900\ \mathrm{s}\ /\ 100\ \mathrm{MB}$ | 2 CPU threads |

### Full Prospective Campaign (6 Cases)
- **Total Projected GPU Wall Time**: ~3.42 hours (bounded safe ceiling: 12.0 hours).
- **Total Projected NVMe Storage**: ~66.8 GB (bounded safe ceiling: 105.0 GB).

---

## 6. Audit & Validation

The entire staged prospective package has been audited and verified via [`audit_prospective_domain.py`](file:///home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/adaptive_control_domain_prospective_v1/audit_prospective_domain.py):
- `binding.json`: Schema, claim boundaries, and 6 case definitions verified.
- `definitions/`: All 8 XML definitions conform to protocol, CFL=0.05, CoefDtMin=0.005, and automatic EOS.
- `requests/`: All 12 runner requests verified with `launch_allowed: false`, `q_n_status: not_assessed`, and valid input paths.
- `transform_forcing.py`: Zero-drive self-test verified; nominal forcing digest `6f42660a...` pinned.
- `second_mechanism_proposal.json`: Baffle exclusion and 2-axis proposal fully structured.
- `resource_estimates.json`: Real receipt data and bounded scaling factors verified.

---

## 7. Next Executable Tasks

1. **Root Followup Review**: Submit `adaptive_control_domain_prospective_v1` for Root review and architectural qualification.
2. **Commensurate dp=0.005m Baseline Execution**: Await Root completion of `root_additional_commensurate_adaptive_input_033` (actual GenCase, native solver run, and 4-way spatial ladder audit).
3. **Guarded Control Generation**: Upon Root authorization, execute `transform_forcing.py` to generate the 3 amplitude CSV files under Root dispatch.
4. **Prospective Qualification Runs**: Schedule CPU GenCase and GPU solver requests via Root strict dispatcher respecting GPU lease and atomic budget policies.
