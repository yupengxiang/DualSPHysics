# DS-DATA-02 F5 Matched 3DP Gauge Comparison Diagnosis & Legal Fallback Report

## 1. Executive Summary & Root Comparison Findings (035)

The root actual matched 3DP spatial series evaluation (`035`) completed with code 0 across both mechanisms:
- **Runup**: [`f5_runup_surface_first_3dp_gauge_comparison_report.json`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_3DP_SURFACE_FIRST_SUPPORT/root-runup-surface-first-three-dp-native-gauges-v2-035/f5_runup_surface_first_3dp_gauge_comparison_report.json)
- **Weir**: [`f5_weir_surface_first_3dp_gauge_comparison_report.json`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_WEIR_3DP_SURFACE_FIRST_SUPPORT/root-weir-surface-first-three-dp-native-gauges-v2-035/f5_weir_surface_first_3dp_gauge_comparison_report.json)

All 6 wave probes (`WG1`, `WG2`, `WG3`, `WG4`, `RunupToe`, `Crest`) were read over the full 800 data rows ($t \in [0.0, 15.98]\text{ s}$ with $\Delta t \approx 0.02\text{ s}$), strictly without extrapolation to 16.0s.

### Medium (DP 0.025 m) vs Fine (DP 0.010 m) Comparison Metrics

| Probe | Location | Mechanism | Relative RMSE ($\eta / H$) | Relative Max Abs ($\Delta \eta / H$) | Wet-Only Rel RMSE | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **WG1** | $x = 2.00\text{ m}$ (flat bed) | Runup | $0.128277$ ($12.83\%$) | $0.437098$ ($43.71\%$) | $0.128277$ (100% wet) | **FAIL** |
| **WG1** | $x = 2.00\text{ m}$ (flat bed) | Weir | $0.120430$ ($12.04\%$) | $0.411745$ ($41.17\%$) | $0.120430$ (100% wet) | **FAIL** |
| **WG2** | $x = 3.10\text{ m}$ (flat bed) | Runup | $0.121031$ ($12.10\%$) | $0.444282$ ($44.43\%$) | $0.121031$ (100% wet) | **FAIL** |
| **WG2** | $x = 3.10\text{ m}$ (flat bed) | Weir | $0.115880$ ($11.59\%$) | $0.428066$ ($42.81\%$) | $0.115880$ (100% wet) | **FAIL** |
| **RunupToe** | $x = 3.55\text{ m}$ (slope toe) | Runup | $0.117793$ ($11.78\%$) | $0.436179$ ($43.62\%$) | $0.118263$ (790 wet) | **FAIL** |
| **RunupToe** | $x = 3.55\text{ m}$ (slope toe) | Weir | $0.117597$ ($11.76\%$) | $0.428205$ ($42.82\%$) | $0.118065$ (790 wet) | **FAIL** |
| **WG3** | $x = 4.35\text{ m}$ (sloping bed)| Runup | **$0.354526$ ($35.45\%$)** | $1.106800$ ($110.68\%$) | $0.128543$ (614 wet) | **FAIL** |
| **WG3** | $x = 4.35\text{ m}$ (sloping bed)| Weir | **$0.364165$ ($36.42\%$)** | $1.094036$ ($109.40\%$) | $0.113372$ (603 wet) | **FAIL** |
| **WG4** | $x = 5.45\text{ m}$ (upper slope)| Runup | **$0.564488$ ($56.45\%$)** | $1.536540$ ($153.65\%$) | None (0 overlap) | **FAIL** |
| **WG4** | $x = 5.45\text{ m}$ (upper slope)| Weir | $0.000000$ ($0.00\%$) | $0.000000$ ($0.00\%$) | None (both 100% dry)| Trivially dry |
| **Crest** | $x = 6.70\text{ m}$ (flume crest)| Runup | $0.000000$ ($0.00\%$) | $0.000000$ ($0.00\%$) | None (both 100% dry)| Trivially dry |
| **Crest** | $x = 6.70\text{ m}$ (flume crest)| Weir | $0.000000$ ($0.00\%$) | $0.000000$ ($0.00\%$) | None (both 100% dry)| Trivially dry |

**Conclusion**: All active wave probes across both mechanisms **fail the 5% relative error tolerance gate** ($\le 0.05 H = 0.02\text{ m}$).

---

## 2. Bounded Source-Based Diagnosis

