# DS-DATA-02 Family F1: Genuine Quarterstep Prospective Clone and Canonical Nominal-vs-Half Native Labels Comparison (Round 036)

- **Date**: 2026-10-04
- **Family**: F1 (Dam Break with Eccentric Obstacle, Thick Boundary DBC)
- **Worktree**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`
- **Scope Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1`
- **Model**: Gemini 3.8 Flash (High) (authorized by User, overriding legacy Luna metadata)
- **Authorizing Request**: DS-DATA-02 ROOT FOLLOWUP 036 F1
- **Status**: `launch_allowed: false` across all requests; Q-N `not_granted`; production `none`.

---

## 1. Executive Summary & Authoritative Invariants

In accordance with root followup 036 F1 instructions and [AGENTS.md](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/AGENTS.md):
1. **Isolated Worktree Ownership**: Work is performed exclusively within the assigned isolated worktree without recursive delegation, solver launches, GenCase executions, array analysis runs, resource ledger writes, main merges, or production approval claims.
2. **Read Actual Evidence**: Examined Root's genuine halfstep terminal evidence in `root_actual_genuine_halfstep_frozen_macro_019` and `macro-comparison.json`.
3. **Negative Finding Recorded**: Under the frozen 1% time allocation (`macro_budget = 0.01`), halfstep vs nominal **FAILED** coordinate quantiles (`0.013760724309613467`), while Center of Mass (`0.0011531225598928007`) and Kinetic Energy (`0.000875883608976671`) passed. Thresholds are strictly preserved, no relabeling of temporal pass is allowed, and no exclusive causal attribution is asserted.
4. **Prospective Quarterstep Clone Transformer**: Implemented `clone_transformer.py` transforming actual halfstep execution inputs (`prepared012`: CFL 0.1, CoefDtMin 0.025) to prospective quarterstep (CFL 0.05, CoefDtMin 0.0125). Invariants enforced include untouched historical `<casedef>`, byte-identical BI4, and whole-XML reverse-bytes recovery.
5. **Prospective Macro Comparison**: Configured half-vs-quarter full-window [0, 1.6] s comparison using the original `compare_pair` operator with identical 1% time allocation, native mass $M=80.4\text{ kg}$, $H_0=0.3\text{ m}$, and weighted quantiles $[0.05, 0.5, 0.95]$.
6. **Canonical Nominal-vs-Half Native Labels Comparison**: Authored `f1_nominal_vs_half_native_labels_comparison.py` to compare UID-paired first passage, residence time, censor codes, and destination fate switches using canonical `native-labels.h5` from nominal attempt 004 (labels001) and halfstep attempt 018 (evidence018). Preserves exact source physical mother `b61c7f08...`, native mass weights, and unknown exclusions, while exhaustively reporting fate transitions without invented CDFs or chaos gates.
7. **Empirically Bounded Resources**: Bounded resource allocations using actual `realhalf013` execution facts (`elapsed: 250.627 s`, `70,174 steps`, `DTsMin: 0`), explicitly refuting naive nominal $2\times$ assumptions.

---

## 2. Halfstep Terminal Evidence Audit (`root_actual_genuine_halfstep_frozen_macro_019`)

