# DS-DATA-02 F6 SO(3) Lie Group & Registered Physical Scales Diagnostic Plan

## 1. Executive Summary & Purpose

This diagnostic plan establishes the rigorous mathematical and physical evaluation framework for the F6 angular-release 3DP response across coarse ($DP = 0.025\text{ m}$), medium ($DP = 0.020\text{ m}$), and fine ($DP = 0.0125\text{ m}$) resolutions.

Directly resolving root continuation instructions:
1. **Invariant $SO(3)$ Lie Group Metric vs Local Chart Euler Angles**:
   - Strictly rejects inferring Euler angle RMSE as $SO(3)$ error.
   - Formulates the exact Riemannian geodesic distance $\Phi(t) = \arccos\left(\text{clip}\left(\frac{\text{tr}(R_1^T R_2) - 1}{2}, -1.0, 1.0\right)\right)$ on the Lie group manifold $SO(3)$.
2. **Registered Physical Reference Scales vs Root Descriptive Dynamic-Peak 5%**:
   - Reconstructs the actual registered quality contract using frozen physical scales:
     $$L_{\text{char}} = 0.8\text{ m}, \quad U_{\text{gravity}} = \sqrt{g L} = 2.8014\text{ m/s}, \quad \omega_{\text{gravity}} = \sqrt{g/L} = 3.5018\text{ rad/s}, \quad \Theta_{\text{char}} = 1.0\text{ rad}$$
   - Strictly prohibits substituting Root's new descriptive dynamic-peak 5% ($\text{RMSE} / \max_t |y(t)|$) as the registered gate.
   - Exposes why the dynamic-peak denominator blows up on low-amplitude off-axis channels (sway, roll, yaw), generating artificial false failures on sub-millimeter / sub-degree differences.
3. **Mass & Support Semantics Separation**:
   - Preserves inviolable distinction between declared physical mass ($128.0\text{ kg}$), fluid-density lattice support weight ($\approx 256.0\text{ kg}$), and solver interaction weight (`masspart`).
4. **Adaptive Sub-stepping Telemetry Integration**:
   - Binds completed telemetry (`native-interval-telemetry.json`): coarse ($0$), medium ($0$), fine ($273$ adjustments out of $327,414$ Symplectic half-steps, $0.08338\%$ incidence).
   - Establishes that localized adaptive sub-stepping is descriptive evidence, not causal proof of non-convergence.

---

## 2. Mathematical Formulation: Invariant $SO(3)$ vs Euler Chart Error

### 2.1 Failure of Euler Angle Euclidean Norm
Euler angles $(\phi, \theta, \psi)$ (roll, pitch, yaw) represent a coordinate chart parameterizing the non-Euclidean Lie group $SO(3)$.
Component-wise Euler RMSE:
$$\text{RMSE}_{\text{Euler}}(\phi) = \sqrt{\frac{1}{N}\sum_{i=1}^N (\phi_{\text{cand}}(t_i) - \phi_{\text{ref}}(t_i))^2}$$
Treating $(\Delta\phi, \Delta\theta, \Delta\psi)$ as a vector in Euclidean space $\mathbb{R}^3$ introduces fundamental errors:
1. **Coordinate Singularities & Gimbal Lock**: Parameterization depends on rotation sequence (DualSPHysics uses ZYX: $R = R_z(\psi) R_y(\theta) R_x(\phi)$).
2. **Chart Distortion & Anisotropy**: The Euclidean distance $\|\Delta\mathbf{\theta}\|_2 = \sqrt{\Delta\phi^2 + \Delta\theta^2 + \Delta\psi^2}$ is non-isometric to the Riemannian metric of $SO(3)$. For non-infinitesimal rotations, $\|\Delta\mathbf{\theta}\|_2 \ne \Phi_{SO(3)}$.
3. **Kinematic Coupling**: Off-axis angular velocity ($\omega_x, \omega_y, \omega_z$) couples into all three Euler angle derivatives non-linearly.

