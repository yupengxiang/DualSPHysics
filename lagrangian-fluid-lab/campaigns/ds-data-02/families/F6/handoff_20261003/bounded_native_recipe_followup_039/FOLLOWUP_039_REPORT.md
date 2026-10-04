# DS-DATA-02 Family F6 Followup 039 Report

**Scope:** `handoff_20261003/bounded_native_recipe_followup_039`  
**Isolated Worktree:** `/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics`  
**Model:** Gemini 3.8 Flash (High)  
**Date:** 2026-10-04  
**Status:** Preparation and Guard Audit Workers Ready; Full 12s GPU Qualification Request Staged (`launch_allowed: false`)

---

## 1. Executive Summary & Boundaries

Under DS-DATA-02 activity boundaries and the dataset-only campaign goal in `GOAL_ZH.md`:
- **Owner Process Constraints:** The owner process strictly reviews source/JSON metadata, develops bounded preparation and audit workers, stages requests with `launch_allowed: false`, and runs clearly synthetic unit tests. No actual H5/CSV array analysis, GenCase, solver, or conversion launches occur in this process.
- **Root Dispatcher:** Root alone launches actual scientific audits, GenCase preflights, solvers, and official conversions through the shared strict dispatcher.
- **Campaign Resources:** Root remaining budget stands at ~32 GPU hours and 56 qualification attempts; Home storage >= 500 GiB. All physical full event windows (12.0s for F6) are preserved.
- **Repair Policy:** At most 2 evidence-based repairs per root cause. Repetitive metric relaxation, quantile substitution, proximity gates, and fake zero-fate proofs are strictly prohibited.
- **Governance & Claims:** `q_n: "not_granted"`, `production_approval: "none"`. No ML, public push, or premature product claims.

---

## 2. Review of Integration Evidence (Reviews 029 & 030)

Review of `root_actual_full241_geometry_pose_review_029` and `root_exact_native_geometry_pose_time_review_030` establishes:
1. **Proven Kabsch SO(3) Rigid Pose Reconstruction:**
   - Evaluated directly on native floating coordinates (`Type == 2`, `Mk == 60`, `Zone == 0`) across 241 explicit Part frames (0.0s to 12.0s, $dt = 0.05$s).
   - Exact immutable floating cohort: 131,072 nodes (fine), 32,000 nodes (medium), 16,384 nodes (coarse).
   - Enforces proper rotation $\det(R) = +1$, rank 3 covariance, and uniform body support weights ($w_i = 1/N$).
   - Validated against official `FloatingInfo_mk60.csv` centroids (max timestamp offset $< 5 \times 10^{-5}$s).
2. **Actual Fine-Medium Orientation & Translation Metrics:**
   - **Geodesic Orientation RMSE:** $0.044738$ rad ($2.563^\circ$), maximum $0.11266$ rad ($6.455^\circ$), mean $0.038456$ rad ($2.203^\circ$).
     - *Governance Ruling:* DESCRIPTIVE ONLY. Orientation budget is `null` / `unregistered`. Inventing an arbitrary 1 rad normalization or 5% SO(3) threshold is strictly prohibited.
   - **Translational Center RMSE:** $0.086168$ m, maximum $0.12623$ m.
     - Normalized against declared characteristic scale $L = 0.8$ m: $\text{RMSE} / L = 0.10771$.
     - *Macro Budget Result:* Fails the generic 5% macro tolerance budget ($\text{RMSE} / L = 0.1077 > 0.05$, exceeding the 0.04 m budget).

---

## 3. Timestep Controls & Halfstep Rationale

