# DS-DATA-02 F6 Angular Release All 3DP Full 12s Rigid Response Comparison Protocol

## 1. Executive Summary & Context

With root completion of native GPU simulation `021`, PartVTK / FloatingInfo exports `022`/`024`, and actual rigid state audits `023`/`025` across all three resolutions:
- **Coarse ($DP = 0.025\text{ m}$)**: [`FloatingInfo_mk60.csv`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-floatinginfo-022/floating/FloatingInfo_mk60.csv) (241 frames, $t \in [0.0, 12.00012]\text{ s}$)
- **Medium ($DP = 0.020\text{ m}$)**: [`FloatingInfo_mk60.csv`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-floatinginfo-022/floating/FloatingInfo_mk60.csv) (241 frames, $t \in [0.0, 12.00013]\text{ s}$)
- **Fine ($DP = 0.0125\text{ m}$)**: [`FloatingInfo_mk60.csv`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-floatinginfo-024/floating/FloatingInfo_mk60.csv) (241 frames, $t \in [0.0, 12.00004]\text{ s}$)

This protocol establishes the rigorous, source-bound comparison evaluator for the actual full 3D free 6DOF rigid angular-release physical case.

---

## 2. Inviolable Quality Contract & Operator Definitions

### 2.1 Frozen Macro Metric Operator
- **Metric**: Relative RMSE evaluated against the reference peak absolute amplitude over the entire simulation window:
  $$\text{RMSE}_{\text{abs}} = \sqrt{\frac{1}{N} \sum_{i=1}^N \left( y_{\text{cand}}(t_i) - y_{\text{ref}}(t_i) \right)^2}$$
  $$\text{Scale}_{\text{ref}} = \max \left( \max_{i} |y_{\text{ref}}(t_i)|, 10^{-12} \right)$$
  $$\text{RMSE}_{\text{rel}} = \frac{\text{RMSE}_{\text{abs}}}{\text{Scale}_{\text{ref}}}$$
- **Threshold**: Relative RMSE $\le 0.05$ ($5\%$) for each degree of freedom.

### 2.2 Rejection of Narrowing Heuristics & Post-Hoc Waivers
1. **No Heave-Only Gate**:
   - The case is a full 3D free 6DOF rigid body response.
   - All 6 DOFs (surge, sway, heave, roll, pitch, yaw) are mandatory evaluation channels.
   - Heave convergence alone does NOT qualify the physical case.
2. **No Truncated 3s Window**:
   - The full $12.0\text{ s}$ window ($241$ frames at $\Delta t = 0.05\text{ s}$) is evaluated.
   - No early truncation or sliding-window qualification is permitted.
3. **No Post-Hoc Orientation Budgets**:
   - Rotational degrees of freedom are evaluated strictly against the frozen $5\%$ relative RMSE operator (with angles converted to radians).
   - No relaxed $20\%$ or $30\%$ orientation thresholds or ad-hoc angular degree caps are introduced.
4. **No Zero-Spin Inference from Zero Initial Velocity**:
   - In DualSPHysics, XML `<angularvelini x="0.08" y="0.12" z="0.06"/>` is assigned directly to internal rigid body state `fobj->fomega` at $t=0$ (`JSph.cpp:1162`) and saved to `PartFloatInfo` at frame 0.
   - Particle node velocities in GenCase / PartVTK frame 0 remain $0.0\text{ m/s}$ prior to the first time-step kernel update `KerFtPartsUpdate` (`JSphGpu_ker.cu:2045-2065`).
   - Reporting translational node velocity as $0.0\text{ m/s}$ at $t=0$ does NOT imply zero internal angular spin.
5. **No Inherited Old Zero-Spin Qualification**:
   - The angular-release candidate is an independent physical control scope with finite initial angular momentum.
   - It inherits zero qualification or acceptance from previous zero-spin runs (`F6_BODY_CELLCENTER_TRANSFORM_001`).

---

## 3. Strict Mass & Support Semantics Separation

Three distinct mass values operate simultaneously and must not be conflated or normalized:
1. **Declared Physical Rigid Body Mass**:
   - $M_{\text{body}} = 128.0\text{ kg}$ with principal moments of inertia $I = [8.53333, 8.53333, 13.6533]\text{ kg}\cdot\text{m}^2$.
   - Dictates Newton-Euler rigid body dynamics in the solver.
2. **Fluid-Density Support Particle Weight**:
   - $\sum m_p \approx 256.0\text{ kg}$ in PartVTK CSV `Mass` column.
   - Derived from continuous fluid reference density $\rho_0 = 1000\text{ kg/m}^3 \times V_{\text{body}} = 0.256\text{ m}^3$.
   - Preserved byte-for-byte as official PartVTK output without artificial rescaling.
3. **Solver Hydrodynamic Interaction Weight (`masspart`)**:
   - Coarse ($DP = 0.025\text{ m}$): $0.015625\text{ kg}$
   - Medium ($DP = 0.020\text{ m}$): $0.008000\text{ kg}$
   - Fine ($DP = 0.0125\text{ m}$): $0.00195313\text{ kg}$
   - Used by the SPH solver kernels for fluid-boundary particle interactions (`fobj.massp`).

---

## 4. Evaluator & Registered Request

- **Evaluator Script**: [`ds_data02_f6_angular_release_comparison_v2.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f6_angular_release_comparison_v2.py)
- **Unit Test**: [`test_ds_data02_f6_angular_release_comparison_v2.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/tests/test_ds_data02_f6_angular_release_comparison_v2.py) (all 4 synthetic tests passed)
- **Configuration**: [`config.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_angular_release_3dp_comparison_004/config.json)
- **Strict Runner Request**: [`F6_ANGULAR_RELEASE_ALL3DP_COMPARISON_REQUEST.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_angular_release_3dp_comparison_004/requests/F6_ANGULAR_RELEASE_ALL3DP_COMPARISON_REQUEST.json)
  - Attempt: `root-angular-release-all3dp-comparison-026`
  - Validated by: `ds_data02_strict_dispatch_v1.py` (12 input files verified)
  - CPU only: $\le 2$ threads, $\le 1800\text{ s}$, `launch_allowed: false`, `root_review_required: true`.
- **Manifest**: [`manifest.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_angular_release_3dp_comparison_004/manifest.json) (SHA256: `9e6498234a1e794567b2b37bda756c01cca0e545b40b4892a47c902391d2e6cc`)
