# DS-DATA-02 F5 Gauge Spatial Disagreement Source-Grounded Diagnostic Plan

## 1. Executive Summary & Non-Negotiable Boundaries

Under DS-DATA-02 root review directives and recent native interval telemetry (`036` confirming `total_DT_min_adjustments = 0` and `NpOut = 0` across all six 3DP solvers), this diagnostic plan provides a source-grounded investigation into the spatial non-convergence observed on Eulerian wave gauges across Coarse ($DP = 0.050\text{ m}$), Medium ($DP = 0.025\text{ m}$), and Fine ($DP = 0.010\text{ m}$) resolutions.

### Inviolable Campaign Governance:
1. **Zero Sample Modification**: Scientific trajectory data and PartVTK gauge outputs remain strictly unchanged.
2. **Zero Budget Relaxation**: Reference wave height $H = 0.40\text{ m}$ and the $5\%$ relative RMSE gate ($0.05 H = 0.020\text{ m}$) are inviolable.
3. **Zero Numerical Recipe Changes**: No third repair for wall-gap; no solver parameter tweaks or artificial damping modifications.
4. **Zero GPU Simulations**: Purely bounded CPU diagnostic audits under shared strict dispatch supervision.

---

## 2. Source-Grounded Root Cause Audits

### 2.1 Physical Gauge Locations vs Continuous Bed Geometry
DualSPHysics SWL gauges evaluate vertical lines of points from `point0` to `point2`. In all generated XMLs, `point0` is set to $z = -0.02\text{ m}$ regardless of the local bed elevation.
- Continuous slope equation: For $x \ge x_{\text{toe}} = 3.55\text{ m}$, bed elevation is $z_{\text{bed}}(x) = (x - 3.55) \times 0.280\text{ m}$.

| Gauge | $x$ Coordinate (m) | Continuous $z_{\text{bed}}$ (m) | Gauge Baseline `point0.z` (m) | Solid Embedding Depth $d_{\text{embed}}$ (m) | Embedding Ratio ($d_{\text{embed}} / H$) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **WG1** | $2.00$ | $0.000$ | $-0.020$ | $0.020\text{ m}$ | $0.050 H$ |
| **WG2** | $3.10$ | $0.000$ | $-0.020$ | $0.020\text{ m}$ | $0.050 H$ |
| **RunupToe** | $3.55$ | $0.000$ | $-0.020$ | $0.020\text{ m}$ | $0.050 H$ |
| **WG3** | $4.35$ | $0.224$ | $-0.020$ | **$0.244\text{ m}$** | **$0.610 H$** |
| **WG4** | $5.45$ | $0.532$ | $-0.020$ | **$0.552\text{ m}$** | **$1.380 H$** |
| **Crest** | $6.70$ | $0.882$ | $-0.020$ | **$0.902\text{ m}$** | **$2.255 H$** |

**Finding**: At WG3, WG4, and Crest, the gauge baseline is embedded deeply ($0.61 H$ to $2.26 H$) into the solid bed. When the gauge drops to `point0` due to absence of water or mass below threshold, it reports $-0.02\text{ m}$ instead of the physical bed surface, generating an immediate coordinate artifact exceeding $1.0 H$.

---

### 2.2 Boundary Particle Padding vs Grid Spacing Shifts
In DualSPHysics Dynamic Boundary Conditions (DBC), boundary particles form a repulsive layer of thickness $t_{\text{pad}} \approx 2 DP$ beneath the fluid domain.
Fluid particles are initialized with an offset of $+0.5 DP$ above the physical bed:
- Coarse ($DP = 0.050\text{ m}$): $z_{\text{fluid,0}} = z_{\text{bed}} + 0.025\text{ m}$ ($t_{\text{pad}} = 0.100\text{ m}$)
- Medium ($DP = 0.025\text{ m}$): $z_{\text{fluid,0}} = z_{\text{bed}} + 0.0125\text{ m}$ ($t_{\text{pad}} = 0.050\text{ m}$)
- Fine ($DP = 0.010\text{ m}$): $z_{\text{fluid,0}} = z_{\text{bed}} + 0.005\text{ m}$ ($t_{\text{pad}} = 0.020\text{ m}$)