### 2.2 Invariant Riemannian Geodesic Distance on $SO(3)$
For any rotation matrices $R_{\text{ref}}(t), R_{\text{cand}}(t) \in SO(3)$, the relative rotation is:
$$R_{\text{rel}}(t) = R_{\text{ref}}^T(t) R_{\text{cand}}(t)$$
The trace of $R_{\text{rel}}(t)$ is related to the rotation angle $\Phi(t)$ about the instantaneous Euler eigen-axis by:
$$\text{tr}(R_{\text{rel}}(t)) = 1 + 2 \cos(\Phi(t))$$
The intrinsic, coordinate-invariant Riemannian geodesic distance on $SO(3)$ is:
$$\Phi(t) = \|\log(R_{\text{ref}}^T(t) R_{\text{cand}}(t))\| = \arccos\left( \text{clip}\left( \frac{\text{tr}(R_{\text{ref}}^T(t) R_{\text{cand}}(t)) - 1}{2}, -1.0, 1.0 \right) \right) \in [0, \pi]$$
Trajectory-wide orientation metrics:
$$\text{RMSE}_{SO(3)} = \sqrt{\frac{1}{N}\sum_{i=1}^N \Phi(t_i)^2}, \quad \text{Max}_{SO(3)} = \max_{i} \Phi(t_i)$$
This metric is bi-invariant: identical under any coordinate choice or rigid body frame transformation.

---

## 3. Registered Physical Reference Scales vs Root Descriptive Dynamic-Peak

### 3.1 Registered Physical Reference Scales
The registered quality contract evaluates convergence against the physical scales of the rigid body and gravity:
| Observable Category | Variable | Reference Scale | Mathematical Formula | Physical Value | 5% Macro Budget |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Translation** | Surge, Sway, Heave, Center | $L_{\text{char}}$ | Box length / width | $0.8000\text{ m}$ | $\le 0.0400\text{ m}$ ($40\text{ mm}$) |
| **Orientation** | $SO(3)$ Geodesic Distance | $\Theta_{\text{char}}$ | Unit radian scale | $1.0000\text{ rad}$ | $\le 0.0500\text{ rad}$ ($2.865^\circ$) |
| **Linear Velocity** | $u, v, w$ | $U_{\text{gravity}}$ | $\sqrt{g L_{\text{char}}}$ | $2.8014\text{ m/s}$ | $\le 0.1401\text{ m/s}$ |
| **Angular Velocity** | $\omega_x, \omega_y, \omega_z$ | $\omega_{\text{gravity}}$ | $\sqrt{g / L_{\text{char}}}$ | $3.5018\text{ rad/s}$ | $\le 0.1751\text{ rad/s}$ |
| **Characteristic Time** | $t$ | $T_{\text{gravity}}$ | $\sqrt{L_{\text{char}} / g}$ | $0.2856\text{ s}$ | $N/A$ |

### 3.2 The Dynamic-Peak Denominator Distortion
Root's descriptive metric computes:
$$\text{RMSE}_{\text{rel, Root}} = \frac{\text{RMSE}_{\text{abs}}}{\max_{t} |y_{\text{ref}}(t)|}$$
**Why this must NOT be used as the registered acceptance gate**:
- In the F6 angular release, the dominant motion is pitch ($\theta$) and heave ($z$).
- The off-axis channels (sway $y$, roll $\phi$, yaw $\psi$) have very low physical excitation ($\max_t |y(t)| \sim 10^{-3}\text{ m}$ or $10^{-3}\text{ rad}$).
- If an off-axis channel has a peak of $0.0010\text{ m}$ ($1\text{ mm}$) and an absolute discrepancy of $0.0002\text{ m}$ ($0.2\text{ mm}$):
  $$\text{Relative to physical scale } L: \quad \frac{0.0002\text{ m}}{0.8000\text{ m}} = 0.025\% \ll 5\% \quad \implies \text{\textbf{PASS}}$$
  $$\text{Relative to dynamic peak: } \quad \frac{0.0002\text{ m}}{0.0010\text{ m}} = 20.0\% > 5\% \quad \implies \text{\textbf{ARTIFICIAL FAIL}}$$
- The dynamic-peak formula suffers from a **denominator singularity / inflation** for near-quiescent signals.
- In our diagnostic evaluator, Root dynamic-peak metrics are preserved and reported as *descriptive diagnostics*, with explicit warning tags (`denominator_inflation_risk: true`, `status: descriptive_only_not_registered_gate`).

---

## 4. Inviolable Mass & Support Semantics

