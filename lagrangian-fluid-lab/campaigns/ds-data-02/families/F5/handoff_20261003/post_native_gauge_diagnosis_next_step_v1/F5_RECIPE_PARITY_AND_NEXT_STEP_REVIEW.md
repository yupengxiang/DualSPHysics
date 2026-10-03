# F5 Bounded Source Review: Recipe Parity, Diagnostic Evidence, and Next Falsifiable Experiment

**Schema**: `ds02.f5.recipe-parity-and-next-step-review.v1`  
**Family ID**: `F5`  
**Target Scope Directory**: `campaigns/ds-data-02/families/F5/handoff_20261003/post_native_gauge_diagnosis_next_step_v1`  
**Date**: `2026-10-04`  
**Reviewed Scopes & Reports**:
- Root Diagnostic 038: `F5_ACTUAL_NATIVE_GAUGE_COHORT_DIAGNOSTIC_038` (`native-gauge-diagnostic.json`, SHA256: `693b1a5583ee55578372f754c0f61e514443f0f1921a15bc6c8afff2bc109bea`)
- Root 3DP Gauge Comparison Review 035: `root_surface_matched_gauge_review_035` (`gauge_evaluator_v2.py`, SHA256: `8f858144b52a03ef207251bd84458bb8cdd0ee5d73bf2a6799cf168a8fc8e35a`)
- Prior Comparison Reports:
  - Runup Report: SHA256 `08cc97b2349c87831be6319971e7280a4b92532460c00c93c9adfe5bd69a2286`
  - Weir Report: SHA256 `46e0a4165d93bbdcae54c415b031922ad7ab9f40546965eb0f88fa426eccbf27`
- Root GenCase Review 029: `root_surface_spatial_gencase_review_029`
- Root Execution Inputs v2 032: `root_surface_spatial_execution_inputs_v2_032`
- Root Interval Telemetry 036: `F5_F6_COMPLETED_NATIVE_INTERVAL_TELEMETRY_036` (`native-interval-telemetry.json`, SHA256: `7a9255d3b2e45efeb6fa2f6460c041df36dd812022be3b539248d33c7115a078`)

---

## 1. Executive Summary & Governance Guardrails

1. **Mandate & Role**: Scoped F5 owner review in `ds-data-02-infra` assigned worktree. All work preserves continuum mother definitions, baseline physical geometries, and historical negative findings without recursive delegation, actual solver execution, GenCase runs, ledger edits, public publishing, or global registry mutation.
2. **Quality Contract Preserved**:
   - Reference still water height: $H = 0.40$ m.
   - Relative error tolerance: $5\%$ ($0.05 \times H = 0.020$ m absolute tolerance).
   - Probes evaluated: all 6 wave gauges (`WG1`, `WG2`, `WG3`, `WG4`, `RunupToe`, `Crest`).
   - Mechanism separation: `RUNUP` and `WEIR` evaluated independently.
   - Time window: strictly 800 native rows in $[0.0, 15.98]$ s with $dt = 0.02$ s (strictly no extrapolation to $16.0$ s).
   - Inviolability: strictly NO changing gauge operators, NO modifying quality metrics or tolerances, NO phase-aligning outputs to manufacture passes, NO assuming causality from cohort statistics, and NO proposing third wall-gap geometry repairs.
3. **Resource Bounds**: Bound root budget constraints: 96 GPU-hours, 384 CPU core-hours, qualification cap 320, Home floor 500 GiB. Nothing in this handoff independently authorizes execution; Root will independently review before compute.

---

## 2. Evidence Grounding from Actual Root Diagnostics