### 3.1 Baseline Original Full Run Audit
The baseline fine run `root-angular-release-dp0125-full12-native-gpu-021` in case `F6_ANGULAR_RELEASE_DP0125` was audited via `RunPARTs.csv`, `Run.out`, and `execution-receipt.json`:
- **Elapsed Runtime:** $7060.63$ s (~1.96 GPUh) on NVIDIA RTX 6000 Ada Generation (`GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec`).
- **Storage Output:** 32,295,399,285 bytes (~32.3 GB).
- **Timestep Controls:**
  - `DtFixed = 0.0` (variable time-stepping).
  - `DtIni = 0.0` (computed initial $dt = 0.00046737$ s).
  - `DtMin = 0.0` (computed minimum $dt = 2.33686 \times 10^{-5}$ s).
  - `cflnumber = 0.2` (in both `<casedef>` and `<execution>`).
  - `CoefDtMin = 0.05`.
  - `StepAlgorithm = 2` (Symplectic, `VerletSteps = 40`).
- **Timestep Counters:**
  - Total solver steps: $163,707$ across 241 frames (0.0s to 12.000037s).
  - Total `DTsMin` adjustments: exactly 273 adjustments, concentrated strictly during violent entry in Part 7 (229 clamps at $t \approx 0.35$s) and Part 8 (44 clamps at $t \approx 0.40$s), 0 elsewhere.
  - Particles out: 28 total (final particle count: 3,045,480).

### 3.2 Halfstep Status & Mechanism
- **Halfstep History:** The baseline run was nominal ($CFL = 0.2$, $\text{CoefDtMin} = 0.05$); no halfstep run has been executed for F6.
- **Legal Halfstep Ruling:** Because `DtFixed == 0`, the solver uses variable CFL stepping. Under DualSPHysics rules, a genuine halfstep time integration control requires legally halving the CFL number ($0.2 \to 0.1$) and $\text{CoefDtMin}$ ($0.05 \to 0.025$) in the `<execution>` block. Sourcing an unprescribed fixed $dt$ is legally prohibited.

---

## 4. Deliverables in Scope `bounded_native_recipe_followup_039`

The following artifacts have been authored and verified:

| File | Purpose | Verification Status |
| :--- | :--- | :--- |
| `source_and_resource_binding.json` | Exhaustive bindings, SHA256 digests, runtime metrics, and budget status of baseline run | Verified; all source file hashes match |
| `preregistration.json` | Preregistration protocol for genuine halfstep CFL=0.1 control | Verified; exact physics and boundaries registered |
| `clone_transformer.py` | Strict XML transformer implementing WholeXML undo proof | Verified; 100% byte-for-byte and tree-for-tree roundtrip |
| `clone_worker.py` | Executable preparation worker; reuses fine BI4 without regeneration | Tested; dry-run passes all 7 source & physics checks |
| `independent_guard_audit.py` | Executable guard audit worker; parses RunPARTs counters and DTsMin clamps | Tested; verifies 241 frames, 163,707 steps, 273 clamps |
| `owner_geometry_v1.py` | Byte-identical vendor of proven Kabsch SO(3) SVD orientation reader | SHA256: `f7213749691c57caac7ad5b41b92a77f85cfc4d1ea90b775c6c6b5a074723dc5` |
| `kabsch_evaluation_pipeline.py` | Downstream evaluation comparing nominal fine vs genuine halfstep fine | Tested; evaluates translation against L=0.8m, orientation descriptive |
| `requests/F6_ANGULAR_RELEASE_DP0125_HALFSTEP_SOLVER_GPU_REQUEST.json` | Full 12s GPU runner request (`schema: ds02.runner-request.v2`) | `launch_allowed: false`, ~4.0 GPUh estimated |
| `requests/F6_ANGULAR_RELEASE_DP0125_HALFSTEP_PREPARATION_CPU_REQUEST.json` | CPU runner request for materializing cloned inputs | `launch_allowed: false` |
| `requests/F6_ANGULAR_RELEASE_DP0125_POSTPROCESS_PARTVTK_REQUEST.json` | Official PartVTK export request for 241 floating frames | `launch_allowed: false` |
| `requests/F6_ANGULAR_RELEASE_DP0125_POSTPROCESS_FLOATINGINFO_REQUEST.json` | Official FloatingInfo export request for 241 frames | `launch_allowed: false` |
| `requests/F6_ANGULAR_RELEASE_DP0125_EVALUATION_CPU_REQUEST.json` | CPU runner request for Kabsch proper SO(3) evaluation | `launch_allowed: false` |
| `test_followup_039.py` | Comprehensive synthetic test suite (7 unit/synthetic tests) | Ran 7 tests in 0.84s: **OK** |

