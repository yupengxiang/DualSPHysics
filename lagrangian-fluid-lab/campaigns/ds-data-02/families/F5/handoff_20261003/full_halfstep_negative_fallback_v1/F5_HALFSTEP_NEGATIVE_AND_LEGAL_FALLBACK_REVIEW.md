# F5 Fine Halfstep Negative Result Review, Source-Operator Analysis, and Legal Fallback Specification

**Schema**: `ds02.f5.halfstep-negative-and-legal-fallback-review.v1`  
**Family ID**: `F5`  
**Target Scope Directory**: `campaigns/ds-data-02/families/F5/handoff_20261003/full_halfstep_negative_fallback_v1`  
**Date**: `2026-10-04`  
**Process Mode**: Root Followup 038 F5 under strict single-process execution (no recursive subagents)  
**Parent Worktree**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`  
**Root Result Evaluated**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_FINE_ACTUAL_FULL_HALFSTEP_ALL_GAUGES/root-fine-two-mechanism-native-schedule-halfstep-all-six-gauges-042/halfstep-gauge-comparison.json`  

---

## 1. Executive Summary and Governance Context

1. **Root Followup 038 Mandate**:
   - Work strictly within the isolated scope directory `campaigns/ds-data-02/families/F5/handoff_20261003/full_halfstep_negative_fallback_v1`.
   - All consumed baseline and historical assets remain completely immutable.
   - Root owns all actual scientific simulations, array audits, solver runs, and data conversions.
   - Candidate runner requests declare `"launch_allowed": false` and `"launch_owner": "root"`.
   - No claim of qualification or production pass is made from code, tests, or JSON files.

2. **Authoritative Outcome of the Two-Mechanism Fine Halfstep Runs**:
   - Both actual fine ($\Delta p = 0.010$ m) simulations—Runup (`root-runup-fine-temporal-halfstep-cfl01-dtmin025-full16-040`) and Weir (`root-weir-fine-temporal-halfstep-cfl01-dtmin025-full16-040`)—completed with returncode 0 (`COMPLETED0`).
   - The Root comparison evaluation (`root-fine-two-mechanism-native-schedule-halfstep-all-six-gauges-042`) evaluated the frozen conjunction gate across all 6 wave gauges:
     $$\frac{\text{RMSE}}{H} \le 0.01 \quad \mathbf{AND} \quad \frac{\max |\Delta \eta|}{H} \le 0.01 \quad (H = 0.40\text{ m})$$
   - **Both mechanisms fail the frozen conjunction gate on active wave probes.**
   - Native interval telemetry confirms:
     - `total_DT_min_adjustments = 0` across all steps in both runs (zero numerical time-step floor clamping).
     - `native_NpOut_interval_sum = 0` across all 801 time frames in both runs (zero particle exclusions from domain).

3. **Inviolable Governance Guardrails**:
   - **Do not claim time eliminated**: The halfstep runs did not pass the conjunction gate; temporal sensitivity remains present.
   - **Do not phase-align or time-shift**: The primary metric evaluates unmodified timestamps over the full 800 uniform evaluation samples ($[0.0, 15.98]$ s) under original linear interpolation as established in Root 035.
   - **Do not drop dry cohorts**: Entire primary error is evaluated over all 800 samples without filtering.
   - **Do not relax maximum budget**: The $0.01$ integration share ($0.20 \times 0.05$ macro budget, $0.004$ m) is strictly preserved.
   - **Permanence of prior spatial failure**: The ~12% spatial non-convergence observed on the flat-bed probes between Medium ($\Delta p = 0.025$ m) and Fine ($\Delta p = 0.010$ m) remains an authentic, verified negative result.
   - **Max 2 root-cause repair policy**: The wall-gap / geometry leak defect consumed its allocated 2 repairs (Repair 1: autofill bound, Repair 2: surface-first continuous bed STL + boundary support).
   - **Prohibition of 12h quarterstep**: Proposing a quarterstep run ($\text{CFL} = 0.05$, $\text{CoefDtMin} = 0.0125$) would require $\approx 24$ GPU-hours for two cases, consuming nearly all of the remaining $\approx 32$ GPU-hour campaign reserve without resolving the underlying Eulerian observer defects or the 12% spatial ladder gap.
   - **Mandated legal fallback**: Under `plan-source/families/F5.md` line 47, F5 must pivot to its authorized legal fallback: a finite single-wave packet event preserving the intended wave runup, breaking, and overtopping mechanisms.