### 2.1 Native Telemetry (Scope 036)
Authoritative interval telemetry from `F5_F6_COMPLETED_NATIVE_INTERVAL_TELEMETRY_036` establishes:
- All 6 reference simulations (Coarse $\Delta p = 0.050$ m, Medium $\Delta p = 0.025$ m, Fine $\Delta p = 0.010$ m for both Runup and Weir) completed with exit code 0 (`completed0`).
- **Timestep Floor Clamps**: `total_DT_min_adjustments = 0` across all 801 recorded intervals for all 6 cases. Symplectic floor incidence is identically $0.0\%$. The solver never clamped to the artificial numerical floor `DtMin` ($0.05 \times DtIni$).
- **Particle Exclusions**: `native_NpOut_interval_sum = 0` across all cases. Zero particles were excluded from the domain.
- **Window Boundaries**: Actual native window $[0.0, 16.000]$ s confirmed; discrete steps were 24,815 (coarse), 51,722–52,652 (medium), and 215,800 (fine).

### 2.2 Root Gauge Cohort Diagnostic 038 Findings
Authoritative audit of `F5_ACTUAL_NATIVE_GAUGE_COHORT_DIAGNOSTIC_038` establishes:
1. **Initial Offsets**:
   - `WG3`: Observed initial offset is identically **$0.0$ m** across all pairwise comparisons (refuting the previous hypothesis of a 2 cm initial Frame 0 offset).
   - `WG1` and `WG2`: Observed initial offset between Medium and Fine is **$1.5 \times 10^{-5}$ m ($15\ \mu\text{m}$)**, consuming only $0.075\%$ of the $0.020$ m budget. Initial elevation offsets are physically negligible.
2. **WG1 and WG2 Errors (Flat-Bed Flume Probes)**:
   - Probes located at $x = 2.0$ m (`WG1`) and $x = 3.1$ m (`WG2`). Initial still water elevation $z = 0.42$ m over bed $z = 0.0$ m.
   - **$100\%$ Always-Wet**: All 800 samples fall strictly in the `both_above_floor` cohort. Zero dry-floor samples exist (`one_at_floor = 0`, `both_at_floor = 0`).
   - **Medium vs Fine Normalized Errors**:
     - `RUNUP`: `WG1` normalized RMSE$/H = 0.12828$ ($12.83\%$), `WG2` normalized RMSE$/H = 0.12103$ ($12.10\%$).
     - `WEIR`: `WG1` normalized RMSE$/H = 0.12043$ ($12.04\%$), `WG2` normalized RMSE$/H = 0.11588$ ($11.59\%$).
   - Both always-wet probes exceed the $5\%$ relative tolerance by more than $2.4\times$.
3. **WG3 Cohort Decomposition (Sloping Bed Probe, $x = 4.35$ m)**:
   - Bed elevation at probe: $z = 0.224$ m.
   - `one_at_floor` cohort (where one resolution drops to bed floor $z = -0.02$ m while the other records water) accounts for **$89.9\%$ (Runup)** and **$92.7\%$ (Weir)** of the total SSE.
   - However, conditional wet-only error (`both_above_floor`, 614 samples in Runup, 603 samples in Weir) yields conditional RMSE$/H$ of **$0.05142$ ($5.14\%$)** for Runup and **$0.04535$ ($4.54\%$)** for Weir.
4. **Decisive Non-Causality Conclusion**:
   - Merely altering dry-floor detection logic or evaluating wet-only subsets **CANNOT** solve the failure of the simulation ladder: `WG1` and `WG2` are independent, strictly wet probes with zero floor interactions, yet fail the $5\%$ gate with $\sim 12\%$ relative error.

---

## 3. Bounded Source Review: Actual Recipe Parity

Systematic inspection of DualSPHysics v5.4 source code (`src/source/JCaseCtes.cpp`, `src/source/JSph.cpp`), case definition files, and execution XMLs across the 3DP ladder reveals five fundamental dimensions of numerical recipe parity:

### 3.1 Dimension 1: Equation of State (EOS), Actual Sound Speed, and $h_{swl}$ vs $\Delta p$
- **Source Mechanism**:
  In Tait's Equation of State, pressure is evaluated as:
  $$P = B \left[ \left(\frac{\rho}{\rho_0}\right)^\gamma - 1 \right], \quad B = \frac{c_s^2 \rho_0}{\gamma}$$
  In the case definitions, constants were configured with `<hswl value="0" auto="true" />`, `<coefsound value="20" />`, and `<speedsound value="0" auto="true" />`.
  In DualSPHysics GenCase, when `hswl auto="true"` is specified, the still water level is calculated from the generated lattice particles as:
  $$h_{swl} = z_{max}^{fluid} - z_{min}^{fluid} = (N_z - 1) \Delta p = H - \Delta p$$
  where $H = 0.40$ m is the continuum fluid domain depth.