The terminal macro comparison artifact was audited from:
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_ACTUAL_GENUINE_HALFSTEP_MACRO/root-ecc-thick-dbc-medium-genuine-halfstep-full1601-frozen-macro-019/macro-comparison.json`

### Terminal Metrics Table (Halfstep vs Nominal)

| Observable / Quantity | Normalized Form | Value | Frozen Budget | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Coordinate Quantiles** | $\max \|q_{\text{half}} - q_{\text{nom}}\| / H_0$ | **`0.013760724309613467`** | `0.01` (1%) | **FAILED** |
| **Center of Mass** | $\max \|\text{COM}_{\text{half}} - \text{COM}_{\text{nom}}\| / H_0$ | **`0.0011531225598928007`** | `0.01` (1%) | **PASS** |
| **Kinetic Energy** | $\max \|\text{KE}_{\text{half}} - \text{KE}_{\text{nom}}\| / (M g H_0)$ | **`0.000875883608976671`** | `0.01` (1%) | **PASS** |
| **Mean Velocity** | $\max \|v_{\text{half}} - v_{\text{nom}}\|$ | `0.007356036064143676 m/s` | descriptive | N/A |
| **Initial Fluid Mass** | $M_{\text{numerical}}$ | `80.40000381879508 kg` | $|M - 80.4| \le 0.05$ | **PASS** |
| **Overall Macro Screening** | $\max(\text{COM}, \text{Quantiles}, \text{KE})$ | `0.013760724309613467` | `0.01` | **FAILED** |
| **Scientific Q-N Status** | Q-N Qualification | `"not_granted"` | N/A | **not_granted** |

### Policy Mandate on Negative Outcome
1. **Threshold Integrity**: The 1% time allocation threshold ($0.01$) must NOT be relaxed to 1.5% or 2% to force a pass.
2. **No Temporal Relabeling**: The halfstep result remains a recorded failure of temporal coordinate quantiles.
3. **No Exclusive Causal Attribution**: Observed discrepancies must not be causally attributed solely to time-step sensitivity or boundary standoff without independent evidence.

---

## 3. Genuine Quarterstep Prospective Clone Transformer

### Architecture & Input Derivation
The quarterstep candidate is derived directly from the audited halfstep input preparation `prepared012`:
- Source XML: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001/root-ecc-thick-dbc-medium-halfstep-execution-constants-input-preparation-012/prepared/F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001.xml` (SHA-256: `3b9358eeb662327acc08f311cb9c1975b1820113d9f7e1089e7296de91eda863`)
- Source BI4: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001/root-ecc-thick-dbc-medium-halfstep-execution-constants-input-preparation-012/prepared/F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001.bi4` (SHA-256: `054c3a44e61e7a34394234944b4b0ed367eea18d6fe15c2242b7fa6eeb2c0a1a`)
- Target Case ID: `F1_ECC_THICK_DBC_MEDIUM_GENUINE_QUARTER_CFL001`

### Mathematical Parameter Transitions

$$\text{CFL}: 0.1 \longrightarrow 0.05 \quad (\text{baseline nominal was } 0.2)$$

$$\text{CoefDtMin}: 0.025 \longrightarrow 0.0125 \quad (\text{baseline nominal was } 0.05)$$

### Enforcement of Stringent Invariants
1. **Historical `<casedef>` Untouched**: The historical definition subtree contains `<cflnumber value="0.2" />` and particle counts. It is isolated from `<execution>` and verified byte-for-byte unmodified (`new_text.startswith(head) is True`).
2. **Whole-XML Reverse-Bytes Assertion**:
   Reverting `<cflnumber value="0.05" />` $\to$ `0.1` and `<parameter key="CoefDtMin" value="0.0125" />` $\to$ `0.025` on the output XML string strictly recovers `restored_text == source_text`.
3. **Discrete Initial Lattice Byte-Identity**:
   The initial particle lattice (`.bi4`) is copied byte-identically with SHA-256 `054c3a44e61e7a34394234944b4b0ed367eea18d6fe15c2242b7fa6eeb2c0a1a`, preserving 1,032,852 total particles and 643,200 fluid particles.
4. **Physical Parameters**:
   - $DP = 0.005\text{ m}$
   - Window: $t \in [0.0, 1.6]\text{ s}$
   - Output cadence: $t_{\text{out}} = 0.001\text{ s}$ (1,601 frames)

---

## 4. Bounded Resource Ledger & Refutation of Nominal 2x Assumptions

### Empirical Solver Evidence (`realhalf013`)
From `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001/root-ecc-thick-dbc-medium-genuine-halfstep-full1601-native-013/`:
- **Elapsed Wall Seconds**: `250.62711460795254 s`
- **GPU Seconds**: `250.62711460795254 s`
- **Total Integration Steps**: `70,174 steps` (`70,173` in Run.csv)
- **Timesteps Adjusted to DtMin (`DTs adjusted to DtMin`)**: `0`
- **Initial Time Step (`DtIni`)**: `0.000254539 s`
- **Minimum Time Step (`DtMin`)**: `6.363487e-06 s`
- **Particles**: 1,032,852 total (643,200 fluid, 389,652 fixed boundary)
- **Native Frames Saved**: 1,601

### Mathematical Refutation of Nominal $2\times$ Assumptions
- Baseline nominal solver GPU runtime: `168.176 s` (~43,000 steps).
- Actual halfstep GPU runtime: `250.627 s` (70,174 steps).
- Scaling ratio:
  $$\frac{T_{\text{half}}}{T_{\text{nom}}} = \frac{250.627}{168.176} \approx 1.490 \ne 2.0$$
- **Physical Reason**: SPH variable time-stepping is bounded by:
  $$\Delta t \le \text{CFL} \cdot \frac{h}{c_s + \|\mathbf{v}\|_{\max}}$$
  Because fluid velocity profiles and local density fluctuations evolve dynamically across frames, the actual step size distribution does not halve uniformly across all phases. Furthermore, `DTs adjusted to DtMin` was exactly `0`, proving that execution was nowhere clamped by the artificial numerical floor.
- Therefore, naively assuming that halfstep requires $2\times$ nominal ($336\text{ s}$) or that quarterstep requires $4\times$ nominal ($672\text{ s}$) is scientifically ungrounded.

### Bounded Quarterstep Resource Budget
- **Expected Steps Range**: $[130,000, 155,000]$ steps
- **Estimated Solver Wall Time**: $\sim 500\text{--}600\text{ s}$
- **Conservative Ceiling (`max_wall_seconds`)**: `1800 s` (30 min)
- **Scratch Storage Reservation**: `107,374,182,400 bytes` (~100 GiB for 1,601 frames of typed native states)
- **Peak GPU Memory**: `8,192 MiB` on RTX 6000 Ada

---

## 5. Canonical Nominal-vs-Half Native Labels Comparison

Script: [f1_nominal_vs_half_native_labels_comparison.py](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/f1_nominal_vs_half_native_labels_comparison.py)

### Canonical Source Artifacts
1. **Nominal Medium Labels** (located via `f1_ecc_medium_native_labels_001` request):
   - Case ID: `F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005`
   - Attempt ID: `root-ecc-thick-dbc-medium-native-labels-004`
   - Path: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/root-ecc-thick-dbc-medium-native-labels-004/native-labels.h5`
   - Exact Standalone Bytes: `44,588,439` (from execution-summary-errata.json)
   - SHA-256: `f9745431ca7f16e2780264303fcb8ef180c76bb1afff21fc247851a4bfa4a959`