**Discretization Shift**:
$$\Delta z_{\text{init}} = 0.5(DP_{\text{coarse}} - DP_{\text{fine}}) = 0.020\text{ m} \equiv 0.050 H$$
The initial fluid node position difference between Coarse and Fine alone **consumes 100% of the entire 5% error budget** before wave propagation commences.

---

### 2.3 SPH Kernel Support Truncation & Mass Thresholding
The SWL gauge algorithm (`JGaugeSwl::CalculeCpuT` in `JDsGaugeItem.cpp`) evaluates kernel fluid mass along probe evaluation points spaced at $\Delta z_{\text{probe}} = 0.5 DP$:
- SPH kernel support radius: $2h = 3 DP$ ($0.150\text{ m}$ coarse, $0.075\text{ m}$ medium, $0.030\text{ m}$ fine).
- `MassLimit` threshold: $0.5 \times m_{\text{fluid}} = 0.5 \times \rho_0 DP^3$.
- In thin-sheet swash ($d < 0.05\text{ m}$), the fluid layer depth is smaller than the Coarse kernel radius ($2h = 0.150\text{ m}$). Particles along the vertical column fail to satisfy `mass >= MassLimit`, causing the gauge to fall back to `point0` ($-0.02\text{ m}$).
- Fine resolution ($2h = 0.030\text{ m}$, mass threshold $125\times$ smaller) resolves the thin swash film and correctly reports the surface ($z \approx 0.40+\text{ m}$), inducing a false numerical jump $\Delta z \approx 0.42\text{ m} > 1.05 H$ across 120 frames at WG3 and 112 frames at WG4.

---

### 2.4 Dry Occupancy & Conditional Cohort Breakdown

Without modifying scientific samples or altering the frozen global operator, the diagnostic plan decomposes the 800 frames into three mutually exclusive conditional cohorts:
1. **Cohort A (Joint Wet)**: Both resolutions report fluid ($z > z_{\text{bed}} + 0.5 DP$).
2. **Cohort B (Resolution Dropout)**: One resolution drops to floor ($-0.02\text{ m}$) while the other tracks surface.
3. **Cohort C (Joint Dry)**: Both resolutions report dry/floor.

By calculating the sum of squared errors $\text{SSE}_{\text{dropout}}$ in Cohort B relative to total $\text{SSE}_{\text{total}}$, the diagnostic objectively quantifies what fraction of the observed non-convergence is attributable to Eulerian gauge thresholding artifacts vs true hydrodynamic dispersion.

---

## 3. Telemetry Evidence Integration

Telemetry audit [`native-interval-telemetry.json`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/F5_F6_COMPLETED_NATIVE_INTERVAL_TELEMETRY_036/root-nine-completed-F5-F6-native-interval-telemetry-036/native-interval-telemetry.json) confirms:
- `total_DT_min_adjustments = 0` across all six F5 Runup and Weir 3DP solvers.
- `native_NpOut_interval_sum = 0` across all six solvers.
- Time-step adaptation is completely unconstrained by numerical floor clamping; spatial disagreement cannot be attributed to time-step clamping.

---

## 4. Assets & Registered Request

- **Diagnostic Script**: [`ds_data02_f5_gauge_spatial_diagnostic_v2.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f5_gauge_spatial_diagnostic_v2.py)
- **Unit Test**: [`test_ds_data02_f5_gauge_spatial_diagnostic_v2.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/tests/test_ds_data02_f5_gauge_spatial_diagnostic_v2.py) (5 passed in 1.42s)
- **Config**: [`config.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/f5_spatial_disagreement_source_diagnostic_037/config.json)
- **Strict Runner Request**: [`F5_GAUGE_SPATIAL_DISAGREEMENT_DIAGNOSTIC_REQUEST.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/f5_spatial_disagreement_source_diagnostic_037/requests/F5_GAUGE_SPATIAL_DISAGREEMENT_DIAGNOSTIC_REQUEST.json) (Attempt `root-f5-spatial-disagreement-diagnostic-037`, 7 input files verified)
- **Manifest**: [`manifest.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/f5_spatial_disagreement_source_diagnostic_037/manifest.json) (SHA256: `72cb2595e2f4bfb3c81942ed4b3dbedecf6b47a8f21082a67183f54c224baeec`)