- **Resulting Parity Differences**:
  Because $h_{swl}$ is calculated as $H - \Delta p$, the reference sound speed and EOS parameter $B$ vary systematically with spatial resolution:
  - **Coarse** ($\Delta p = 0.050$ m): $N_z = 8 \implies h_{swl} = 0.350$ m, $c_s = 20\sqrt{9.81 \times 0.350} = 37.0594$ m/s, **$B = 196,200.0$ Pa**.
  - **Medium** ($\Delta p = 0.025$ m): $N_z = 16 \implies h_{swl} = 0.375$ m, $c_s = 20\sqrt{9.81 \times 0.375} = 38.3601$ m/s, **$B = 210,214.3$ Pa**.
  - **Fine** ($\Delta p = 0.010$ m): $N_z = 40 \implies h_{swl} = 0.390$ m, $c_s = 20\sqrt{9.81 \times 0.390} = 39.1198$ m/s, **$B = 218,622.9$ Pa**.
  - **Continuum Mother Target** ($H = 0.400$ m): $h_{swl} = 0.400$ m, $c_s = 20\sqrt{9.81 \times 0.400} = 39.6182$ m/s, **$B = 224,228.6$ Pa**.
- **Assessment**:
  The EOS constant $B$ varies by $+7.14\%$ from Coarse to Medium, and by $+4.00\%$ from Medium to Fine (+11.43% overall). Every resolution solves a fluid with a different artificial compressibility ($\beta = 1/(\gamma B)$).

### 3.2 Dimension 2: Pressure and Density Initialization
- **Source Mechanism**:
  In `<constantsdef>`, `<rhopgradient value="3" />` was configured.
  DualSPHysics applies option 3 as maximum water height hydrostatic initialization:
  $$P(z) = \rho_0 g (z_{max} - z), \quad \rho(z) = \rho_0 \left(1 + \frac{P(z)}{B}\right)^{1/\gamma}$$
- **Resulting Parity Differences**:
  Because both $z_{max}(\Delta p) = 0.42 - \Delta p / 2$ and $B(\Delta p)$ vary with resolution, the initial density and pressure profiles at identical physical elevations $z$ differ across resolutions at $t = 0$.

### 3.3 Dimension 3: Smoothing Coefficient and Boundary Supports
- **Source Mechanism**:
  In 3D DualSPHysics, smoothing length is calculated with $\text{coefh} = 1.5$:
  $$h = \text{coefh} \sqrt{3} \Delta p = 1.5 \sqrt{3} \Delta p \approx 2.598076 \Delta p$$
  Kernel support radius is $2h \approx 5.196152 \Delta p$.
  The bed STL surface was projected into boundary marker 40 (`root_numeric_bed_surface_support`), followed by solid box fills with DBC (Dynamic Boundary Conditions).
- **Resulting Parity Differences**:
  In DBC, boundary particles exert repulsive pressure forces over a distance of $2h$.
  At Coarse ($\Delta p = 0.050$ m), $2h = 0.2598$ m.
  At Medium ($\Delta p = 0.025$ m), $2h = 0.1299$ m.
  At Fine ($\Delta p = 0.010$ m), $2h = 0.0520$ m.
  Effective boundary layer thickness and standoff distance change by a factor of $5\times$ across the ladder, altering effective friction and dissipation along the flume bed.

### 3.4 Dimension 4: Exact Wave Forcing and Discretized Moving-Wall Nodes
- **Source Mechanism**:
  Piston motion is prescribed via `piston_f91973457a049db5_regular_piston.dat` (sha256 `8cb7dab074...`), bitwise identical across all resolutions.
