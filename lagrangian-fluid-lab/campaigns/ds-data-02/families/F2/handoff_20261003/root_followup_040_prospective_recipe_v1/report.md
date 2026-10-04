# DS-DATA-02 Family F2: Root Followup 040 Prospective Recipe Report v1

**Document Identifier:** `ds-data-02.f2.root-followup-040-prospective-recipe-report.v1`  
**Date:** `2026-10-04T02:40:00Z`  
**Scope:** `lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_040_prospective_recipe_v1`  
**Governance & Claim Boundaries:** `launch_allowed: false`, `q_n: not_granted`, `q_e: not_granted`, `q_i: not_granted`, `production: none`  

---

## 1. Executive Summary & Root Followup 040 Mandate

This report delivers the executable, Root-reviewable prospective suite for genuine independent adaptive time integration control of **F2 RV4EQ DP005 OFFSET** over the full 4.0-second event window.

### Campaign Budget Status
- **Target 7 Families Count:** 0/336 (remains 0/336 across all families)
- **Remaining Resource Budget:** ~32 GPU hours / 53 qualification attempts (max 2 repairs/root causes)
- **Candidate Resource Requirement:** ~0.307 GPU hours (~1,107 s walltime on NVIDIA RTX 6000 Ada), 1 qualification attempt
- **Execution Authority:** Strictly `launch_allowed: false`; dispatch through shared `ds_data02_strict_dispatch_v1.py` runner only

---

## 2. Review of Save Comparison 027 (complete0)

Root's completed save comparison report (`save-comparison.json`) evaluates observation discretization sensitivity between nominal 401 frames ($dt=0.01\text{ s}$) and dense 4001 frames ($dt=0.001\text{ s}$) of the same physical simulation trajectory:

- **Source File:** `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_ACTUAL_NATIVE_SAVE_COMPARISON/root-offset-fine-full401-vs4001-native-per-uid-residence-save-comparison-027/save-comparison.json`
- **Report SHA-256:** `2f1a19acfd9d02fc8b45c5144937335c10a33c00a9fb352786345977995eebe8`
- **Nominal Source:** `root-offset-fine-full401-frozen-events-native-weights-024` (401 frames)
- **Dense Source:** `root-offset-fine-full4001-frozen-events-native-weights-025` (4001 frames)

### Core Verified Invariants:
1. **UID Final Fates Agreement:**
   ALL 196,608 fluid particle final fates match identically with **0 switched particles**:
   - Unknown: 2,151 particles
   - Cup: 0 particles
   - Receiver: 24,411 particles
   - Tray: 161,580 particles
   - Inflight: 8,466 particles
2. **Native Exclusions:**
   2,151 Motive 1 out-of-bounds exclusions ($0.268875\text{ kg}$) are strictly preserved as unknown invalid; physical spill is not inferred.
3. **Per-UID Residence Gaps:**
   - Inflight: mass-weighted mean absolute gap $0.0086022\text{ s}$, max absolute gap $0.0660208\text{ s}$
   - Cup: mass-weighted mean absolute gap $0.0031132\text{ s}$, max absolute gap $0.0544648\text{ s}$
   - Receiver: mass-weighted mean absolute gap $0.0010337\text{ s}$, max absolute gap $0.0635137\text{ s}$
   - Tray: mass-weighted mean absolute gap $0.0068768\text{ s}$, max absolute gap $0.0604922\text{ s}$
   - Global max absolute gap: $0.0660208\text{ s}$
4. **Episodic Event Matching:**
   Literal closed bracket matching ($\max(t_{\text{start,nom}}, t_{\text{start,dense}}) \le \min(t_{\text{end,nom}}, t_{\text{end,dense}})$ without $+10^{-12}\text{ s}$ extension) yields:
   - Proven unique 1:1 joint matches: 1,852,580 events ($231.57\text{ kg}$)
   - Ambiguous clusters retained: 8,085 nominal / 16,184 dense events
   - Unmatched nominal: 0