---

## 2. Quantitative Review of Root 042 Halfstep Comparison

### 2.1 Metric Results Table

Evaluated against reference depth and wave scale $H = 0.40$ m, tolerance budget $\text{Tol} = 0.01 H = 0.0040$ m:

| Mechanism | Probe | Location / Bed Condition | Relative RMSE ($\text{RMSE}/H$) | Relative Max Abs ($\max|\Delta\eta|/H$) | Conjunction Gate ($\le 0.01$) | Primary Failure Mode |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Runup** | **WG1** | $x = 2.00$ m (flat bed, $z_{\text{bed}} = 0$) | $0.00653$ (PASS) | **$0.11696$ (FAIL)** | **FAIL** | Wave front phase timing spike ($t = 3.10$ s) |
| **Runup** | **WG2** | $x = 3.10$ m (flat bed, $z_{\text{bed}} = 0$) | $0.00573$ (PASS) | **$0.10327$ (FAIL)** | **FAIL** | Wave crest timing spike ($t = 7.48$ s) |
| **Runup** | **WG3** | $x = 4.35$ m (sloping bed, $z_{\text{bed}} = 0.224$) | **$0.03046$ (FAIL)** | **$0.74854$ (FAIL)** | **FAIL** | SWL floor dropout jump ($t = 6.76$ s) |
| **Runup** | **WG4** | $x = 5.45$ m (upper slope, $z_{\text{bed}} = 0.532$) | **$0.11961$ (FAIL)** | **$1.52303$ (FAIL)** | **FAIL** | SWL floor dropout jump ($t = 8.48$ s) |
| **Runup** | **RunupToe** | $x = 3.55$ m (slope toe, $z_{\text{bed}} = 0$) | $0.00436$ (PASS) | **$0.01806$ (FAIL)** | **FAIL** | Wave crest peak timing ($t = 7.90$ s) |
| **Runup** | **Crest** | $x = 6.70$ m (flume crest, $z_{\text{bed}} = 0.882$) | $0.00000$ (PASS) | $0.00000$ (PASS) | PASS | Trivially dry (800/800 floor) |
| **Weir** | **WG1** | $x = 2.00$ m (flat bed, $z_{\text{bed}} = 0$) | $0.00415$ (PASS) | **$0.01963$ (FAIL)** | **FAIL** | Peak crest timing ($t = 8.16$ s) |
| **Weir** | **WG2** | $x = 3.10$ m (flat bed, $z_{\text{bed}} = 0$) | $0.00665$ (PASS) | **$0.08076$ (FAIL)** | **FAIL** | Single-frame surface threshold dip ($t = 2.62$ s) |
| **Weir** | **WG3** | $x = 4.35$ m (sloping bed, $z_{\text{bed}} = 0.224$) | $0.00637$ (PASS) | **$0.03719$ (FAIL)** | **FAIL** | Front transition timing ($t = 6.74$ s) |
| **Weir** | **WG4** | $x = 5.45$ m (behind weir crest, $z_{\text{bed}} = 0.532$) | $0.00000$ (PASS) | $0.00000$ (PASS) | PASS | Trivially dry (800/800 floor) |
| **Weir** | **RunupToe** | $x = 3.55$ m (slope toe, $z_{\text{bed}} = 0$) | $0.00546$ (PASS) | **$0.02487$ (FAIL)** | **FAIL** | Front transition timing ($t = 10.68$ s) |
| **Weir** | **Crest** | $x = 6.70$ m (flume crest, $z_{\text{bed}} = 0.882$) | $0.00000$ (PASS) | $0.00000$ (PASS) | PASS | Trivially dry (800/800 floor) |