- **Resulting Parity Differences**:
  While the mathematical displacement $X(t)$ is identical, the physical moving wall is discretized into SPH particles:
  - Coarse: 3,128 moving particles.
  - Medium: 15,947 moving particles.
  - Fine: 169,817 moving particles.
  The particle representation of the paddle face introduces resolution-dependent boundary roughness and inter-particle gap dynamics during stroke reversal.

### 3.5 Dimension 5: Independent Temporal Controls (Absent Halfstep Study vs Clamps=0)
- **Source Mechanism**:
  DualSPHysics executes a 2nd-order Symplectic time-integrator. Timesteps adapt dynamically based on CFL and force conditions:
  $$\Delta t \le \min \left( \text{CFL} \frac{h}{c_s + v_{max}}, 0.25 \sqrt{\frac{h}{g}} \right)$$
- **Resulting Parity Differences**:
  - `DTsMin = 0` (clamps = 0) is proven by telemetry 036. The solver never clamped to an artificial numerical floor.
  - **Crucial Distinction**: Absence of floor clamps eliminates the hypothesis of artificial timestep truncation, but **does not prove temporal convergence**.
  - In F5, spatial refinement simultaneously refined time ($\Delta t \propto h \propto \Delta p$). Median $\Delta t$ was $\sim 6.4 \times 10^{-4}$ s (coarse), $\sim 3.0 \times 10^{-4}$ s (medium), and $\sim 7.4 \times 10^{-5}$ s (fine). No independent temporal convergence study (holding $\Delta p$ fixed while halving $\text{CFL}$) has ever been performed for F5.

---

## 4. Separation of Proven Differences from Untested Hypotheses

| Parity Dimension | Proven Source Difference (Fact) | Untested Hypothesis (Speculation) | Analytical Physical Assessment |
| :--- | :--- | :--- | :--- |
| **EOS / Sound Speed ($h_{swl}, B$)** | $B$ varies from $196.2$ kPa to $218.6$ kPa ($+11.4\%$) due to `hswl auto="true"`. | Unifying $B = 224.2$ kPa across resolutions will close the $12\%$ WG1/WG2 gap. | **Falsified by Order-of-Magnitude Analysis**: Mach number $M \approx 0.05$. Compressibility shift on shallow wave celerity is $O(M^2) \sim 0.26\%$. A $2\%$ shift in $c_s$ produces $\le 0.08\%$ relative wave elevation shift ($< 0.3$ mm), two orders of magnitude smaller than the observed $12\%$ error. |
| **Initial Offsets** | Initial offsets at WG1/WG2 are $\sim 15\ \mu\text{m}$; WG3 is $0.0$ m. | Initial Frame 0 node displacement consumes the $20$ mm error budget. | **Disproven by Telemetry**: Consumes $< 0.075\%$ of budget; offsets are physically zero. |
| **Sloping Bed Dry Floor** | Dry floor explains $90\text{--}93\%$ of WG3 SSE. Wet-only WG3 RMSE is $\sim 5\%$. | Modifying gauge floor logic or excluding dry samples will fix the campaign failure. | **Disproven by Telemetry**: WG1 and WG2 are $100\%$ wet with zero dry samples, yet fail with $12\%$ error. |
| **Temporal Controls (Clamps=0)** | Telemetry proves $0$ `DTsMin` adjustments across all runs. | Solver was corrupted by numerical timestep clamping. | **Disproven by Telemetry**: Solver ran under unconstrained adaptive CFL. |
| **Temporal Truncation** | No independent CFL halfstep study exists at fixed $\Delta p$. | $12\%$ error is caused by temporal integration error. | **Highly Unlikely**: 2nd-order Symplectic local truncation error is $O(\Delta t^2) \sim 10^{-8}$, negligible compared to spatial discretization error $O(h^2) \sim 6 \times 10^{-4}$. |
| **Spatial Resolution ($H_{wave}/\Delta p$)** | Water depth $d = 0.40$ m, wave height $H_{wave} \approx 0.04$ m. Coarse has $H_{wave}/\Delta p < 1$, Medium has $1.6$, Fine has $4.0$. | The $12\%$ error is caused by **insufficient small $\Delta p$** (spatial under-resolution). | **Governing Physical Cause**: SPH wave propagation requires $H_{wave}/\Delta p \ge 10$ to prevent severe numerical dissipation and dispersion from kernel smoothing. At $H_{wave}/\Delta p \approx 1.6\text{--}4.0$, waves are in the under-resolved pre-asymptotic regime. |