5. **Scientific Boundary:**
   Save comparison 027 evaluates observation save frequency only. It does not establish numerical time integration convergence.

---

## 3. Audit of Existing Time-Control Evidence

An exhaustive audit of existing F2 simulation attempts confirms that **genuine independent adaptive time integration control is missing**:
1. **Dense Save 001 (`root-offset-fine-effective-dense-save001-full4-native-018`):**
   This run used standard adaptive parameters ($\text{CFL}=0.2, \text{CoefDtMin}=0.05$) and simply saved output every $0.001\text{ s}$ (4001 frames). It is an observation save alias, not an independent time integration run.
2. **Reduced Dt Floor-Safe 001 (`qualification-f2_rv4eq_dp005_offset_v1_reduced_dt_save010_floorsafe001-native-fullstate-v1`):**
   This attempt overrode the solver with an explicit fixed timestep ($\text{DtFixed}=3.88682\times 10^{-6}\text{ s}$), forcing 1,029,119 identical fixed time steps rather than genuine adaptive halving. Furthermore, it lacked postprocessing, PartVtk conversion, actual pose extraction, and frozen V8 operator labels generation. It is preserved as consumed negative evidence; artificial fixedDt clamps are rejected.

---

## 4. Exact Initial State and Execution Clone Specification

To achieve genuine independent time integration control without modifying the physical problem, the clone worker:
1. **Exact Initial State Copy:**
   Copies the authoritative GenCase-generated binary particle initial state `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001.bi4` (73,360,382 bytes, SHA-256 `efa7d2a296ed3de308c93b598e47225b36865006977caaa6a9a8898099b922a6`).
2. **Asset Binding Invariance:**
   Retains the original prefix basename `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001` in the destination directory. This ensures that `<file name="F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_motion.dat" />` references in `<casedef>` and `<execution>` remain valid without modifying case geometry or motion definitions.
3. **Adaptive True-Halfstep Execution Mutation:**
   - `execution/constants/cflnumber`: halved from $0.2 \to 0.1$
   - `execution/parameters/CoefDtMin`: halved from $0.05 \to 0.025$
   - `DtFixed = 0`, `DtIni = 0`, `DtMin = 0` (clamps negative; pure adaptive time stepping)
   - `TimeMax = 4.0`, `TimeOut = 0.01` (401 frames baseline event window retained)
4. **Whole-XML Reverse Proof:**
   Inverting mutated tokens recovers exact original 7,618 bytes and original SHA-256 `f57c5e5fcf6c7c374ae14a8b28ae40b9e080554e2dfae8824253ae32e42b49cd`.
5. **ElementTree Roundtrip Undo Proof:**
   Restoring `cflnumber` to 0.2 and `CoefDtMin` to 0.05 yields bitwise-identical `E.tostring(restored) == E.tostring(before)`, verifying Root's `run.py` contract.

---

## 5. Pinned Source Receipts & Lineage

| Source Role | Path | SHA-256 | Status | Frames |
| :--- | :--- | :--- | :--- | :--- |
| **GenCase** | `.../F2_RV4EQ_DP005_OFFSET_V1/gencase-f2_rv4eq_dp005_offset_v1-20261002-001/execution-receipt.json` | `f973b151cadea0d9...` | completed (0) | 1 |
| **Baseline Solver** | `.../qualification-f2_rv4eq_dp005_offset_v1-baseline-save001-native-fullstate-v1/execution-receipt.json` | `ad826271229884cc...` | completed (0) | 401 |
| **Pose root-013** | `.../root-offset-fine-actual-native-pose-v1-013/execution-receipt.json` | `9b16197cb574f50e...` | completed | 401 |
| **Report root-024**| `.../root-offset-fine-full401-frozen-events-native-weights-024/execution-receipt.json` | `e3f3a39c741b02d7...` | completed (0) | 401 |
| **Dense Solver 018**| `.../root-offset-fine-effective-dense-save001-full4-native-018/execution-receipt.json` | `b4fd368774eb0ed9...` | completed (0) | 4001 |
| **Dense Pose 022**  | `.../root-offset-fine-full4001-actual-pose-13-bitwise-payload-singlecopy-022/execution-receipt.json` | `c82580ded03bb6a0...` | completed | 4001 |
| **Dense Report 025**| `.../root-offset-fine-full4001-frozen-events-native-weights-025/execution-receipt.json` | `ea85d05c84f34bcb...` | completed (0) | 4001 |
| **Comparison 027**  | `.../root-offset-fine-full401-vs4001-native-per-uid-residence-save-comparison-027/save-comparison.json` | `2f1a19acfd9d02fc...` | completed | 401 vs 4001 |

