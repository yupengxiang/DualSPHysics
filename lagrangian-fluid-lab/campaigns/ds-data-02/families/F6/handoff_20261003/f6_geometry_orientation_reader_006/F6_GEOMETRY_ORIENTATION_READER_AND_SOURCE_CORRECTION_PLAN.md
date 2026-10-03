# DS-DATA-02 F6 Geometry-Based Orientation Reader & Source Correction Plan

## 1. Executive Summary & Purpose

This plan establishes the authoritative mathematical, algorithmic, and governance specification for the **fresh F6 geometry-based orientation reader** (`ds_data02_f6_geometry_orientation_reader_v1.py`), directly resolving Root Source Review 031 (`root_owner_F5_F6_source_review_031/review.json`) and incorporating authoritative errata for both F5 and F6.

### Inviolable Preconditions & Campaign Boundaries
1. **Preservation of Prior Unadopted Work**:
   - `F5diagnostic037` (`f5_spatial_disagreement_source_diagnostic_037`) and `F6SO3diagnostic005` (`f6_so3_and_physical_scale_diagnostic_005`) remain **unadopted and preserved** in their original paths.
2. **Root Execution Ownership**:
   - Root strictly owns all scientific actual H5/CSV/actual pytest/solver/converter execution via the shared strict dispatcher.
   - The infra agent executes only synthetic mock fixtures in temporary directories; zero actual scientific arrays are read, and zero actual solver runs are launched.
3. **Orientation Budget Status**:
   - The orientation budget is explicitly **NULL / unregistered** until an actual contract source is found.
   - No retrospectively invented gate (e.g. 1 rad 5%) is promoted; no case qualification is claimed.
   - Root Q-N qualified products remain **0/336**.

---

## 2. Primary Source Citations & Architecture Review

Authoritative source inspection of the DualSPHysics codebase establishes the following foundational facts:

1. **DualSPHysics Rotation Matrix Sequence (`FunctionsMath.h:345-353`)**:
   ```cpp
   inline tmatrix3f RotMatrix3x3(const tfloat3& ang){
     const float cosx=cos(ang.x),cosy=cos(ang.y),cosz=cos(ang.z);
     const float sinx=sin(ang.x),siny=sin(ang.y),sinz=sin(ang.z);
     return(TMatrix3f(
        cosy*cosz,                   -cosy*sinz,                    siny,
        sinx*siny*cosz + cosx*sinz,  -sinx*siny*sinz + cosx*cosz,  -sinx*cosy,
       -cosx*siny*cosz + sinx*sinz,   cosx*siny*sinz + sinx*cosz,   cosx*cosy
     ));
   }
   ```
   This implements an **XYZ rotation matrix** ($R = R_x(\text{ang.x}) R_y(\text{ang.y}) R_z(\text{ang.z})$), directly refuting the previous assumption of an aerospace ZYX sequence ($R_z R_y R_x$).

2. **Native Floating Body Persistence (`JDsPartFloatSave.cpp:166`)**:
   ```cpp
   FtData->SetPartData0(cf, v.center, v.fvel, v.fomega, ...);
   ```
   The native solver persists continuous center of mass `center`, linear velocity `fvel`, and angular velocity `fomega` into `PartFloatInfo.ibi4`, but **does NOT persist Euler angles**.

3. **Official Post-Processing Semantics (`doc/help/FloatingInfo_Help.out:66-85`)**:
   - Lists: `roll [deg]`: rotation on X-axis, `pitch [deg]`: rotation on Y-axis, `yaw [deg]`: rotation on Z-axis.
   - Specifically notes: `*** Note that the sign of pitch has changed since v5.0.204`.
   - The documentation does not define or prove any composite 3-angle Euler sequence chart.

4. **Registered Physical Scales (`observation_plan.json`)**:
   - Registers characteristic length $L_{\text{char}} = 0.8\text{ m}$ (box length/width), $U_{\text{gravity}} = \sqrt{g L} = 2.8014\text{ m/s}$, and generic 5% macro tolerance.
   - The previously claimed orientation unit $\Theta = 1.0\text{ rad}$ and angular velocity scale $\Omega = \sqrt{g/L} = 3.5018\text{ rad/s}$ are **unregistered**.

