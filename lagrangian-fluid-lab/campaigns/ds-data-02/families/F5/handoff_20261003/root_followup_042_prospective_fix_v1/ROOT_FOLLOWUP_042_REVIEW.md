# F5 Root Followup 042: Technical Review, Negative Finding Synthesis, and Prospective Fallback Fix v1

**Schema**: `ds02.f5.root-followup-042-review.v1`  
**Family ID**: `F5`  
**Scope Directory**: `campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_042_prospective_fix_v1`  
**Date**: `2026-10-04`  
**Process Mode**: Root Followup 042 F5 single-process execution (Gemini 3.8 Flash High, no recursive subagents)  
**Parent Worktree**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`  
**Commit Ref Target**: `codex/ds-data-02-infra`  
**Prior Root Evidence Evaluated**:
- Root024 surface-first geometry & boundary support (`root_surface_first_boundary_preservation_024`)
- Root025 native inputs & actual receipts (`root_surface_first_actual_audit_025`)
- Root042 native schedule halfstep gauge comparison (`root_actual_fine_halfstep_native_schedule_comparison_042`)
- Followup 038 review & diagnostic tooling (`full_halfstep_negative_fallback_v1`)

---

## 1. Executive Summary and Campaign Governance

1. **Governance Status and Context**:
   - **Campaign Goal Progress**: 0/336 finalized, 273/320 qualified, charged 65.3 GPU-hours of 96.0 allocated budget.
   - **Remaining Campaign Reserve**: ~30.7 GPU-hours.
   - **Storage State**: Home floor 500 GiB, free space ~2978 GiB.
   - **Strict Grounding Rule**: Claims require actual data. No invented acceptance thresholds, guarantees, or unique causal assertions. No product completion claimed from code, tests, or JSON definitions alone.

2. **Rootguard Execution Boundary**:
   - All actual scientific CSV, H5, motion, and STL generation or evaluation, as well as GenCase, DualSPHysics, and converter execution, are **Rootguard dispatch ONLY**.
   - No actual scientific worker is launched as an audit or test in this scoped work.
   - No overwriting or using unconsumed old owner outputs as provenance.
   - Deliverables consist strictly of source code, XML definitions, prospective physical registrations, runner requests (`launch_allowed: false`), and synthetic unit test fixtures.

---

## 2. Review of Prior Findings: Root024, Root025, and Root042

### 2.1 Surface-First Recipe Geometry (Root024) and Native Evidence (Root025)
- In `root_surface_first_boundary_preservation_024`, the bed geometry was repaired via a 60-triangle surface-first support mesh rasterized before wall/piston elements, alongside continuous bed STL `assets/f5_continuous_bed_profile_slope_0p280.stl` (`SHA256: 93cf180ae6d5439d3ed3e2787b390d3b1268d76f0069dbdeaa10b18bf3314621`).
- In `root_surface_first_actual_audit_025`, actual fine ($\Delta p = 0.010$ m) GenCase executions completed with code 0:
  - Runup (`F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024`): 7,031,723 total particles.
  - Weir (`F5_REF_WEIR_DP010_SURFACE_FIRST_SUPPORT_024`): 7,083,939 total particles.
  - Preserved continuous fluid mass $2,352.0$ kg ($2,352,000$ fluid particles).

### 2.2 Fine Temporal Halfstep Comparison (Root042)
- The fine temporal halfstep runs evaluated time sensitivity with CFL halved from 0.20 to 0.10 and CoefDtMin from 0.05 to 0.025:
  - Runup: `root-runup-fine-temporal-halfstep-cfl01-dtmin025-full16-040` (`COMPLETED0`)
  - Weir: `root-weir-fine-temporal-halfstep-cfl01-dtmin025-full16-040` (`COMPLETED0`)
  - Native interval telemetry: zero $DT_{\text{min}}$ clamping adjustments (`total_DT_min_adjustments = 0`), zero particle domain exclusions (`native_NpOut_interval_sum = 0`).
- Root042 evaluated the frozen conjunction gate across all 6 wave gauges:
  $$\frac{\text{RMSE}}{H} \le 0.01 \quad \mathbf{AND} \quad \frac{\max|\Delta\eta|}{H} \le 0.01 \quad (H = 0.40\text{ m})$$
- **Outcome**: Both mechanisms strictly failed the conjunction gate on active wave probes.

### 2.3 Causal Separation: Observer Flaws vs Physical Dispersion
Detailed inspection reveals two distinct factors contributing to gauge discrepancy:
1. **Observer Validity Defect 1: Baseline Gauge Sub-Bed Embedding**:
   - In the Root024 XML definitions, every wave gauge was assigned `point0.z = -0.020` m.
   - On the sloping bed ($x \ge 3.55$ m), the continuous bed rises up to $+0.840$ m.
   - At `WG4` ($x = 5.45$ m), the local bed is at $z_{\text{bed}} = 0.532$ m, placing `point0.z` **$55.2$ cm below solid rock**.
   - Under DualSPHysics `JDsGaugeItem.cpp:782`, when fluid drains below the detection threshold, the reported surface position collapses to `point0.z`.
   - On `WG4`, when water receded in one run while a thin layer remained in the other, the gauge collapsed to $-0.020$ m, generating an artificial step error of $0.609$ m ($1.523 H$).
   - This is an observer geometry coordinate defect, not a physical hydrodynamic divergence.
2. **Observer Validity Defect 2: Turbulent Surface Threshold Dips**:
   - On breaking wave surfaces, lateral particle aeration momentarily drops fluid mass at the topmost probe test node below `MassLimit`, causing single-frame jumps of $2\text{--}3$ particle spacings ($\approx 25$ mm).
3. **Physical Solver Sensitivity: Dispersion Under CFL Halving**:
   - On flat-bed probes (`WG1`, `WG2`), relative RMSE was small ($\text{RMSE}/H \in [0.0041, 0.0066] \le 0.0100$).
   - However, steep wave fronts ($\partial\eta/\partial t \approx 3.0$ m/s) exhibited small phase shifts (~$8$ ms) between CFL=0.2 and CFL=0.1, projecting onto pointwise metrics as localized spikes ($\max|\Delta\eta|/H \approx 0.10\text{--}0.12$).
4. **Governance Rule on Causality**:
   - High error concentration (e.g. >85% of squared error in 1% of samples) is **strictly descriptive**. It does NOT prove sole causality and does NOT authorize filtering, phase alignment, or sample elimination. The primary metric remains tied to the unmodified full window.

---

## 3. Transition to Mandated Legal Fallback

### 3.1 Policy Authority and Root Cause Budget
- Under DS-DATA-02 campaign governance, each defect class is limited to **at most 2 root-cause repairs**.
- Geometry wall-gap leakage consumed Repair 1 (autofill bound) and Repair 2 (surface-first STL + boundary support).
- A 12h quarterstep run ($\approx 24$ GPU-hours) was rejected because it would exhaust campaign reserves (~30.7 GPUh remaining) without resolving observer defects or spatial non-convergence.
- Under `plan-source/families/F5.md` line 47:
  $$\mathbf{“失败后备：先规则/单波有限事件，再波包；主范围可比复杂地形更简单，但必须包含爬升/越堤真实事件。”}$$
- Therefore, transitioning to a **finite single-wave packet event** is the authorized, source-grounded fallback.

### 3.2 Physical Mechanisms Preserved (No Quiet Empty Box, No Learning)
A valid fallback cannot be an unforced or trivial quiescent box. Both required F5 hydrodynamic mechanisms are fully preserved:
1. **Mechanism 1: Sloping Bed Runup, Breaking, and Return Flow (`runup_return`)**:
   - 3D flume ($11.95$ m $\times$ $1.44$ m), depth $H = 0.40$ m, continuous sloping bed ($m = 0.280$).
   - Driven by finite single-wave packet (`control_single_packet.dat`, duration $7.5$ s, max stroke $2.80$ cm).
   - Generates solitary shoaling, peak runup excursion on the slope, breaking, and return flow drawdown.
   - For $t \ge 7.5$ s, paddle remains stationary, completely eliminating wavemaker reflection interference and multi-harmonic standing waves.
2. **Mechanism 2: Notched Weir Overtopping and Retention Paired Background (`weir_pair`)**:
   - Retains low weir structure ($x \in [4.96, 5.20]$ m, base $z = 0.3648$ m, crest $z = 0.4748$ m, lateral notch $y \in [0.25, 0.50]$ m).
   - Finite wave packet approaches weir: overtopping cohort spills over notch and crest into receiving basin, while non-overtopping cohort is retained and reflects downslope.
   - Clean, finite mass overtopping budget into downstream basin.

### 3.3 Authentic Observer Geometry Correction (No Invented Bed Crest)
- In the fallback specification, probe baselines `point0.z` are aligned with local continuous bed elevation $z_{\text{bed}}(x)$:
  - `WG1`: $x = 2.00$ m, $z_{\text{bed}} = 0.000$ m $\implies \text{point0.z} = 0.000$ m
  - `WG2`: $x = 3.10$ m, $z_{\text{bed}} = 0.000$ m $\implies \text{point0.z} = 0.000$ m
  - `RunupToe`: $x = 3.55$ m, $z_{\text{bed}} = 0.000$ m $\implies \text{point0.z} = 0.000$ m
  - `WG3`: $x = 4.35$ m, $z_{\text{bed}} = (4.35 - 3.55) \times 0.280 = 0.224$ m $\implies \text{point0.z} = 0.224$ m
  - `WG4`: $x = 5.45$ m, $z_{\text{bed}} = (5.45 - 3.55) \times 0.280 = 0.532$ m $\implies \text{point0.z} = 0.532$ m
  - `Crest`: $x = 6.70$ m, $z_{\text{bed}} = 0.840$ m $\implies \text{point0.z} = 0.840$ m
- **Bed Crest Precision Note**: Between $x = 6.55$ m and $x = 7.15$ m, the continuous bed profile is a horizontal crest plateau at $z = 0.840$ m. The elevation at $x = 6.70$ m is strictly $0.840$ m, NOT an extrapolated $0.882$ m. This adheres strictly to the rule: "No invented SHA or bed crest."

---

## 4. Commensurate Three-Resolution Ladder ($\Delta p = 0.050, 0.025, 0.010$ m)

To enable systematic spatial convergence under the legal fallback recipe, definitions are established across three commensurate resolutions:

| Resolution | $\Delta p$ [m] | Commensurate Ratio | Case ID (Runup) | Case ID (Weir) | Predicted Fluid Particles | Predicted Total Particles | Fluid Mass [kg] |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Coarse** | $0.050$ | $1\times$ | `F5_REF_RUNUP_DP050_FALLBACK_042` | `F5_REF_WEIR_DP050_FALLBACK_042` | $18,816$ | $\approx 55,800$ | $2,352.0$ |
| **Medium** | $0.025$ | $2\times$ | `F5_REF_RUNUP_DP025_FALLBACK_042` | `F5_REF_WEIR_DP025_FALLBACK_042` | $150,528$ | $\approx 455,500$ | $2,352.0$ |
| **Fine** | $0.010$ | $5\times$ | `F5_REF_RUNUP_DP010_FALLBACK_042` | `F5_REF_WEIR_DP010_FALLBACK_042` | $2,352,000$ | $\approx 7,052,000$ | $2,352.0$ |

*Disclaimer: Particle counts listed above are analytical volume estimates ($V / \Delta p^3$) and scaled boundary estimates; they are clearly predicted quantities, not actual simulation outputs.*

---

## 5. Deliverables Inventory in `root_followup_042_prospective_fix_v1`

1. **Continuous Bed STL Generator (`generate_continuous_bed_stl.py`)**:
   - Mathematical synthesis of 60 watertight triangles from 8 profile nodes.
   - Hash validator verifying match against official immutable hash `93cf180ae6d5439d3ed3e2787b390d3b1268d76f0069dbdeaa10b18bf3314621`.
2. **Single-Packet Motion Generator (`generate_single_packet_motion.py`)**:
   - Hann-modulated finite wave packet generator.
   - Produces 641-point 16.0 s table with max excursion $2.80$ cm and stationary tail $\ge 7.5$ s.
3. **Case Preparation Worker (`prepare_fallback_cases.py`)**:
   - Synthesizes all 6 XML case definitions with Root024 surface-first bed support mesh, corrected observer coordinates, and 3 commensurate resolutions.
4. **Prospective Specification (`prospective_nominal_pair_specification.json`)**:
   - Formal ds02 physical specification for nominal pair and 3 commensurate DPs.
5. **XML Case Definitions (`definitions/`)**:
   - 3 Runup XMLs (`definitions/runup/F5_REF_RUNUP_DP*.xml`)
   - 3 Weir XMLs (`definitions/weir/F5_REF_WEIR_DP*.xml`)
6. **Rootguard Runner Requests (`requests/`)**:
   - `requests/F5_FALLBACK_PREPARATION_REQUEST.json`: Bounded CPU preparation request (`launch_allowed: false`).
   - `requests/F5_FALLBACK_GENCASE_3DP_REQUEST.json`: Bounded CPU GenCase request (`launch_allowed: false`).
   - `requests/F5_FALLBACK_SOLVER_3DP_REQUEST.json`: GPU solver request for 6 cases (~13.1 GPUh, `launch_allowed: false`).
7. **Synthetic Unit Test Suite (`test_prospective_fix_v1.py`)**:
   - Unit tests covering geometry, motion, observer alignment, particle scaling, XML structure, and request governance.
8. **Scope Manifest (`manifest.json`)**:
   - Formal catalog of all scope artifacts with byte counts and SHA256 digests.

---

## 6. Next Executable Tasks for Root

1. **Review Runner Requests**: Root inspects `requests/F5_FALLBACK_PREPARATION_REQUEST.json` and `requests/F5_FALLBACK_GENCASE_3DP_REQUEST.json`.
2. **Rootguard Dispatch**: When authorized, Root launches preparation and GenCase under shared DS-DATA-02 runner with GPU lease reservation.
3. **Standby**: Local agent maintains zero autonomous simulation runs; awaits explicit Root directive.