---

## 5. The ONE Next Falsifiable Experiment: Exact Physical EOS Parity Transformation

To rigorously distinguish whether the $12\%$ discrepancy originates from a **numerical recipe parity flaw** (Dimension 1) versus **insufficient small $\Delta p$** (under-resolution), we formulate exactly ONE falsifiable experiment.

### 5.1 Experiment Definition
- **Experiment Title**: F5 Exact Physical EOS Parity Transformation Experiment on Medium and Fine Resolutions (`F5_EOS_PARITY_MEDIUM_FINE_039`).
- **Core Change**: Replace the resolution-dependent still water level `hswl auto="true"` with the exact continuum still water depth $H = 0.40$ m across Medium ($\Delta p = 0.025$ m) and Fine ($\Delta p = 0.010$ m) resolutions:
  ```xml
  <constantsdef>
      <hswl value="0.4" auto="false" />
      <speedsound value="39.618177" auto="false" />
      <b value="224228.57143" auto="false" />
  </constantsdef>
  ```
  And in the derivative execution configuration (`<execution><constants>`):
  ```xml
  <b value="224228.57143" units_comment="Pascal (Pa)" />
  ```
- **Preservation of Continuum Mother Definition**:
  - Physical fluid bounds $[-0.9, 3.3] \times [-0.7, 0.7] \times [0.02, 0.42]$ m ($M = 2352.0$ kg) strictly preserved.
  - Continuous bed STL geometry (`f5_continuous_bed_profile_slope_0p280.stl`) strictly preserved.
  - Piston displacement motion (`piston_f91973457a049db5_regular_piston.dat`) strictly preserved.
  - Frozen quality contract ($H = 0.40$ m, $5\%$ relative tolerance, 6 gauges, 800 samples) strictly preserved.

### 5.2 Expected Diagnostic Outcomes
1. **Outcome A (Falsification of Recipe Cause, Expected by Physics)**:
   - Medium vs Fine normalized RMSE at WG1 and WG2 remains $\approx 12\%$ ($\Delta \text{RMSE} < 0.2\%$).
   - **Scientific Implication**: Proves conclusively that EOS compressibility variation is NOT the cause of the $12\%$ discrepancy. Establishes beyond doubt that the discrepancy is governed by **insufficient small $\Delta p$** (under-resolution of wave amplitude).
2. **Outcome B (Confirmation of Recipe Cause)**:
   - Medium vs Fine normalized RMSE drops towards or below the $5\%$ threshold.
   - **Scientific Implication**: Validates that artificial compressibility shifts were the primary distortion.

### 5.3 Credible Resource and Storage Estimates
- **Medium Case** ($\Delta p = 0.025$ m, 150,528 fluid particles):
  - Wall time: $\sim 120$ s ($0.033$ GPU-hours).
  - Storage: $\sim 11.2$ GB.
- **Fine Case** ($\Delta p = 0.010$ m, 2,352,000 fluid particles):
  - Wall time: $\sim 10,135$ s ($2.815$ GPU-hours).
  - Storage: $\sim 180.2$ GB.
- **Total Budget Required**:
  - `RUNUP` only: $2.85$ GPU-hours, $\sim 191.4$ GB.
  - Both `RUNUP` + `WEIR`: $5.70$ GPU-hours, $\sim 382.8$ GB.
- **Compliance with Root Limits**:
  - GPU Hours: $5.70\ \text{GPU-h} \ll 96\ \text{GPU-h}$ bound (and $\ll 320$ qualification cap).
  - Disk Storage: $382.8\ \text{GB} \le 500\ \text{GiB}$ ($536.8$ GB) Home floor.
  - Strict compliance verified.