---

## 5. WholeXML Undo Proof & Exact Initial Rigid Preservation

### 5.1 Reversibility Proof
- **Forward Mutation:**
  - `<parameter key="CoefDtMin" value="0.05" />` $\to$ `<parameter key="CoefDtMin" value="0.025" />` (in `<execution><parameters>`)
  - `<cflnumber value="0.2" />` $\to$ `<cflnumber value="0.1" />` (in `<execution><constants>`)
- **Historical Preservation:** `<casedef><constantsdef><cflnumber value="0.2" />` remains untouched.
- **Reversion:** Reverting the two strings yields the exact original byte sequence and identical ElementTree XML string. Verified in `test_03_whole_xml_undo_proof`.

### 5.2 Exact Initial Rigid Geometry & Physics Preservation
- **Rigid Body Drawbox:** Solid box at point `(2.00625, 0.80625, 0.88125)` with size `(0.7875, 0.7875, 0.3875)`, moved by $z = +0.005$ m.
- **Mass Semantics:** Declared physical `massbody = 128.0` kg (support particle weight sum = 256.0 kg).
- **Center:** `[2.4, 1.2, 1.08]` m.
- **Inertia Tensor:** `[8.53333, 8.53333, 13.6533]` $\text{kg}\cdot\text{m}^2$.
- **Driver:** Initial angular velocity `[0.08, 0.12, 0.06]` rad/s, `translationDOF = [1, 1, 1]`, `rotationDOF = [1, 1, 1]`.
- **Native EOS:** $\rho_0 = 1000$ $\text{kg}/\text{m}^3$, $\gamma = 7$, $c_{s0} = 55.59$ m/s, $B = 441450$ Pa, ViscoTreatment = 2, Visco = $1 \times 10^{-6}$ $\text{m}^2/\text{s}$.
- **BI4 Reuse:** Cloned input reuses exact fine BI4 (`90248a50c0041ae6fbfe85555166331f97710ce57937c3cdaddafe0b33f8169d`); zero new GenCase generation; particle counts remain verified at 3,045,508.

---

## 6. Campaign Budget & Resource Consumption Projection

- **Root Available Budget:** ~32 GPU hours, 56 qualification attempts, Home storage >= 500 GiB.
- **Projected Halfstep Cost:**
  - Estimated step count: ~320,000 to ~350,000 steps (~2x baseline 163,707 steps).
  - Estimated wallclock runtime: ~14,000 s (~3.9 to 4.2 GPUh) on NVIDIA RTX 6000 Ada.
  - Remaining GPU hours after run: ~28 GPUh (ample headroom for subsequent evaluation).
  - Storage footprint: ~45 GiB (leaving >= 455 GiB).
- **Single Repair Enforcement:** This is repair attempt 1 of the authorized maximum 2 repairs for the F6 spatial/temporal divergence root cause.

---

## 7. Next Executable Tasks for Root Dispatcher

1. **Input Materialization:** Run `clone_worker.py` via CPU dispatcher to write cloned XML and copy BI4.
2. **GPU Solver Dispatch:** Dispatch `F6_ANGULAR_RELEASE_DP0125_HALFSTEP_SOLVER_GPU_REQUEST.json` through the shared strict dispatcher to live GPU inventory with atomic lease.
3. **Official Postprocessing:** Run `PartVTK` (241 frames) and `FloatingInfo` official binary export requests.
4. **Guard Audit & Kabsch Evaluation:** Execute `independent_guard_audit.py` and `kabsch_evaluation_pipeline.py` to compare nominal fine vs genuine halfstep fine trajectories.