### 2.2 Key Empirical Observations

1. **RMSE vs Max Discrepancy Duality**:
   - For all flat-bed probes in Runup (`WG1`, `WG2`, `RunupToe`) and all active probes in Weir (`WG1`, `WG2`, `WG3`, `RunupToe`), the relative RMSE is strictly within the $1.0\%$ contractual budget ($\text{RMSE}/H \in [0.00415, 0.00665] \le 0.0100$).
   - Yet every active probe fails the $\max|\Delta\eta|/H \le 0.01$ threshold.
2. **Extreme Discrepancy on Sloping Bed Probes in Runup (`WG3`, `WG4`)**:
   - On `WG4`, relative maximum error reaches $1.52303 H$ ($0.609$ m, exceeding the total still water depth by $1.5\times$!).
   - On `WG3`, relative maximum error reaches $0.74854 H$ ($0.299$ m).
   - In contrast, in the Weir case, `WG4` is protected behind the weir crest and remains dry, where error is identically zero.

---

## 3. Source-Operator Detector Analysis: Separating Observer Defects from Physical Sensitivity

To determine the defensible next step, we must rigorously separate defects in **observer validity** (the Eulerian measurement instrument) from **physical solver sensitivity** (the CFD continuum response to $\Delta t$).

### 3.1 Observer Validity Defect 1: Baseline Gauge Embedding and Floor Collapse

1. **C++ Implementation in DualSPHysics (`JDsGaugeItem.cpp:758-787`)**:
   - The Eulerian wave gauge `swl` evaluates fluid mass along a vertical line of test nodes from `point0` to `point2` spaced by $\Delta z_{\text{probe}} = \text{coefdp} \cdot \Delta p = 0.005$ m.
   - At each test node $i$, fluid mass is interpolated: $m_i = m_{\text{fluid}} \sum_b W_{ib} \frac{m_b}{\rho_b}$.
   - The free surface position is defined as the highest point where $m_i \ge \text{MassLimit} = 0.5 \times m_{\text{fluid}}$.
   - **The Fallback Clause (`line 782`)**:
     ```cpp
     if (ptsurf.x == DBL_MAX) ptsurf = Point0 + (PointDir * (mpre ? PointNp : 0));
     ```
     When no test node detects fluid mass above `MassLimit` (e.g., when the fluid recedes or the layer is thinner than the kernel support), the reported elevation collapses directly to `Point0.z`.

2. **Geometric Misalignment Across the Domain**:
   - In all generated XMLs (`F5_REF_RUNUP_*.xml`, `F5_REF_WEIR_*.xml`), every single probe was assigned an identical baseline coordinate:
     $$\text{point0.z} = -0.020\text{ m}$$
   - However, the tank bed is continuous and sloping for $x \ge 3.55$ m:
     $$z_{\text{bed}}(x) = \max(0.0,\ (x - 3.55) \times 0.280\text{ m})$$

| Gauge | $x$ Coordinate | Bed Elevation $z_{\text{bed}}$ | Baseline `point0.z` | Solid Bed Embedding Depth $d_{\text{embed}}$ | Embedding Ratio $d_{\text{embed}} / H$ |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **WG1** | $2.00$ m | $0.000$ m | $-0.020$ m | $0.020$ m | $0.050 H$ |
| **WG2** | $3.10$ m | $0.000$ m | $-0.020$ m | $0.020$ m | $0.050 H$ |
| **RunupToe** | $3.55$ m | $0.000$ m | $-0.020$ m | $0.020$ m | $0.050 H$ |
| **WG3** | $4.35$ m | $0.224$ m | $-0.020$ m | **$0.244$ m** | **$0.610 H$** |
| **WG4** | $5.45$ m | $0.532$ m | $-0.020$ m | **$0.552$ m** | **$1.380 H$** |
| **Crest** | $6.70$ m | $0.882$ m | $-0.020$ m | **$0.902$ m** | **$2.255 H$** |