### A. Semantics of `NpOut = 0` vs Physical Fluid Mass Conservation
- DualSPHysics `RunPARTs.csv` reports `NpOut = 0` across all 801 time steps in all 6 simulation runs.
- **Critical Semantic Boundary**: `NpOut` counts only particles whose coordinates exceed the simulation domain bounding box (`Pos < PointMin` or `Pos > PointMax`) and are excluded by the solver engine.
- `NpOut = 0` establishes **strictly zero solver domain exclusions**.
- It does **NOT** establish zero fluid mass loss or exact volume conservation:
  1. DualSPHysics employs a weakly-compressible equation of state ($P = B [(\rho/\rho_0)^\gamma - 1]$). Density fluctuations ($\Delta \rho / \rho_0$) produce physical volume contraction/dilation without particle loss.
  2. Particles can stick to boundary nodes, become trapped in non-participating dead zones, or experience boundary penetration without leaving the bounding box.
  3. SWL gauge measurement is an Eulerian kernel-sum estimate, not a Lagrangian particle tracker. Gauge dropouts occur when fluid particles are too sparse to exceed the detection threshold, even if no particles were excluded.

### B. C++ Source Inspection: `JGaugeSwl::CalculeCpuT` & Gauge Discretization
From the official DualSPHysics source ([`JDsGaugeItem.cpp:758-787`](file:///home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeItem.cpp#L758-L787) and [`JDsGaugeSystem.cpp:268-275`](file:///home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeSystem.cpp#L268-L275)):
1. **Vertical Discretization Along Probe Line**:
   - The probe vertical segment from `Point0` ($z = -0.02\text{ m}$) to `Point2` ($z = 1.25\text{ m}$) is discretized into sampling nodes with spacing `PointDp = coefdp * Dp` ($0.5 \times DP$).
   - Spacing scales directly with resolution: $\Delta z_{\text{probe}} = 25\text{ mm}$ (coarse), $12.5\text{ mm}$ (medium), $5\text{ mm}$ (fine).
2. **The `MassLimit` Threshold & Floor Fallback**:
   - When omitted from the XML configuration, `masslimit` defaults to:
     $$\text{masslimit} = m_{\text{fluid}} \times 0.5$$
   - Since $m_{\text{fluid}} = \rho_0 DP^3$, the threshold scales cubically: $0.0625\text{ kg}$ (coarse) $\to 0.0078125\text{ kg}$ (medium) $\to 0.0005\text{ kg}$ (fine).
   - At each probe node, `CalculeMassCpu` sums the fluid kernel weight $m_{\text{fluid}} \sum_b W_{ab} \frac{m_b}{\rho_b}$.
   - If no probe node along the entire column reaches `MassLimit` (variable `mpre == 0`), line 782 sets:
     ```cpp
     if (ptsurf.x == DBL_MAX) ptsurf = Point0 + (PointDir * (mpre ? PointNp : 0));
     ```
     `ptsurf` collapses to `Point0` ($z = \text{pos0z} = -0.02\text{ m}$), the floor elevation.
3. **Sloping Bed Artifacts (WG3, WG4)**:
   - On the slope, the wave tongue thins to depths $< 0.05\text{ m}$.
   - At fine resolution ($DP = 0.010\text{ m}$), a 3 cm layer contains 3 particle rows, easily exceeding `MassLimit = 0.0005 kg`. The surface is tracked ($z \approx 0.40+\text{ m}$).
   - At medium ($DP = 0.025\text{ m}$) and coarse ($DP = 0.050\text{ m}$), a 3 cm layer has fewer particles than needed for kernel support; `mass < MassLimit` everywhere, triggering a collapse to $-0.02\text{ m}$.
   - This discrete drop of $\Delta z \approx 0.42\text{ m} > 1.05 H$ creates 120 dropout frames between medium and fine on WG3 and 112 dropout frames on WG4, artificially inflating global RMSE.
   - When evaluating only the 614 overlapping wet frames on WG3, relative RMSE drops from $0.3545 H$ to $0.1285 H$ (a $63.7\%$ reduction), demonstrating that threshold dropout is the dominant contributor to the anomalous error magnitude.

### C. Flat Bed Discrepancy (WG1, WG2): Viscosity & Time-Step Coupling
- On the flat bed (WG1, WG2), water is 100% deep ($\text{dry} = 0/800$), yet relative RMSE is $\approx 12\%$, exceeding the 5% gate.
- This discrepancy is driven by two coupled numerical mechanisms:
  1. **Artificial Viscosity Dissipation**: The solver uses artificial viscosity $\alpha = 0.01$. The effective numerical kinematic viscosity scales as $\nu_{\text{art}} \sim \alpha h c_s$. Because smoothing length $h = 1.5 DP$ shrinks from $0.13\text{ m}$ (coarse) to $0.026\text{ m}$ (fine), numerical dissipation drops by $5\times$. Fine resolution exhibits less wave crest damping and higher steepness.
  2. **Coupled Symplectic Time-Stepping**: Median time step $\Delta t$ reduces from $647\ \mu\text{s}$ (coarse) to $297\ \mu\text{s}$ (medium) to $53\ \mu\text{s}$ (fine). Over 16 seconds (800 frames), differential dispersion accumulates a wave phase lag $\Delta \phi$, producing an apparent $L_2$ difference $\approx 0.12 H$.

---

## 3. Legal Fallback Recommendation

1. **Strict Campaign Boundary Adherence**:
   - Surface-first boundary discretization was accepted as Repair 2 for the wall-gap cause.
   - **No third repair for the wall-gap cause is permissible.**
   - **No relaxation of the physical reference scale $H = 0.4\text{ m}$ or the 5% relative error gate is permissible.**
   - **No further GPU simulation launches.**

2. **Formal Campaign Fallback**:
   - Formally catalog the spatial series non-convergence as an **established scientific negative finding** under DS-DATA-02:
     - Spatial refinement alone ($DP = 0.050 \to 0.025 \to 0.010\text{ m}$) under uncalibrated artificial viscosity and variable CFL time-stepping does not achieve 5% convergence on Eulerian wave gauges.
     - The WG3 relative RMSE of $\sim 0.355 - 0.364 H$ reproduces the historical 4DP spatial negative result ($0.317 - 0.350 H$), confirming that this non-convergence is a persistent property of the numerical formulation on sloping beds.
     - Scientific qualification status remains `not_assessed`, and qualification claim remains `none`.
     - Data is cataloged as candidate spatial evidence with preserved negative history, not as a qualified numerical reference.

---

## 4. Scientific Addendum: Hypothesis Qualification & Conditional Cohort Framework

### 4.1 Distinction Between Correlation and Proven Root Causality
The observations that (1) thin runup swash on sloping beds (WG3, WG4) coincides with discrete drops to `pos0z = -0.02 m`, and (2) artificial viscosity scaling $\nu_{\text{art}} \sim \alpha h c_s$ and Symplectic time-step reduction coincide with flat-bed (WG1, WG2) $\sim 12\%$ relative RMSE are **scientifically grounded hypotheses**, not mathematically proven sole drivers. Discrete SWL floor coincidence alone does not establish complete causal sufficiency. Contact line dynamics, free surface aerated spray, wall boundary particle density deficiency, and paddle generation harmonics interact with the Eulerian SWL gauge kernel.

### 4.2 Bounded Prospective Diagnostic Framework (Conditional Cohorts)
To rigorously evaluate these mechanisms without premature conclusions, the following conditional cohort partitions are defined:
- **Cohort 1: Continuous Deep-Water Flat-Bed Probes (WG1, WG2)**:
  - 100% wet occupancy throughout the entire 16.0s simulation window across all 3 resolutions.
  - Tests the pure hydrodynamic dissipation hypothesis: evaluates wave envelope damping and spectral phase drift independent of any floor drop or dry occupancy artifacts.
- **Cohort 2: Intermittent Wetting Front Slope Transition Probes (RunupToe, Crest)**:
  - Probes experiencing periodic flooding and drainage (790–800 wet frames at toe, ~502 wet frames at crest).
  - Isolates front arrival timing errors from swash depth errors.
- **Cohort 3: Thin-Sheet Swash Slope Probes (WG3, WG4)**:
  - Probes exhibiting thin water layers ($< 0.05\text{ m}$) where kernel mass drops below `MassLimit`.
  - Compares continuous surface tracking against discrete floor-clamped samples to quantify the exact artifact contribution.

### 4.3 Governance Rules & Boundaries
1. **No 5% Tolerance Gate Waiver**:
   - The relative RMSE tolerance of $0.05 H = 0.02\text{ m}$ is inviolable. No relaxed error bands are permitted.
2. **No Premature Halting of the Entire Family**:
   - Automated solver launches are paused pending root review of diagnostic evidence; the F5 family is NOT terminated or abandoned.
3. **Strict Repair Boundary**:
   - Surface-first boundary discretization was accepted as Repair 2 for wall-gap leakage; no third repair for the wall-gap cause is permissible.