---

## 3. Mathematical & Algorithmic Formulation

To eliminate chart singularities, sequence ambiguity, and post-processing conventions, orientation must be reconstructed directly from the 3D geometry of the floating body nodes.

### 3.1 Floating Node Input Specification
- Root prepares official full 241 floating-node PartVTK exports (Attempt `root-full-window-floating-node-export-028`):
  `PartVTK -savecsv PartFloating -first:0 -last:240 -onlytype:-all,+floating -vars:-all,+idp,+zone,+type,+mk -csvsep:1`
- File header structure:
  - Line 1: `TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid`
  - Line 2: `<native_time_s>,<Np>,...`
  - Line 3: `<blank>`
  - Line 4: `Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Type,Mk,`
- Filtering:
  - `Type == 2` (floating)
  - `Mk == 60` (rigid floating box)
  - Finite coordinate verification ($\text{isfinite}(x, y, z)$)
  - Node ordering strictly sorted by unique `Idp` to ensure canonical node correspondence across all frames.

### 3.2 Kabsch / SVD Proper SO(3) Pose Formulation
Given reference frame 0 nodes $P = \{ p_i \}_{i=1}^N$ and target frame $t$ nodes $Q = \{ q_i \}_{i=1}^N$:
1. **Centroids**:
   $$p_c = \frac{1}{N}\sum_{i=1}^N p_i, \quad q_c = \frac{1}{N}\sum_{i=1}^N q_i$$
   *(Uniform geometric weights $w_i = 1/N$, avoiding mass rescale and support weight conflation).*
2. **Centered Coordinates**:
   $$X_i = p_i - p_c, \quad Y_i = q_i - q_c$$
3. **Reference Covariance Rank Check**:
   $$C_{\text{ref}} = \frac{1}{N} X^T X \quad \implies \quad \sigma_3(C_{\text{ref}}) > 10^{-6} \quad (\text{Rank } 3)$$
4. **Cross-Covariance Matrix**:
   $$H = X^T Y \in \mathbb{R}^{3 \times 3}$$
5. **Singular Value Decomposition**:
   $$H = U \Sigma V^T$$
6. **Proper $SO(3)$ Rotation Enforcement**:
   $$d = \det(V U^T), \quad D = \operatorname{diag}(1, 1, d), \quad R(t) = V D U^T$$
   This guarantees $\det(R(t)) = +1.0$ (proper rotation in $SO(3)$, correcting any improper reflection).
7. **Rigidity Fit Residual**:
   $$\text{RMS}_{\text{rigid}}(t) = \sqrt{\frac{1}{N} \sum_{i=1}^N \| q_i - (R(t) X_i + q_c) \|^2}$$
   Quantifies structural rigidity and verifies the non-deformation assumption.

### 3.3 Continuous Physical Time SLERP Cross-DP Comparison
Cross-DP comparison (e.g. coarse vs medium vs fine) must be evaluated in continuous physical time:
1. **Strictly Prohibited**:
   - Index-based frame pairing (invalid when sampling rates or time points differ).
   - Linear Euler angle interpolation (suffers from gimbal lock, chart distortion, and non-geodesic paths).
2. **Valid Lie Group SLERP Interpolation**:
   - Convert $R(t)$ to unit quaternion $q(t) = [w, x, y, z]$ with $w \ge 0$.
   - For query physical time $t \in [t_k, t_{k+1}]$ with $\alpha = (t - t_k) / (t_{k+1} - t_k)$:
     $$q(t) = \operatorname{SLERP}(q_k, q_{k+1}; \alpha) = \frac{\sin((1-\alpha)\theta)}{\sin\theta} q_k + \frac{\sin(\alpha\theta)}{\sin\theta} q_{k+1}$$
     $$c(t) = (1-\alpha) c_k + \alpha c_{k+1}$$