2. **Halfstep Medium Labels** (evidence018):
   - Case ID: `F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001`
   - Attempt ID: `root-ecc-thick-dbc-medium-halfstep-full1601-singlecopy-native-evidence-018`
   - Path: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001/root-ecc-thick-dbc-medium-halfstep-full1601-singlecopy-native-evidence-018/native-labels.h5`
   - Exact Standalone Bytes: `44,373,342`
   - SHA-256: `9d18bfe49004d22d17f191e295f640c9806f9a2142fb059f538e852ab29c3291`
3. **Physical Mother Condition**:
   - Condition SHA-256: `b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb`

### Mathematical Comparison Formulation
Both label datasets share the identical typed particle cohort:
- Total particles: $1,032,852$
- Fluid cohort: $643,200$ particles, paired directly by $\text{UID} = (\text{particle\_zone}, \text{particle\_id})$.
- Native float32 mass weight: $m_i = 0.0001250000059371814\text{ kg}$, total $M_{\text{fluid}} = 80.40000381879508\text{ kg}$.

#### A. First Passage Timing & Censoring
For each event $e \in \{\text{lower\_channel\_entry}, \text{upper\_channel\_entry}, \text{downstream\_arrival}\}$:
- **Censor Partition**: Particles are partitioned into 4 disjoint subsets:
  1. Both observed: $c_{\text{nom}} = 0 \land c_{\text{half}} = 0$
  2. Nominal only: $c_{\text{nom}} = 0 \land c_{\text{half}} \ne 0$
  3. Halfstep only: $c_{\text{nom}} \ne 0 \land c_{\text{half}} = 0$
  4. Neither observed: $c_{\text{nom}} \ne 0 \land c_{\text{half}} \ne 0$
- **Timing Differences** on jointly observed particles:
  - Linear chord estimate difference:
    $$\Delta t_{\text{chord}} = |t_{\text{chord, nom}} - t_{\text{chord, half}}|$$
  - Disjoint saved bracket gap:
    $$\text{Gap} = \max\left(0, \max(t_{0, \text{nom}} - t_{1, \text{half}}, t_{0, \text{half}} - t_{1, \text{nom}})\right)$$
  - Worst possible bracket difference:
    $$\Delta t_{\text{worst}} = \max\left(|t_{0, \text{nom}} - t_{1, \text{half}}|, |t_{1, \text{nom}} - t_{0, \text{half}}|\right)$$
  - Evaluated against allocated event budget:
    $$B_{\text{event}} = 0.003497487083913345\text{ s} \times 0.2 = 0.000699497416782669\text{ s}$$

#### B. Residence Time
For each destination region $r \in \{\text{upstream}, \text{lower\_channel}, \text{upper\_channel}, \text{downstream}\}$:
$$\Delta \tau_r = |\tau_{r, \text{nom}} - \tau_{r, \text{half}}|$$
Evaluated with mass-weighted mean, maximum, and weighted quantiles $[0.05, 0.5, 0.95]$.

#### C. Fate Switches (Destination Category Transitions)
Exhaustively tracks the transition matrix of final destination categories between nominal and halfstep:
$$M_{c_1, c_2} = \sum_{i \in \text{fluid}} m_i \cdot \mathbb{I}(\text{cat}_{\text{nom}, i} = c_1 \land \text{cat}_{\text{half}, i} = c_2)$$
Total fate switch mass and fraction are reported directly:
$$M_{\text{switch}} = \sum_{c_1 \ne c_2} M_{c_1, c_2}, \quad f_{\text{switch}} = \frac{M_{\text{switch}}}{M_{\text{fluid}}}$$
**Strict Policy Mandate**: No invented CDFs, arbitrary distributions, or chaos gates are used to filter or erase fate switches. Every single particle migration is preserved in the output report.

#### D. Preserved Native Unknown Exclusions
Audits `unknown_mass_kg`, `numerical_loss_mass_kg`, and `invalid_state_mass_kg` across all 1,601 frames. Confirms that numerical losses and unresolved states are not erased or reassigned.

---

## 6. Directory Artifact Inventory

All files for this scope are co-located in:
`lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/`

| Filename | Type | Purpose | Launch Allowed | Q-N Status |
| :--- | :--- | :--- | :--- | :--- |
| [clone_transformer.py](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/clone_transformer.py) | Python Script | Quarterstep clone transformer from prepared012 | N/A (Tool) | N/A |
| [quarterstep_binding.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/quarterstep_binding.json) | JSON Binding | Prospective parameter & resource binding | N/A | `not_granted` |
| [quarterstep_prepare_request.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/quarterstep_prepare_request.json) | Runner Request | CPU preflight request for input preparation | `false` | `not_granted` |
| [quarterstep_solver_request.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/quarterstep_solver_request.json) | Runner Request | GPU qualification request for quarterstep solver | `false` | `not_granted` |
| [quarterstep_macro_binding.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/quarterstep_macro_binding.json) | JSON Binding | Prospective half-vs-quarter macro comparison binding | N/A | `not_granted` |
| [quarterstep_macro_run.py](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/quarterstep_macro_run.py) | Python Script | Macro evaluator running original compare_pair | N/A (Tool) | `not_granted` |
| [quarterstep_macro_request.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/quarterstep_macro_request.json) | Runner Request | CPU evaluator request for macro comparison | `false` | `not_granted` |
| [f1_nominal_vs_half_native_labels_comparison.py](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/f1_nominal_vs_half_native_labels_comparison.py) | Python Script | Canonical nominal-vs-half UID/weight paired comparison | N/A (Tool) | `not_granted` |
| [nominal_vs_half_labels_binding.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/nominal_vs_half_labels_binding.json) | JSON Binding | Canonical binding for labels comparison | N/A | `not_granted` |
| [nominal_vs_half_labels_request.json](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/nominal_vs_half_labels_request.json) | Runner Request | CPU evaluator request for labels comparison | `false` | `not_granted` |
| [GENUINE_QUARTERSTEP_PROSPECTIVE_REVIEW.md](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/genuine_quarterstep_prospective_v1/GENUINE_QUARTERSTEP_PROSPECTIVE_REVIEW.md) | Markdown Doc | Comprehensive technical review and evidence summary | N/A | N/A |

---

## 7. Verification via Synthetic Fixtures

Comprehensive unit tests have been implemented in:
[test_ds_data02_f1_genuine_quarterstep_prospective_v1.py](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/tests/test_ds_data02_f1_genuine_quarterstep_prospective_v1.py)

Tests verify:
1. **Transformer Reversibility**: Tests that XML modifications apply strictly to `<execution>`, preserve `<casedef>`, and satisfy the whole-XML reverse-bytes assertion.
2. **Synthetic H5 Label Comparison**: Generates mock HDF5 native-labels in `tmp_path` without loading actual production arrays, validating censor state breakdown, chord time deltas, interval gaps, residence deltas, fate switch transition matrices, and budget comparisons.
3. **Request Schema & Policy Invariants**: Verifies `launch_allowed is False`, `q_n_status == "not_granted"`, and `production_approval == "none"` across all runner requests.