3. **Consequence of the Embedding**:
   - At `WG4`, when water is present, the surface is at $z \approx 0.589$ m.
   - When water recedes or the swash layer thins below kernel support, the gauge output falls back to `point0.z = -0.020` m instead of the local bed elevation ($+0.532$ m).
   - At $t = 8.48$ s, the nominal run recorded $z = 0.5892$ m while the halfstep run recorded $z = -0.0200$ m (floor).
   - The discrepancy is:
     $$\Delta z = 0.5892 - (-0.0200) = 0.6092\text{ m} \equiv 1.523 H!$$
   - **Conclusion**: This is NOT a 150% physical wave amplitude discrepancy. It is a coordinate artifact caused by placing the observer's default fallback value $55.2$ cm inside solid rock.

### 3.2 Observer Validity Defect 2: Momentary Single-Frame Surface Threshold Dips

1. Detailed audit of Weir `WG2` reveals:
   - At $t = 2.60$ s: nominal $0.4429$ m, halfstep $0.4438$ m ($\Delta = -0.9$ mm).
   - At $t = 2.62$ s: nominal $0.4501$ m, halfstep **$0.4178$ m** ($\mathbf{\Delta = +32.3}$ mm $\equiv 0.081 H$).
   - At $t = 2.64$ s: nominal $0.4533$ m, halfstep $0.4530$ m ($\Delta = +0.3$ mm).
2. Physical interpretation:
   - In a single $0.02$ s frame, the halfstep Eulerian gauge dropped $26$ mm and immediately rebounded $35$ mm in the next frame.
   - On a turbulent, breaking wave surface, individual particles experience local lateral spacing fluctuations. When the topmost particle moves slightly off the probe line, the mass sum at the uppermost test point dips below `MassLimit`, causing the detected free-surface height to jump down by $2\text{--}3$ particle spacings ($\approx 25$ mm).
   - This isolated single-sample measurement glitch constitutes the entirety of the maximum error on Weir `WG2`.

### 3.3 Physical Solver Sensitivity: Phase and Timing Dispersion Under CFL Halving

1. On continuous, fully wet probes (`WG1`, `WG2`):
   - In Runup `WG1` at $t = 3.10$ s, the error spikes to $\Delta \eta = 0.0468$ m ($0.117 H$).
   - Immediately before ($t = 3.08$ s), the error is $-0.0020$ m ($-0.005 H$).
   - Immediately after ($t = 3.12$ s), the error is $+0.0010$ m ($+0.0025 H$).
   - Inspection shows that between $t = 3.08$ s and $3.12$ s, the steep front of the incident wave passes `WG1`, rising from $0.36$ m to $0.48$ m in $0.04$ s (vertical velocity $\partial \eta / \partial t \approx 3.0$ m/s).
   - A temporal shift of merely **$8$ ms** (less than half of the $20$ ms output cadence) between CFL=0.2 and CFL=0.1 shifts the elevation on this steep front by:
     $$\Delta \eta \approx \frac{\partial \eta}{\partial t} \times \Delta t_{\text{shift}} \approx 3.0\text{ m/s} \times 0.008\text{ s} \approx 0.024\text{ m} \sim 0.06 H$$
2. **Causal Distinction**:
   - The Symplectic integrator has second-order local truncation error $O(\Delta t^2)$. Halving CFL and CoefDtMin halves the time step throughout the domain, producing minor phase dispersion changes.
   - On very steep wave fronts, minute physical phase shifts project onto Eulerian pointwise metrics as large vertical discrepancies.
   - However, the global $L_2$ error (RMSE) remains small ($\le 0.65\%$), confirming that the overall wave profile is well captured.