---

## 6. Native Mass Authority and Immutable Pose Standard

1. **Native Binary Float32 Mass Authority:**
   - Single fluid particle mass: $0.0001250000059371814\text{ kg}$
   - Fluid particle count: $196,608$
   - Cohort mass: $24.576001167297363\text{ kg}$
   - Benchmark mass: $24.576\text{ kg}$
   - Relative representation drift: $4.7497\times 10^{-8}$ (legacy $10^{-12}$ diagnostic strictly fails)
   - Rejection of old uniform mass-.30 estimate and legacy 24.576 representation gate pass
2. **Corrected Pose 13 Typed Fields Standard:**
   - 13 typed datasets: `time`, `particle_id`, `particle_zone`, `initial_type`, `initial_mk`, `initial_mass`, `mass`, `type`, `mk`, `valid`, `position`, `velocity`, `density`
   - Augmented pose dataset: `rigid_body_state` with `control_sign_applied: -1.0`, moving node count 76,676, max angle residual $3.769\times 10^{-8}\text{ rad}$, max pos RMS $3.210\times 10^{-8}\text{ m}$

---

## 7. Resource Accounting & Budget Analysis

- **Actual Baseline Solver Receipt:**
  - Elapsed seconds: $553.287853717804\text{ s}$ (~9.22 min)
  - Simulation steps: $201,237$
  - Output bytes: $29,396,068,905\text{ bytes}$ (~27.38 GiB)
  - Particles: 1,667,249
  - Hardware: 1x NVIDIA RTX 6000 Ada Generation
- **Candidate Halved-Step Estimate:**
  - Estimated steps: ~402,474 (~2x baseline)
  - Estimated GPU seconds: ~1,107 s (~18.45 min, ~0.307 GPU hours)
  - Max wall seconds: 3,600 s
  - Estimated storage: ~35 GB
  - Campaign budget impact: Remaining budget is ~32 GPU hours and 53 qualification attempts. The candidate consumes ~0.31 GPUh and 1 attempt, operating comfortably within budget constraints.

---

## 8. Prospective Recipe Artifacts Summary

The prospective suite is located in `lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_040_prospective_recipe_v1/`:
- `binding.json`: Pins source prefix, XML, BI4, motion dat, receipts 024/025, pose 013/022, save comparison 027, and execution control parameters.
- `selected_transformer.py`: Implements XML transformation with byte-level reversibility and ElementTree roundtrip undo proofs.
- `prepare.py`: Executable bounded CPU clone worker that writes cloned assets, preserves asset bindings, and creates `clone-report.json`.
- `evaluation_report.json`: Authoritative JSON evaluation report documenting save comparison 027, missing time-control evidence, and resource accounting.
- `prepare-request.json`: Root-ready CPU clone preparation request (`launch_allowed: false`).
- `solver-request.json`: Root-ready GPU solver qualification request (`launch_allowed: false`).
- `tests/test_f2_truehalfstep_preparation_v1.py`: Focused synthetic test suite containing 10 passing unit tests.
