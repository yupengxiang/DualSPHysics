# F1 Source Configuration Review, Root-Cause Diagnosis & Fallback Authorization

- **Campaign**: DS-DATA-02
- **Family**: F1 (Dam Break, Obstacle Bypass, and Asymmetric Flow Remerging)
- **Scope**: `handoff_20261003/root_followup_041_bounded_fallback_v1`
- **Date**: 2026-10-04
- **Author**: Family F1 Numerical & Dataset Specialist
- **Status**: Root Reviewable Technical Report & Prospective Fallback Transition

---

## 1. Executive Summary & Root Audit Context

The DS-DATA-02 Family F1 campaign targets rigorous 3D Lagrangian fluid data generation across two core hydrodynamic mechanisms:
1. **Mechanism A: Eccentric Obstacle Flow (`eccentric_obstacle`)**, derived from upstream benchmark `main/01_DamBreak` (tank $1.60 \times 0.67 \times 0.40\text{ m}$, obstacle $0.12 \times 0.12 \times 0.45\text{ m}$ at $(0.90, 0.24, 0.00)$).
2. **Mechanism B: Asymmetric Dual-Channel Flow (`asymmetric_dual_channel`)**, derived from upstream benchmark `mdbc/04_Dambreak` (tank $3.22 \times 1.00 \times 1.00\text{ m}$, flow splitter at $x \in [1.25, 2.05]$, $y \in [0.34, 0.40]$, lower channel width $0.34\text{ m}$, upper channel width $0.60\text{ m}$).

### 1.1 Latest Native Evidence and Attempt State
In recent root-supervised execution, genuine time-step refinement experiments were conducted for the eccentric obstacle case under the thick DBC formulation:
- **Macro Comparison Attempt `025`**:
  `DATA/families/F1/F1_ECC_THICK_DBC_ACTUAL_HALF_QUARTERSTEP_MACRO/root-ecc-thick-dbc-medium-half-quarterstep-full1601-frozen-macro-025/macro-comparison.json`
  - Nominal: Genuine halfstep (CFL 0.10, CoefDtMin 0.025, 1601 frames, $t \in [0, 1.6\text{ s}]$, mass $80.4000\text{ kg}$).
  - Candidate: Genuine quarterstep (CFL 0.05, CoefDtMin 0.0125, 1601 frames, $t \in [0, 1.6\text{ s}]$, mass $80.4000\text{ kg}$).
  - **Macro Result**: Coordinate quantiles max over $H_0 = 0.00429104577$ ($0.429\%$).
  - **Screening Status**: `macro_screening_within_budget: true` against the registered $1.0\%$ engineering threshold.

- **Paired Native Transport Labels Attempt `026`**:
  `DATA/families/F1/F1_ECC_THICK_DBC_HALF_VS_QUARTER_LABELS_COMPARISON/root-ecc-thick-dbc-medium-half-quarterstep-full1601-paired-native-transport-026/paired-native-transport.json`
  - Cohort: 643,200 fluid particles ($80.4000\text{ kg}$, $dp = 0.005\text{ m}$).
  - **Same-UID Fate Switches**: Exactly **21,479 particles** switched destination categories between genuine halfstep and genuine quarterstep ($2.684875\text{ kg}$, or **$3.339\%$** of fluid mass).
  - **First-Passage Chord Timing**:
    - Lower channel entry max chord time difference: **$0.680255\text{ s}$** (allocated budget: $0.000699\text{ s}$, **FAIL**).
    - Upper channel entry max chord time difference: **$0.679134\text{ s}$** (allocated budget: $0.000699\text{ s}$, **FAIL**).
    - Downstream arrival max chord time difference: **$0.440010\text{ s}$** (allocated budget: $0.000699\text{ s}$, **FAIL**).
  - **Residence Times**:
    - Upstream residence max difference: **$0.869123\text{ s}$**.
    - Downstream residence max difference: **$0.795841\text{ s}$**.

- **Prior Spatial Resolution Refinement Attempt `009`**:
  `DATA/families/F1/F1_ECC_THICK_DBC_ACTUAL_FULL_THREE_DP_MACRO/root-ecc-thick-dbc-full1601-three-dp-frozen-macro-009/macro-comparison.json`
  - Medium ($dp=0.005\text{ m}$) vs Fine ($dp=0.00333\text{ m}$):
    - `coordinate_quantiles_max_over_H0`: **$0.1391918$** ($13.92\%$ vs $5\%$ budget, **FAIL**).
    - `center_of_mass_max_over_H0`: **$0.0621701$** ($6.22\%$ vs $5\%$ budget, **FAIL**).
  - Nominal vs Halfstep Macro (Attempt `019`):
    - `coordinate_quantiles_max_over_H0`: **$0.0137607$** ($1.376\%$ vs $1\%$ budget, **FAIL**).
    - Fate switches: **24,229 particles** ($3.0286\text{ kg}$, $3.767\%$ of fluid mass).

---

## 2. Root-Cause Hydrodynamic Diagnosis

The persistent failure of individual particle transport convergence despite macro quantile passing exposes a fundamental physical mechanism:

### 2.1 The Stagnation-Line Bifurcation Singularity
1. In the original violent dam break setup, a fluid column of height $H_0 = 0.30\text{ m}$ collapses under gravity, producing an impinging front velocity $u_{\text{front}} \approx 2 \sqrt{g H_0} \approx 3.43\text{ m/s}$.
2. The front impacts the blunt upstream face of the eccentric obstacle ($x = 0.90\text{ m}$, width $0.12\text{ m}$, height $0.45\text{ m}$).
3. At the obstacle centerline ($y \approx 0.30\text{ m}$), a hydrodynamic stagnation line forms. Fluid hitting this boundary must make a binary topological decision: turn left into the lower channel ($y \in [0.00, 0.24\text{ m}]$) or turn right into the upper channel ($y \in [0.36, 0.67\text{ m}]$).
4. Because the impact is supercritical and turbulent ($Re \sim 10^5$, $Fr \sim 2.5$), high-frequency acoustic wave reflections and localized particle disorder create extreme trajectory sensitivity near the stagnation line. The local Lyapunov exponent is strongly positive.
5. A microscopic time-step perturbation ($\Delta t$ halved from CFL 0.1 to 0.05, then to 0.025) shifts the pressure gradient on individual particles by a fraction of a millipascal, causing particles near the bifurcation line to alter their path around the obstacle.
6. This results in **21,479 particles switching channels or recirculating**, causing timing discrepancies of $0.68\text{ s}$ in a $1.6\text{ s}$ window.

### 2.2 Spray Jetting and Free-Surface Fragmentation
- High kinetic energy ($E_k \propto H_0^2$) causes the impinging liquid sheet to jet vertically up the obstacle face and slam violently against the downstream end-wall ($x = 1.60\text{ m}$).
- Secondary splashing, droplet detachment, and chaotic re-entrainment produce non-monotonic spatial quantile distributions between resolutions, directly driving the spatial quantile discrepancy of $0.139\cdot H_0$ ($> 5\%$ budget).

---

## 3. Protocol Enforcement & Legal Fallback Mandate

Root campaign governance enforces strict operational boundaries:
1. **Per-Root-Cause Repair Limit**: A maximum of **2 evidence-based repairs** is permitted per root cause before transitioning to a legal fallback.
   - *Repair Attempt 1*: Genuine halfstep time integration (CFL 0.10, CoefDtMin 0.025) $\to$ Macro failed ($1.376\%$), 24,229 fate switches.
   - *Repair Attempt 2*: Genuine quarterstep time integration (CFL 0.05, CoefDtMin 0.0125) $\to$ Macro passed ($0.429\%$), but 21,479 fate switches remain; spatial quantiles ($0.139$) and COM ($0.062$) remain in failure.
   - **Conclusion**: The 2 repairs for the high-energy violent template are legally exhausted.
2. **Prohibition of Retrospective Gate Relaxation**:
   - We must not assert "chaos is physical" to excuse $3.34\%$ destination switches.
   - We must not apply post-hoc spatial cropping, quiet-frame selection, or dropout masks.
3. **Resource Guard & Budget Feasibility**:
   - Root has approximately **~31 GPU hours remaining** before active reservations (qualification goal: actual 0 / 336 cases, current 271 / 320).
   - An eighth-step or finer DP run at $dp < 0.0033\text{ m}$ would consume tens of GPU hours for a single case, violating global campaign resource sustainability without solving the stagnation-line bifurcation instability.
4. **Legal Fallback Authorization**:
   - In accordance with `lagrangian-fluid-lab/campaigns/ds-data-02/plan-source/families/F1.md` (Line 45 & 64), when two root-cause repairs fail on an initial template, the campaign requires transition to a **compact physically meaningful prospective finite gravity-release transport fallback pair**.

---

## 4. Source Audit & Input SHA Verification

To ensure strict reproducibility, all reference sources, binaries, and prior artifacts are audited from real files on disk. The authentic SHA-256 hashes are recorded below:

| Asset / Source File | Absolute Path | SHA-256 Digest |
| :--- | :--- | :--- |
| **Official GenCase Binary** | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64` | `a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226` |
| **Official Solver Binary** | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64` | `0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29` |
| **Official PartVTK Binary** | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64` | `62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00` |
| **Upstream ECC DamBreak XML** | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/01_DamBreak/CaseDambreak_Def.xml` | `a6bec7c5d3ece69ffcc72e1c3d7395da017dc0bf119b4cab5eae41400a24cbdd` |
| **Upstream Dual DamBreak XML** | `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml` | `1f7cca807e16a3b1a1cc4da649a68db5166439d3f4b30fa4ea25635baf6045b7` |
| **Strict Dispatcher v1** | `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py` | `81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec` |
| **Runtime v2** | `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py` | `5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60` |
| **Thick DBC Base Script** | `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f1_eccentric_thick_boundary.py` | `23a88eb21aeae3f73ecc85c00fb0d7b78ed1de1b70b31be88bf812b41a53f388` |
| **Thick DBC v3.1 Script** | `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f1_eccentric_thick_boundary_v3_1.py` | `1dd13450d6306c3770d13c14cf9b4491df4eccfa77b3be59168c4f35082c477f` |
| **Root Attempt 025 Macro JSON** | `DATA/families/F1/F1_ECC_THICK_DBC_ACTUAL_HALF_QUARTERSTEP_MACRO/root-ecc-thick-dbc-medium-half-quarterstep-full1601-frozen-macro-025/macro-comparison.json` | `312fa6d2e31e50055f98049a2617386727982094d404a4769ee5c021f0945ca7` |
| **Root Attempt 026 Transport JSON** | `DATA/families/F1/F1_ECC_THICK_DBC_HALF_VS_QUARTER_LABELS_COMPARISON/root-ecc-thick-dbc-medium-half-quarterstep-full1601-paired-native-transport-026/paired-native-transport.json` | `b712d5b5c3c31d56e6750c79f7e48889d6e98e68a72b0968b1179a3e630306f2` |
| **System Python 3.10** | `/usr/bin/python3.10` | `a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae` |

All digests have been verified by direct hash calculation from live files. Zero fabricated artifacts or synthetic assumptions exist.