### 3.4 Governance Rule on Discrepancy Concentration

- The concentration metrics computed by `audit_halfstep_discrepancies.py` demonstrate that for `WG4`, **$100\%$ of total squared error** is concentrated in only $8$ samples (top 1% of the window), and for `WG3`, **$87.2\%$ of total squared error** is concentrated in $8$ samples.
- **Strict Boundary**: This concentration is **strictly descriptive**. It does NOT prove causality and does NOT authorize filtering, phase alignment, or sample elimination. The primary contract error must evaluate the full, unmodified 800-sample window.

---

## 4. Bounded CPU Audit Tooling and Runner Request

To ensure complete reproducibility and enable Root to execute the diagnostic independently, we deliver:

1. **Standalone Audit Script**: `audit_halfstep_discrepancies.py`
   - Replicates Root035/Root042 linear interpolation with exact timestamp fidelity.
   - Retains the entire primary error over the full 800 uniform samples in $[0.0, 15.98]$ s.
   - Outputs pointwise maximum discrepancy events, top 5 discrepancy samples, high-discrepancy time windows, and contributor concentration fractions.
   - Evaluates descriptive SWL floor and dropout flags alongside continuous bed embedding depths.
   - Pins all 12 source CSV hashes, 4 execution receipts, and the Root042 comparison JSON.
2. **Bounded CPU Runner Request**: `requests/F5_HALFSTEP_DISCREPANCY_AUDIT_REQUEST.json`
   - Schema: `ds02.runner-request.v2`
   - Governed under: `"launch_allowed": false`, `"launch_owner": "root"`
   - Bounded execution cap: 300 wall seconds, 1 CPU thread, 0 GPU.
   - Pinned inputs: 33 verified file paths and SHA256 digests.

---

## 5. Legally Justified Prospective Fallback Specification

### 5.1 Policy Authority and Root Cause Budget
- Under DS-DATA-02 campaign governance, each defect class is limited to **at most 2 root-cause repairs**.
- The wall-gap leakage defect used Repair 1 (autofill bound) and Repair 2 (surface-first STL + boundary support).
- The subsequent spatial ladder failed ($\sim 12\%$ relative error on flat bed), and the temporal halfstep run failed the conjunction gate on all active wave gauges.
- A quarterstep run ($\approx 24$ GPU-hours) would leave the family with $<8$ GPU-hours, exhausting campaign resources while leaving the Eulerian observer flaws unaddressed.
- Under `plan-source/families/F5.md` line 47:
  $$\mathbf{“失败后备：先规则/单波有限事件，再波包；主范围可比复杂地形更简单，但必须包含爬升/越堤真实事件。”}$$
- Therefore, transitioning to a **finite single-wave packet event** is the legally mandated, source-grounded fallback.

### 5.2 Preservation of Intended Physical Mechanisms
A valid fallback cannot be a "trivial quiet box" (e.g. still water with zero forcing). The prospective fallback preserves both required F5 mechanisms:

1. **Mechanism 1: Sloping Bed Runup, Breaking, and Return Flow (`runup_return`)**:
   - Retains the full 3D flume ($11.95$ m $\times$ $1.44$ m), still water depth $H = 0.40$ m, and the continuous sloping bed STL ($m = 0.280$).
   - Driven by a finite wave packet (`control_single_packet.dat`, duration $7.5$ s, max stroke $3.0$ cm).
   - The paddle motion launches a solitary-like wave that shoals, breaks, climbs to a peak runup excursion on the slope, and recedes downslope back into the basin.
   - For $t > 7.5$ s, the paddle is completely stationary, eliminating wavemaker reflection interference and allowing clean measurement of the return flow.