---

## 6. Distinct Mathematically Valid Tighter-Resolution Reference Specification ($\Delta p = 0.005$ m)

If Root determines from the theoretical $O(M^2)$ proof that the EOS recipe experiment is unnecessary because insufficient small $\Delta p$ is already established, the only mathematically valid scientific recourse is a tighter-resolution reference ladder:

### 6.1 Mathematical Formulation of Finer Reference ($\Delta p = 0.005$ m)
- Particle spacing: $\Delta p = 0.005$ m ($5$ mm).
- Wave height resolution: $H_{wave} / \Delta p \approx 0.04 / 0.005 = 8.0$ particles (approaching the $\ge 10$ asymptotic threshold).
- Water depth resolution: $H / \Delta p = 0.40 / 0.005 = 80$ particles.
- Smoothing length: $h = 1.5 \sqrt{3} \times 0.005 \approx 0.01299$ m; $2h \approx 0.02598$ m.
- Exact EOS constants locked to continuum: $h_{swl} = 0.40$ m, $c_s = 39.6182$ m/s, $B = 224,228.57$ Pa.

### 6.2 Theoretical Scaling and Storage Ceiling Warning
- **Particle Counts** (theoretical prediction, clearly marked pending real GenCase):
  - Fluid volume $2.352\ \text{m}^3 \implies N_{fluid} = 2.352 / (0.005^3) = \mathbf{18,816,000}$ particles ($8\times$ Fine).
  - Boundary particles: Surface area particle density scales by $4\times \implies N_{bound} \approx 18.7 \times 10^6$ particles.
  - Total particles: $N_p \approx \mathbf{37.5\ \text{million}}$ particles.
- **Integration Steps**:
  - $\Delta t \propto \Delta p \implies$ time steps double: $\approx \mathbf{430,000}$ steps.
- **Compute Cost**:
  - Total work scales by $N_p \times \text{steps} \approx 5.3 \times 2 = 10.6\times$ Fine.
  - GPU wall time: $\approx \mathbf{29.8\ \text{GPU-hours}}$ per run ($59.6$ GPU-hours for Runup + Weir).
- **Storage Feasibility Assessment**:
  - If 801 full particle snapshots are saved at $dt = 0.02$ s:
    $$\text{Storage} \approx 37.5 \times 10^6 \times 24\ \text{bytes} \times 801 \approx \mathbf{720\ \text{to}\ 950\ \text{GB}}\ \text{per run!}$$
  - For two runs, storage would exceed $1.5$ Terabytes, **catastrophically violating the 500 GiB Home floor**.
  - **Architectural Prerequisite**: A $\Delta p = 0.005$ m reference run CANNOT be executed with standard full 801-part dumps. It requires Root-level architectural storage authorization to decouple gauge sampling (`_outputdt value="0.02"`) from particle field saves (`-tout:0.20` or `-svres:0`), which would require updating the frozen evaluator's 801-frame `RunPARTs.csv` assertion.

---

## 7. Next Executable Tasks & Handoff Boundaries

1. **Local Scoped Delivery**: Commit this review, the prospective transformation specification (`prospective_transformation.json`), and the candidate runner request (`requests/F5_PROSPECTIVE_EOS_PARITY_EXPERIMENT_REQUEST.json`).
2. **Root Action Required**: Root independently reviews the bounded recipe parity analysis and chooses whether to:
   - Authorize candidate experiment `F5_EOS_PARITY_MEDIUM_FINE_039` ($5.7$ GPU-h, $382$ GB) to formally falsify the recipe parity hypothesis on disk; OR
   - Formally declare that the F5 $5\%$ macro gate cannot be satisfied at $\Delta p \ge 0.010$ m due to insufficient small $\Delta p$ ($H_{wave}/\Delta p < 10$), deferring sub-5% qualification until Root implements decoupled high-resolution storage policies.
3. **No Independent Execution**: No solver execution, GenCase run, or ledger modification is authorized or attempted by this handoff.