3. **Riemannian Geodesic Distance on $SO(3)$**:
   $$\Phi(t) = \arccos\left(\operatorname{clip}\left(\frac{\operatorname{tr}(R_{\text{ref}}^T(t) R_{\text{cand}}(t)) - 1}{2}, -1.0, 1.0\right)\right) \in [0, \pi]\text{ rad}$$
4. **Aggregate Trajectory Metrics**:
   - Geodesic RMSE (rad, deg)
   - Geodesic Maximum (rad, deg)
   - Translation Center RMSE (m) and Center RMSE / $L_{\text{char}}$

### 3.4 Native FloatingInfo Centroid Validation
Validates node geometry centroid $q_c(t)$ against official `FloatingInfo_mk60.csv` center position at identical native timestamps, computing translation RMSE and maximum difference.

---

## 4. Authoritative Errata Summary

### F5 Errata (`f5_root_source_review_031_errata.json`)
1. **3D Smoothing Length**: In 3D DualSPHysics, $H = \text{Coefh} \cdot \sqrt{3} \cdot dp$. For $\text{Coefh} = 1.5, dp = 0.01\text{ m}$, generated 3D XML gives $H = 0.025980762114\text{ m}$, NOT $0.015\text{ m}$.
2. **WG3 Initial Offset**: Telemetry proves initial offset is identically $0.0\text{ m}$. Initial 20mm shift assumption is false.
3. **Weir Scope**: Configured weir was ignored in diagnostic 037; both RUNUP and WEIR are declared scope.
4. **Below-Bed Geometry**: Scanline points below bed STL are valid scan endpoints (returning Point 0 on dry surface), not invalid probes.
5. **Threshold Causal Attribution**: Hardcoded MassLimit and 2dp wall padding are unproven causal hypotheses. Root actual native diagnostic 038 is running to address this without duplication.
6. **Gauge Time Horizon**: Native gauge rows end at 15.98s, no extrapolation to 16.0s.

### F6 Errata (`f5_f6_source_review_031_errata.json`)
1. **Orientation Scale & Gate**: 1 rad unit and $\sqrt{g/L}$ scale are unregistered; orientation budget is NULL / unregistered.
2. **Unconstrained Simulation Time**: Claim of 99.9166% unconstrained time conflated unweighted half-step incidence ($273 / 327402$) with duration fraction.
3. **Actual Step Counts**: Coarse telemetry is 76399 steps, medium is 96697 steps (not 41200 / 51500).
4. **Rotation Semantics**: `FunctionsMath.h` uses XYZ sequence; `JDsPartFloatSave` does not persist Euler angles; direct geometry Kabsch reconstruction is mandatory.
5. **Cross-DP Frame Pairing**: Continuous physical time SLERP is mandatory over index-based pairing.

---

## 5. Synthetic Fixtures & Verification Results

The implementation is verified using 5 synthetic mock fixtures in `tests/fixtures/synthetic_floating_fixtures.py` and `tests/test_ds_data02_f6_geometry_orientation_reader_v1.py`:
- `test_rigid_pure_rotation`: Recovers known 3D rotation and translation to single-precision float accuracy ($< 10^{-6}$), with rigidity RMS $< 10^{-6}\text{ m}$.
- `test_reflection_detection_and_proper_so3`: Detects reflection in $V U^T$ and enforces proper $\det(R) = +1.0$.
- `test_nonrigid_deformation_residual`: Verifies that structural deformation is strictly flagged by rigidity residuals ($> 0.01\text{ m}$).
- `test_uid_permutation_invariance`: Confirms node sorting by exact UID ensures invariance to row shuffling.
- `test_full_window_pipeline_and_floating_info`: Verifies full 241-frame pipeline, FloatingInfo centroid agreement ($< 10^{-5}\text{ m}$), SLERP trajectory evaluation, and NULL orientation budget reporting.

All 6 unit tests pass completely (`pytest tests/test_ds_data02_f6_geometry_orientation_reader_v1.py`).