2. **Mechanism 2: Notched Weir Overtopping and Retention Paired Background (`weir_pair`)**:
   - Retains the low weir structure ($x = 4.96$ m, crest $z = 0.4748$ m, lateral notch $y \in [0.25, 0.50]$ m) and downstream receiving basin.
   - The finite wave packet approaches the weir: the overtopping cohort spills over the notch and crest into the receiving zone, while the non-overtopping cohort is reflected back downslope.
   - Provides a clean, finite mass overtopping budget into the receiving zone without continuous chaotic re-reflection.

### 5.3 Correction of Eulerian Observer Geometry
In the prospective fallback definition:
- Every probe baseline `point0.z` is set exactly to the local continuous bed elevation $z_{\text{bed}}(x)$:
  - `WG1`: $x = 2.00$ m, `point0.z = 0.000` m
  - `WG2`: $x = 3.10$ m, `point0.z = 0.000` m
  - `RunupToe`: $x = 3.55$ m, `point0.z = 0.000` m
  - `WG3`: $x = 4.35$ m, `point0.z = 0.224` m
  - `WG4`: $x = 5.45$ m, `point0.z = 0.532` m
  - `Crest`: $x = 6.70$ m, `point0.z = 0.882` m
- When fluid drains completely at `WG3` or `WG4`, the gauge defaults to the physical bed surface rather than $-0.02$ m, completely eliminating the $0.55\text{--}0.90$ m unphysical coordinate step jumps.

### 5.4 Contract and Native Label Compatibility
- Full 16.0 s simulation window ($T_{\text{max}} = 16.0$ s, $\text{TimeOut} = 0.02$ s, 801 particle parts, 800 gauge rows).
- Invariant error budgets: $0.05$ macro budget ($0.020$ m), $0.01$ integration allocation ($0.004$ m).
- Fully compatible with `event_definitions.json` event phases (`initial_quiescent`, `wave_generation`, `incident_propagation`, `slope_runup`, `weir_passage`, `return_flow`, `terminal_accounting`).
- Materializes required native Lagrangian particle labels: `origin_band`, `toe_first_arrival_time_s`, `crest_first_passage_time_s`, `repeat_crossing_count`, and `terminal_destination`.

---

## 6. Deliverable Artifacts and Checkpoint

| Artifact | Schema / Format | Description |
| :--- | :--- | :--- |
| `F5_HALFSTEP_NEGATIVE_AND_LEGAL_FALLBACK_REVIEW.md` | Markdown | Comprehensive review of Root042 negative halfstep result, source-operator detector analysis, and legal fallback specification. |
| `audit_halfstep_discrepancies.py` | Python 3 | Executable bounded CPU audit script replicating Root035/042 interpolation, identifying peak samples/windows, concentration, and descriptive floor flags. |
| `requests/F5_HALFSTEP_DISCREPANCY_AUDIT_REQUEST.json` | `ds02.runner-request.v2` | Bounded CPU runner request (`launch_allowed: false`, `launch_owner: "root"`) with 33 pinned input hashes. |
| `prospective_fallback_definition.json` | `ds02.f5.prospective-fallback-specification.v1` | Complete specification of legal single-packet fallback recipe for Runup and Weir mechanisms with corrected observer geometry. |
| `requests/F5_PROSPECTIVE_FALLBACK_PREPARATION_REQUEST.json` | `ds02.runner-request.v2` | Prospective preparation request (`launch_allowed: false`, `launch_owner: "root"`). |
| `test_audit_and_fallback.py` | Pytest | Test suite verifying source hashes, metric replication, concentration calculation, schema validity, and governance assertions. |
| `manifest.json` | `ds02.f5.manifest.v1` | Scope manifest with SHA256 digests and formal governance declarations. |

---

## 7. Next Executable Tasks for Root

1. **Review Audit Request**: Independently review candidate request `requests/F5_HALFSTEP_DISCREPANCY_AUDIT_REQUEST.json` and execute bounded CPU audit if authorized.
2. **Review Fallback Specification**: Evaluate `prospective_fallback_definition.json` against campaign budget and qualification targets.
3. **Standby**: Maintain zero autonomous simulation launch; await explicit Root directive.