The three mass values operating simultaneously in F6:
1. **Declared Physical Rigid Body Mass**:
   - $M_{\text{body}} = 128.0\text{ kg}$
   - Principal moments of inertia: $I_{xx} = 8.53333\text{ kg}\cdot\text{m}^2, I_{yy} = 8.53333\text{ kg}\cdot\text{m}^2, I_{zz} = 13.65333\text{ kg}\cdot\text{m}^2$.
   - Directly governs Newton-Euler equations of motion in DualSPHysics (`JSph.cpp:2605-2645`).
2. **Fluid-Density Lattice Support Weight**:
   - $\sum m_p \approx 256.0\text{ kg}$ in PartVTK exports.
   - Derived from continuous fluid reference density $\rho_0 = 1000\text{ kg/m}^3 \times V_{\text{body}} = 0.256\text{ m}^3$.
   - Preserved byte-for-byte; never scaled or conflated with physical mass.
3. **Solver Hydrodynamic Interaction Weight (`masspart`)**:
   - Coarse ($DP = 0.025\text{ m}$): $0.015625\text{ kg}$
   - Medium ($DP = 0.020\text{ m}$): $0.008000\text{ kg}$
   - Fine ($DP = 0.0125\text{ m}$): $0.00195313\text{ kg}$
   - Controls SPH boundary-particle hydrodynamic pressure and force summation.

---

## 5. Adaptive Sub-stepping Telemetry Evidence

From completed Root interval audit [`native-interval-telemetry.json`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/F5_F6_COMPLETED_NATIVE_INTERVAL_TELEMETRY_036/root-nine-completed-F5-F6-native-interval-telemetry-036/native-interval-telemetry.json):
- **Coarse ($DP = 0.025\text{ m}$)**:
  - $41,200$ interval steps; $0$ DTsMin adjustments; $0$ NpOut exclusions.
- **Medium ($DP = 0.020\text{ m}$)**:
  - $51,500$ interval steps; $0$ DTsMin adjustments; $0$ NpOut exclusions.
- **Fine ($DP = 0.0125\text{ m}$)**:
  - $163,707$ interval steps ($327,414$ Symplectic half-steps); $273$ DTsMin adjustments across $2$ saved intervals; $28$ NpOut exclusions.
  - Symplectic floor incidence fraction: $273 / 327,414 = 0.0008338$ ($0.08338\%$).
- **Scientific Conclusion**:
  - The $273$ adjustments occur in only 2 localized intervals under sharp free-surface impact where the adaptive CFL condition briefly encounters the minimum timestep floor.
  - Telemetry confirms that time-stepping is unconstrained across $99.9166\%$ of the simulation.
  - Clamping is descriptive evidence and does NOT constitute causal proof of spatial non-convergence or solver corruption.

---

## 6. Implementation Assets & Verification

1. **Diagnostic Evaluator Script**:
   [`ds_data02_f6_so3_physical_scale_diagnostic_v1.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f6_so3_physical_scale_diagnostic_v1.py)
   - Computes invariant $SO(3)$ geodesic distance, Euler chart distortion ratio, physical-scale relative errors, and Root dynamic-peak diagnostics.
2. **Synthetic Unit Test**:
   [`test_ds_data02_f6_so3_physical_scale_diagnostic_v1.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/tests/test_ds_data02_f6_so3_physical_scale_diagnostic_v1.py)
   - $4$ tests passed in $0.50\text{ s}$ using synthetic tmp_path fixtures.
3. **Configuration**:
   [`config.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_so3_and_physical_scale_diagnostic_005/config.json)
4. **Strict Runner Request**:
   [`F6_SO3_AND_PHYSICAL_SCALE_DIAGNOSTIC_REQUEST.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_so3_and_physical_scale_diagnostic_005/requests/F6_SO3_AND_PHYSICAL_SCALE_DIAGNOSTIC_REQUEST.json)
   - Attempt: `root-f6-so3-physical-scale-diagnostic-027`
   - Validated strictly by: `ds_data02_strict_dispatch_v1.py` ($9$ files verified)
   - Bound parameters: CPU only, $\le 2$ threads, $\le 1800\text{ s}$, `launch_allowed: false`, `root_review_required: true`.
5. **Manifest**:
   [`manifest.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_so3_and_physical_scale_diagnostic_005/manifest.json)
