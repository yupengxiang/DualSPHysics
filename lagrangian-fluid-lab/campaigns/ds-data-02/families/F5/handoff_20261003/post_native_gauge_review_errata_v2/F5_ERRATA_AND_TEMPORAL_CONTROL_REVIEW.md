# F5 Source-Review Corrections, Errata Facts, and Genuine Temporal Control Preparation

**Schema**: `ds02.f5.errata-and-temporal-control-review.v2`  
**Family ID**: `F5`  
**Target Scope Directory**: `campaigns/ds-data-02/families/F5/handoff_20261003/post_native_gauge_review_errata_v2`  
**Date**: `2026-10-04`  
**Process Mode**: Fresh Gemini process under Root Followup 034  
**Parent Worktree**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`  
**Root Handoff Reference**: `campaigns/ds-data-02/families/F5/handoff_20261003/root_native_gauge_cohort_diagnostic_038/binding.json`  
**Reviewed Commit**: `fdfd1777`  

---

## 1. Governance Guardrails and Process Context

1. **Review Context**: Root independently reviewed F5 commit `fdfd1777`. Root has **NOT adopted** the unsupported causal conclusions or the proposed Equation of State (EOS) parity experiment contained therein.
2. **Preservation of Original Bytes**: All historical commits, source geometries, previous diagnostic reports, baseline execution receipts, and git bytes remain strictly preserved. This handoff writes only to the new isolated scope directory `campaigns/ds-data-02/families/F5/handoff_20261003/post_native_gauge_review_errata_v2` and delivers a scoped local commit.
3. **Execution Guardrails**: In strict compliance with Root instructions:
   - **NO actual array or CSV post-processing analysis** is performed.
   - **NO DualSPHysics solver executions** are launched.
   - **NO GenCase runs** are initiated.
   - **NO recursive agent delegations** are spawned.
   - **NO ledger modifications** are made.
   - **NO production promotions or cleanups** are attempted.
   - All candidate runner request files declare `"launch_allowed": false` and `"launch_owner": "root"`. Root must independently review before any future launch.

---

## 2. Errata and Source-Review Corrections

Root review of commit `fdfd1777` identified three critical technical corrections regarding physical interpretation, spatial resolution claims, and computational resource accounting:

### 2.1 Correction 1: Refutation of Linear Small-Mach Bound and Non-Uniqueness of EOS Attribution
- **Prior Flawed Premise in `fdfd1777`**: Commit `fdfd1777` utilized a linearized small-Mach perturbation scaling ($O(M^2) \sim 0.26\%$) to argue that artificial sound speed variation ($B$ changing by $+11.4\%$) was mathematically incapable of producing the observed $12\%$ free-surface discrepancy at wave gauges `WG1` and `WG2`. From this, it concluded that if an EOS parity experiment failed to eliminate the error, it would uniquely and conclusively establish spatial under-resolution as the governing cause.
- **Root Correction and Physical Reality**:
  1. *Nonlinear SPH Reality*: Linearized small-Mach theoretical scaling applies strictly to unbounded, inviscid, linear acoustic waves. DualSPHysics simulates an intrinsically **nonlinear, moving-wall, shallow-water system** with Dynamic Boundary Condition (DBC) repulsive particles, violent paddle acceleration, continuous sloping bed wet-dry front dynamics, and moving contact lines. Linear theoretical scaling does **NOT** prove an upper bound on errors in such a coupled nonlinear numerical system.
  2. *Non-Uniqueness of Attribution*: If an EOS parity experiment is performed and errors persist, that outcome does **NOT** uniquely establish spatial under-resolution. Multiple distinct numerical and physical mechanisms vary simultaneously across resolutions:
     - **Boundary Supports**: In DBC, boundary particle repulsive forces scale with the kernel support radius $2h \approx 5.196 \Delta p$. The effective boundary standoff distance changes by a factor of $5\times$ across the 3DP ladder ($0.260$ m at Coarse vs $0.052$ m at Fine), dramatically altering bottom boundary layer behavior, wave damping, and dissipation along the flume bed.
     - **Temporal Discretization and Sensitivity**: SPH velocity divergence, particle shifting, and time-step integration truncation error interact with spatial gradients.
     - **Operator Behavior**: Kernel truncation at the free surface and bed interfaces, particle disorder, and the discrete particle representation of the planar paddle face introduce resolution-dependent roughness.
  3. *Conclusion*: Attributing residual discrepancy uniquely to spatial under-resolution based on an EOS experiment is scientifically invalid. Root has formally rejected the EOS parity experiment.

### 2.2 Correction 2: Disavowal of Universal $H_{wave}/\Delta p \ge 10$ Particle Threshold
- **Prior Flawed Premise in `fdfd1777`**: Commit `fdfd1777` claimed that SPH wave propagation fundamentally requires at least 10 particles across the wave amplitude ($H_{wave}/\Delta p \ge 10$) to avoid fatal numerical dissipation, asserting that because $H_{wave} \approx 0.04$ m had only $1.6$ to $4.0$ particles across its height, spatial under-resolution was the "governing proven physical cause."
- **Root Correction and Physical Reality**:
  1. *Absence of Universal Law*: There is **no universal requirement** that SPH requires $H_{wave}/\Delta p \ge 10$. In small-amplitude, smooth wave regimes, numerical accuracy is governed by particles per wavelength ($\lambda / \Delta p$) and particles per fluid depth ($H / \Delta p$).
  2. *Flume Dimensions*: At Fine resolution ($\Delta p = 0.010$ m), the still water depth $H = 0.40$ m contains $H/\Delta p = 40$ fluid particle layers, and the primary wavelength ($\lambda \sim 2\text{--}3$ m) spans 200 to 300 particles. Small-amplitude smooth wave propagation can be adequately resolved without demanding 10 particles across a small elevation perturbation.
  3. *Categorization*: Insufficient spatial resolution must be strictly categorized as an **untested plausible hypothesis**, alongside temporal sensitivity and boundary interaction effects, rather than a proven primary cause.

### 2.3 Correction 3: Rigorous Storage Accounting, Budget Window, and $\Delta p = 0.005$ m Scaling
- **Prior Flawed Accounting in `fdfd1777`**: Commit `fdfd1777` asserted that a theoretical $\Delta p = 0.005$ m run would generate 720 to 950 GB per run and "catastrophically violate the 500 GiB Home floor."
- **Root Correction and Authoritative Evidence**:
  1. *Actual Disk Capacity*: Direct system audit (`df -h /home/jade`) demonstrates **3.7 TiB free** (within the documented 3.5–3.8 TiB window). A run consuming 720–950 GB does **not** alone exceed the 500 GiB free floor ($3700\text{ GiB} - 950\text{ GiB} \approx 2750\text{ GiB} \gg 500\text{ GiB}$). Budget reservations must compute the sum of actual inputs, raw outputs, working copies, and the required 500 GiB safety floor.
  2. *Live Campaign GPU Budget Status*:
     - Total allocated budget: **96.0 GPU-hours**.
     - Total charged so far: **~50.5 GPU-hours**.
     - Available remaining campaign budget: **~45.5 GPU-hours**.
  3. *Actual Baseline Fine Telemetry*:
     Authoritative execution receipts confirm exact baseline elapsed times:
     - `RUNUP` Fine (`root-runup-surface-first-full16-native-027`): **10,134.8276 s** (~2.815 GPU-hours).
     - `WEIR` Fine (`root-weir-surface-first-full16-native-027`): **9,465.4636 s** (~2.629 GPU-hours).
  4. *Rigorous $\Delta p = 0.005$ m Work Scaling*:
     - In 3D space, halving particle spacing scales particle count by $(1/0.5)^3 = 8\times$ ($2^3$).
     - The acoustic CFL condition ($\Delta t \propto h \propto \Delta p$) requires doubling the number of time steps ($2\times$).
     - Total computational work scales by $8 \times 2 = \mathbf{16\times}$ baseline fine!
     - Predicted runtime per run:
       $$\text{RUNUP: } 16 \times 2.815\text{ GPUh} \approx \mathbf{45.0\ \text{GPU-hours}}$$
       $$\text{WEIR: } 16 \times 2.629\text{ GPUh} \approx \mathbf{42.1\ \text{GPU-hours}}$$
     - A single $\Delta p = 0.005$ m simulation would consume nearly the **entire remaining 45.5 GPU-hour window**, rendering it completely unfeasible for the current campaign window. Any future consideration requires rigorous uncertainty quantification, actual particle counts, and decoupled storage architectures.

---

## 3. Root Decision: Independent Integration Diagnostic First

Root chooses the **required missing independent integration diagnostic** as the mandatory first priority before any spatial speculation:

### 3.1 Scientific Rationale: `DTsMin = 0` Does Not Imply Time Convergence
- Authoritative telemetry from `F5_F6_COMPLETED_NATIVE_INTERVAL_TELEMETRY_036` confirmed `total_DT_min_adjustments = 0` across all runs.
- While this definitive telemetry rules out artificial numerical floor clipping, **absence of floor clamping does NOT prove temporal convergence**.
- In DualSPHysics, the Symplectic time-integrator evaluates local truncation error $O(\Delta t^2)$. In the 3DP spatial series, spatial refinement simultaneously refined time ($\Delta t \propto \Delta p$), leaving spatial and temporal discretization errors completely confounded.
- An independent temporal study—holding spatial resolution $\Delta p = 0.010$ m fixed while halving the integration time step—has never been performed for F5.

### 3.2 Diagnostic Configuration: Genuine Halving of CFL and CoefDtMin
To achieve a genuine halving of the execution time step without altering the spatial grid:
1. **Execution CFL**: Mutated from `0.2` to **`0.1`** (`case/execution/constants/cflnumber`).
2. **Execution CoefDtMin**: Mutated from `0.05` to **`0.025`** (`case/execution/parameters/parameter[@key='CoefDtMin']`).
3. **Exact Invariant Preservation**:
   - Spatial resolution: $\Delta p = 0.010$ m strictly identical.
   - Initial condition binary: exact original `F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024.bi4` (SHA256: `bbb32f38...`) and `F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024.bi4` (SHA256: `a73ee03e...`) verified bit-for-bit.
   - Physical forcing: identical regular piston motion data (`8cb7dab0...`).
   - Bed STL geometry: identical continuous bed profile (`93cf180a...`).
   - Equation of State: source Tait EOS ($B = 218,622.86$ Pa, $\gamma = 7$, $\rho_0 = 1000$ kg/m$^3$) unchanged.
   - Full time window: strictly 16.0 s with `TimeOut = 0.02` s.
   - All 6 original native wave gauges (`WG1`, `WG2`, `WG3`, `WG4`, `RunupToe`, `Crest`).
   - Default shader density unchanged (`DensityDT=2`, `DensityDTvalue=0.1`).

---

## 4. Standalone Execution-Only Transformer Specification

### 4.1 Root Primary Source Grounding
Primary native sources are read directly via `campaigns/ds-data-02/families/F5/handoff_20261003/root_native_gauge_cohort_diagnostic_038/binding.json`:
- **RUNUP Fine XML**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024/root-execution-inputs-026/F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024.xml` (SHA256: `1de0a403c525b01208062f46f1b53759ca798edce8221b05c389fc8006ef6c54`)
- **WEIR Fine XML**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024/root-execution-inputs-026/F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024.xml` (SHA256: `e34fe0f2616f481049553ff122c25e3b2da771258450bec4f07ad34d239f5f5f`)

### 4.2 Strict XML Mutation Rules and Reversibility Proof
- **Target 1**: `<parameter key="CoefDtMin" value="0.05" />` $\longrightarrow$ `<parameter key="CoefDtMin" value="0.025" />` (inside `<execution><parameters>`).
- **Target 2**: `<cflnumber value="0.2" />` $\longrightarrow$ `<cflnumber value="0.1" />` (inside `<execution><constants>`).
- **Historical CFL Protected**: The historical `<casedef><constantsdef><cflnumber value="0.2" />` tag is **STRICTLY PRESERVED** and never mutated.
- **Reversibility Proof**:
  - Restoring `0.1` $\to$ `0.2` and `0.025` $\to$ `0.05` in the execution block produces bit-for-bit identical byte streams matching original SHA256 digests (`1de0a403...` and `e34fe0f2...`).
  - Tested and verified in Python via `prospective_execution_transformer.py` and `test_prospective_execution_transformer.py`.

### 4.3 GenCase Provenance: Clone Governance (Not New GenCase)
To prevent misleading metadata:
- The prospective runs are **execution-only clones**, NOT new GenCase generations.
- They bind directly to the actual existing GenCase receipts:
  - RUNUP: `root-runup-surface-first-support-gencase-024/execution-receipt.json` (SHA256: `f0628e57...`).
  - WEIR: `root-weir-surface-first-support-gencase-024/execution-receipt.json` (SHA256: `bb9bee84...`).
- When Root launches the execution, the runner will record an `actual_clone_preparation_receipt` linking back to the verified initial BI4 proofs.

---

## 5. Preregistered Strict Independent Integration Macro/Gauge Diagnostic

### 5.1 Evaluation Framework and Contractual Budget Source
The diagnostic evaluates pairwise convergence between the baseline Fine run and the half-CFL/half-DtMin Fine run:
- **Evaluator**: Exact frozen reader `gauge_evaluator_v2.py` (SHA256: `8f858144b52a03ef207251bd84458bb8cdd0ee5d73bf2a6799cf168a8fc8e35a`).
- **Normalization Scale**: $H = 0.40$ m.
- **Evaluation Window**: Exactly 800 uniform samples in $[0.0, 15.98]$ s with $dt = 0.02$ s.
- **Temporal Budget Primary Citation**:
  Formally read from `lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/quality_contract.json` (lines 42–43):
  ```json
  "macro_relative_error_budget": 0.05,
  "integration_error_share": 0.2
  ```
  $$\text{Temporal Integration Budget} = 0.05 \times 0.20 = \mathbf{0.01\ (1.0\% \text{ relative error})}$$
  $$\text{Absolute Error Tolerance} = 0.01 \times 0.40\text{ m} = \mathbf{0.004\ \text{m}\ (4.0\ \text{mm})}$$
- **Strict Invariants**: Strictly **NO phase alignment**, **NO time shifting**, **NO loosening of the 5% spatial macro threshold**, and **NO wet-only subset selection**.

### 5.2 Permanence of Prior Spatial Failure
A fundamental principle of rigorous numerical qualification:
$$\mathbf{The\ prior\ always\text{-}wet\ 12\%\ spatial\ failure\ stays\ negative\ whichever\ temporal\ result\ occurs.}$$

1. **If Temporal Halfstep PASSES ($\text{RMSE}/H \le 1.0\%$)**:
   - The baseline Fine run is rigorously proven to be temporally converged.
   - Therefore, the $12\%$ discrepancy observed between Medium and Fine at flat-bed probes `WG1` and `WG2` is conclusively proven to be **NOT an artifact of temporal integration error**.
   - The spatial ladder failure remains an authentic, verified negative result of the tested spatial discretization.
2. **If Temporal Halfstep FAILS ($\text{RMSE}/H > 1.0\%$)**:
   - The baseline Fine run was not temporally converged under baseline $\text{CFL} = 0.2$.
   - The spatial ladder comparison was corrupted by temporal integration error, and spatial convergence was never demonstrated.
   - The spatial ladder result remains strictly negative.

---

## 6. Resource Reservations and Budget Protection

### 6.1 Reservation Caps vs Expected Consumption
- **Conservative Reservable Limits**:
  - Maximum wall time: **28,800 s (8.0 GPU-hours)** per case.
  - CPU allocation: **4 threads $\times$ 8.0 h = 32 core-hours** per case.
  - Total two-case conservative cap: **16.0 GPU-hours**, **64 core-hours**.
- **Expected Actual Runtime ($2\times$ Baseline Fine)**:
  - `RUNUP`: $2 \times 10,134.8\text{ s} = 20,269.7\text{ s}$ (**~5.63 GPU-hours**).
  - `WEIR`: $2 \times 9,465.5\text{ s} = 18,930.9\text{ s}$ (**~5.26 GPU-hours**).
  - Total expected consumption: **~10.89 GPU-hours**.
- **Campaign GPU Budget Window**:
  - Remaining: **~45.5 GPU-hours**.
  - Subtracting conservative cap (16.0 GPUh) leaves **~29.5 GPU-hours** available.
  - Fits safely and comfortably within campaign limits.
- **Disk Storage and Floor Protection**:
  - Estimated storage: **256 GiB** per case (512 GiB total).
  - Available Home space: **3.7 TiB** (~3,780 GiB).
  - Free space after potential execution: $3780 - 512 \approx 3,268\text{ GiB} \gg 500\text{ GiB}$ floor.
  - Required 500 GiB safety floor is fully protected.

### 6.2 Expected Output Metadata Validation Checklist
Upon any future Root authorized execution, the following exact metadata must be verified:
- `Part_%04d.bi4`: exactly 801 files (Part 0000 to Part 0800).
- `GaugesSWL_*.csv`: exactly 800 data rows (0.00 s to 15.98 s).
- `RunPARTs.csv`: exactly 801 rows, strictly monotonically increasing timestamps, zero particle exclusions (`NpOut = 0`).

---

## 7. Deliverable Artifacts Summary

| Artifact File | Schema / Format | Description |
| :--- | :--- | :--- |
| `F5_ERRATA_AND_TEMPORAL_CONTROL_REVIEW.md` | Markdown | Comprehensive errata, physical corrections, and governance documentation. |
| `prospective_execution_transformer.py` | Python 3 | Standalone execution-only transformer script with hash verification and reversibility check. |
| `binding_proposals.json` | `ds02.f5.binding-proposals.v1` | Formal proposal binding RUNUP and WEIR to exact original XMLs, BI4 proofs, and mutations. |
| `preregistered_integration_diagnostic.json` | `ds02.f5.preregistered-integration-diagnostic.v1` | Pre-registered independent integration macro/gauge diagnostic protocol with 1% contract budget. |
| `requests/F5_RUNUP_FINE_TEMPORAL_HALFSTEP_REQUEST.json` | `ds02.runner-request.v2` | Candidate runner request (`launch_allowed: false`, `launch_owner: "root"`). |
| `requests/F5_WEIR_FINE_TEMPORAL_HALFSTEP_REQUEST.json` | `ds02.runner-request.v2` | Candidate runner request (`launch_allowed: false`, `launch_owner: "root"`). |
| `test_prospective_execution_transformer.py` | Pytest | Test suite verifying source integrity, mutation, reversibility, proposals, and requests (6/6 passing). |
| `manifest.json` | `ds02.f5.manifest.v1` | Comprehensive scope manifest and governance assertions. |

---

## 8. Next Executable Tasks

1. **Deliver Scoped Local Commit**: Commit all new files in `handoff_20261003/post_native_gauge_review_errata_v2` locally on branch `codex/ds-data-02-infra`.
2. **Root Pre-Launch Review**: Submit prospective transformer, proposals, and request JSONs to Root for independent review and execution authorization.
3. **No Autonomous Compute**: Maintain strict standby; await explicit Root execution directive.
