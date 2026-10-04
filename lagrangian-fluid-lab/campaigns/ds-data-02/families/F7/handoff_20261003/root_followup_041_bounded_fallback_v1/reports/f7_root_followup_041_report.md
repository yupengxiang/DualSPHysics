# DS-DATA-02 Family F7: Root Followup 041 Bounded Fallback Report

- **Scope ID**: `handoff_20261003/root_followup_041_bounded_fallback_v1`
- **Family**: `F7` (Moving Obstacle Exchange & Pump Transport)
- **Physical Mother ID**: `F7_OBSTACLE_SMOOTH_C2_BASE`
- **Mechanism**: `moving_obstacle_exchange`
- **Authoritative Date**: 2026-10-04T03:00:00Z
- **Governance Status**: Preflight / Prospective Repair Staged; `launch_allowed: false`; No Q-I / Q-N / Production Grants

---

## 1. Executive Summary & Preserved Evidence Lineage

Under directives for **ROOT FOLLOWUP 041 F7**, this delivery provides **ONE prospective source-evidence-based smooth driving-control repair** for the F7 moving obstacle within the isolated family worktree `codex/ds-data-02-f7`. 

### Preserved Prior Evidence & Historical Negatives
1. **Source-Bound Original Prescribed Motion Regularity Audit (`root-obstacle-original-source-bound-motion-regularity-017`)**:
   - Source audit report: `DATA/families/F7/F7_OBSTACLE_ORIGINAL_PRESCRIBED_MOTION_REGULARITY/root-obstacle-original-source-bound-motion-regularity-017/motion-regularity.json` (SHA256: `4301fa31...`).
   - Root proved that the reference XML prescribed motion (`mvrotsinu`) contains explicit phase resets, discontinuous velocity jumps ($-34.95^\circ/\text{s} \to 0$ and $0 \to -113.10^\circ/\text{s}$), acceleration jumps ($270.33^\circ/\text{s}^2$), wait states holding an arbitrary rotated pose ($-42.798^\circ$), and ends mid-stroke at $t=12.0\text{ s}$ ($-85.6^\circ$).
   - **Critical Causality Boundary**: This proves source-level kinematic discontinuity in the original driving prescription, **NOT unique causality for the historical 43.011% spatial kinetic-energy discrepancy**. Multi-resolution discretization, lattice-boundary interaction, and numerical particle representation remain active unisolated factors.
2. **Dense Pair Temporal Macro Review (`root_actual_dense_pair_macro_review_016`)**:
   - Baseline dense save vs TRUE half-time-step dense save under fixed frozen physical scales passed with max scaled KE error of $0.01078675$ ($1.08\% \le 5.0\%$ budget).
   - **Affirmation**: Temporal stability under time-step halving isolates the time integrator; it does not explain or cure spatial refinement divergence.
3. **Retained Spatial Discrepancy (`F7_FROZEN_FINE_VS_DP001_SPATIAL_STUDY_001`)**:
   - Fine ($dp=0.016\text{ m}$) vs Finer ($dp=0.010\text{ m}$) spatial comparison retained as **43.011% FAIL** ($0.4301 > 0.05$ budget), with peak KE error at $19.42\%$.
4. **Retained Boundary Exclusions and Paired Transport Fates (`root_paired_transport_comparison_010`, `root_dense_paired_transport_review_012`)**:
   - Excluded boundary particles ($0.410\text{ kg}$ vs $0.423\text{ kg}$, $410$ vs $423$ particles) and crossing fates ($8,376$ vs $8,843$) remain open negative findings classified as **unknown physical fate**; no zero-loss or complete containment claim is made.
5. **Rejection of Owner 039 Causal Flags**:
   - Owner 039 causal hypotheses asserting spatial KE error solely arises from airgap $> 1\text{ mm}$ or truncated kernel radius coverage are rejected per Root directives. Fluid continuous face cannot be inferred from discrete lattice corner metadata alone.
   - Python ElementTree `bool(elem)` walrus bug (where leaf elements without children evaluate to `False` in boolean context) is corrected across all scripts by strictly enforcing `if elem is not None:`.

---

## 2. Official DualSPHysics Motion File Reader Semantics Audit

To eliminate fabricated smoothness from textbook sinusoids, DualSPHysics official C++ source code was audited directly:

### Audited Source Implementation:
- `src/source/JMotion.cpp` (SHA256: `f013c7d7...`):
  - Reads `<mvrotfile>` elements from XML:
    ```xml
    <mvrotfile id="1" duration="12" anglesunits="degrees">
      <file name="motion_obstacle_smooth_c2.dat" />
      <axisp1 x="-0.04" y="0" z="0.05" />
      <axisp2 x="-0.04" y="0" z="1.05" />
    </mvrotfile>
    ```
  - Parses attributes: `duration`, `anglesunits` ("degrees" or "radians"), and axis coordinates `axisp1`, `axisp2`.
- `src/source/JMotionData.cpp` (SHA256: `9ceff907...`):
  - Class `JMotionDataRotAxis::LoadFileAng(dirdata, file, angdegrees)` loads files with `JReadDatafile`.
  - Expects 2 whitespace-separated columns: `Time` and `Angle`. Lines starting with `#` are treated as remark lines.
  - If `angdegrees` is true (default when `anglesunits="degrees"`), values are loaded directly as degrees.
- `src/source/JMotionObj.cpp` (SHA256: `06dafbfcb7...`):
  - In `DfConfig(TpDfRotAxis)`, initializes `DfLastAng = DfAng[0] = 0.0`.
  - At each simulation time step:
    - Calculates target time `t = timestep - amov->Start`.
    - Evaluates interpolated angle: `newang = DfGetNewAng(t)` using piecewise linear interpolation:
      $$\text{tfactor} = \frac{t - t_0}{t_1 - t_0}, \quad \text{newang} = \theta_0 + \text{tfactor} \cdot (\theta_1 - \theta_0)$$
    - Applies incremental rotation: `ModPos.Rotate(newang - DfLastAng, axisp1, axisp2)`.
    - Updates history: `amov->DfLastAng = newang`.
  - **Audit Confirmation**: The motion file specifies **absolute angle** $\theta(t)$ in degrees. DualSPHysics automatically calculates the step delta $\Delta \theta = \theta(t) - \theta(t - \Delta t)$.

---

## 3. Mathematical Formulation of Prospective $C^2$ Driving Control Repair

We design a continuous, piecewise quintic polynomial (minimum-jerk) rotation trajectory satisfying strict $C^2$ regularity across the complete $12.0\text{ s}$ physical event window.

### Base Polynomial & Boundary Derivatives
For each segment of duration $T$ with normalized coordinate $\tau = (t - t_{\text{start}}) / T \in [0, 1]$:
$$s(\tau) = 10\tau^3 - 15\tau^4 + 6\tau^5$$
$$\dot{s}(\tau) = \frac{1}{T} (30\tau^2 - 60\tau^3 + 30\tau^4) = \frac{30}{T} \tau^2 (1 - \tau)^2$$
$$\ddot{s}(\tau) = \frac{1}{T^2} (60\tau - 180\tau^2 + 120\tau^3) = \frac{60}{T^2} \tau (1 - \tau) (1 - 2\tau)$$

Boundary properties at both ends ($\tau = 0$ and $\tau = 1$):
$$s(0) = 0, \quad \dot{s}(0) = 0, \quad \ddot{s}(0) = 0$$
$$s(1) = 1, \quad \dot{s}(1) = 0, \quad \ddot{s}(1) = 0$$

### Physical Event Schedule (Total Window: $12.0\text{ s}$)
1. **Segment 1 ($t \in [0.0, 1.0\text{ s}]$, $T=1.0\text{ s}$)**: Forward stroke from neutral $\theta=0^\circ$ to $+\theta_{\text{max}} = +45.0^\circ$.
   $$\theta(t) = 45^\circ \cdot s(t), \quad \theta(0)=0^\circ, \quad \theta(1)=45^\circ$$
2. **Segment 2 ($t \in [1.0, 3.0\text{ s}]$, $T=2.0\text{ s}$)**: Reverse swing from $+45.0^\circ$ across neutral to $-\theta_{\text{max}} = -45.0^\circ$.
   $$\theta(t) = 45^\circ - 90^\circ \cdot s\left(\frac{t-1}{2}\right), \quad \theta(2)=0^\circ \text{ (neutral crossing)}, \quad \theta(3)=-45^\circ$$
3. **Segment 3 ($t \in [3.0, 5.0\text{ s}]$, $T=2.0\text{ s}$)**: Forward swing from $-45.0^\circ$ across neutral to $+45.0^\circ$.
   $$\theta(t) = -45^\circ + 90^\circ \cdot s\left(\frac{t-3}{2}\right), \quad \theta(4)=0^\circ \text{ (neutral crossing)}, \quad \theta(5)=+45^\circ$$
4. **Segment 4 ($t \in [5.0, 7.0\text{ s}]$, $T=2.0\text{ s}$)**: Reverse swing from $+45.0^\circ$ across neutral to $-45.0^\circ$.
   $$\theta(t) = 45^\circ - 90^\circ \cdot s\left(\frac{t-5}{2}\right), \quad \theta(6)=0^\circ \text{ (neutral crossing)}, \quad \theta(7)=-45^\circ$$
5. **Segment 5 ($t \in [7.0, 8.0\text{ s}]$, $T=1.0\text{ s}$)**: Return stroke from $-45.0^\circ$ to neutral rest $\theta=0.0^\circ$.
   $$\theta(t) = -45^\circ + 45^\circ \cdot s(t-7), \quad \theta(7)=-45^\circ, \quad \theta(8)=0^\circ$$
6. **Segment 6 ($t \in [8.0, 12.0\text{ s}]$, $T=4.0\text{ s}$)**: Neutral rest tail.
   $$\theta(t) \equiv 0.0^\circ, \quad \dot{\theta}(t) \equiv 0.0^\circ/\text{s}, \quad \ddot{\theta}(t) \equiv 0.0^\circ/\text{s}^2$$

---

## 4. Analytic & Synthetic Regularity Audit Ledger

The dedicated worker (`f7_obstacle_smooth_motion_worker.py`) evaluated exact one-sided boundary limits $\lim_{t \to t_j^-}$ and $\lim_{t \to t_j^+}$ across all transitions:

| Junction | Time ($s$) | Event Description | Left Limit $(\theta, \dot{\theta}, \ddot{\theta})$ | Right Limit $(\theta, \dot{\theta}, \ddot{\theta})$ | $\Delta \theta$ ($^\circ$) | $\Delta \dot{\theta}$ ($^\circ/\text{s}$) | $\Delta \ddot{\theta}$ ($^\circ/\text{s}^2$) | $C^2$ Status |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **$t_0$** | $0.00$ | Initial boundary start | $(0.0, 0.0, 0.0)$ | $(0.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |
| **$t_1$** | $1.00$ | Forward peak turnaround | $(45.0, 0.0, 0.0)$ | $(45.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |
| **$t_2$** | $3.00$ | Reverse peak turnaround | $(-45.0, 0.0, 0.0)$ | $(-45.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |
| **$t_3$** | $5.00$ | Forward peak turnaround | $(45.0, 0.0, 0.0)$ | $(45.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |
| **$t_4$** | $7.00$ | Reverse peak turnaround | $(-45.0, 0.0, 0.0)$ | $(-45.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |
| **$t_5$** | $8.00$ | Neutral return & rest entry | $(0.0, 0.0, 0.0)$ | $(0.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |
| **$t_6$** | $12.00$ | Physical window finish | $(0.0, 0.0, 0.0)$ | $(0.0, 0.0, 0.0)$ | $0.000$ | $0.000$ | $0.000$ | **PASS ($C^2$)** |

### Contrast with Root Reference Regularity Audit (`motion-regularity-017`):

| Transition Metric | Original Reference Schedule | Prospective Smooth Repair | Improvement |
| :--- | :---: | :---: | :---: |
| **Max Velocity Jump** | **$-113.10^\circ/\text{s}$** ($t=2.25\text{ s}$) | **$0.000^\circ/\text{s}$** | **$100\%$ Discontinuity Eliminated** |
| **Max Acceleration Jump** | **$270.33^\circ/\text{s}^2$** ($t=2.0\text{ s}$) | **$0.000^\circ/\text{s}^2$** | **$100\%$ Discontinuity Eliminated** |
| **Wait State Pose** | **$-42.8^\circ$ (rotated)** | **$0.0^\circ$ (neutral)** | **Asymmetry eliminated** |
| **$t=12.0\text{ s}$ Terminal State** | Mid-stroke cutoff ($-85.6^\circ$, $+34.9^\circ/\text{s}$) | Complete rest ($0.0^\circ$, $0.0^\circ/\text{s}$) | Finite interaction completed |
| **Linear Interp Bound ($\Delta t=0.001\text{ s}$)** | N/A (analytic formula) | $< 3.25 \times 10^{-5}$ deg | High-fidelity discretised tracking |

---

## 5. Whole-XML Undo & Three Commensurate Reference DPs

Per instructions, prospective definitions restore the exact original continuous geometry, undoing all unverified alterations from Owner 039:
- **Tank Dimensions**: $1.2 \times 0.8 \times 0.6\text{ m}$ ($x \in [-0.6, 0.6]$, $y \in [-0.4, 0.4]$, $z \in [0.0, 0.6]$).
- **Paddle Dimensions**: $0.06 \times 0.48 \times 0.48\text{ m}$, centered on $x=-0.04\text{ m}$, $y \in [-0.24, 0.24]$, $z \in [0.05, 0.53]$.
- **Rotation Axis**: Defined by `axisp1 = [-0.04, 0.0, 0.05]` to `axisp2 = [-0.04, 0.0, 1.05]`.
- **Boundary Layers**: Restored to standard 3 layers: `<layers vdp="0,1,2" />`.
- **Fluid Initialization**: Restored to original `<fillbox modefill="void">` at seeds $(\pm 0.45, 0.0, 0.266)$, targeting continuous fluid volume $0.3201984\text{ m}^3$ ($320.1984\text{ kg}$).
- **First Nominal 3-Ladder Resolutions**:
  - `COARSE`: $dp = 0.025\text{ m}$, `pointref = [0.0125, 0.0125, 0.0125]`
  - `MEDIUM`: $dp = 0.020\text{ m}$, `pointref = [0.010, 0.010, 0.010]`
  - `FINE`: $dp = 0.016\text{ m}$, `pointref = [0.008, 0.008, 0.008]`
- **XML Diff Verification**: `verify_xml_undo_integrity()` confirmed byte-level/tag-level equality outside `<motion>` across all three resolutions.

---

## 6. Formalized Legal Fallback & Pump Branch Governance

- **Two-Repair Boundary Rule**:
  - Repair 1: `F7_OBSTACLE_EXPLICIT_WET_CELLS_001` (Failed with 43.011% spatial KE discrepancy).
  - Repair 2: `F7_OBSTACLE_SMOOTH_C2_BASE` (Current prospective driving-control repair).
  - Exactly 2 evidence-based repairs have now been staged for this root cause. If Repair 2 fails to bring spatial KE error $\le 5.0\%$ under the strict Root dispatcher, the obstacle parameter space will be permanently closed.
- **Formalized Legal Fallback**:
  - `F7_PUMP_STIRRER_FALLBACK_001_FINE` (`configs/f7_legal_fallback_spec.json`), authorized by `plan-source/families/F7.md`.
- **Pump Branch Directives**:
  - The pump branch remains pending a separate mechanism; no quiet proxy is invented.

---

## 7. Staged Requests & Resource Accounting

### Staged Dispatch Requests:
1. `requests/f7_obstacle_smooth_motion_audit_request.json`
   - Kind: CPU audit worker (`launch_allowed: false`)
   - Binds: input file SHAs, audit binding, Root report 017
2. `requests/f7_obstacle_smooth_c2_gencase_request.json`
   - Kind: CPU GenCase preflight on `FINE` definition (`launch_allowed: false`)
   - Max wall: 600 s; Estimated storage: 100 MiB

### Campaign Counters:
- Root remaining GPU budget: ~31 GPU hours before current reservations.
- Qualification progress: 271 / 320 attempts.
- Physically qualified cases: 0 / 336 (No Q-N granted from definitions/receipts alone).
- Production approval: **none**.
- Synthetic Unit Test Suite: 6 passed in 0.37s (`tests/test_f7_obstacle_smooth_motion_worker.py`).

---

## 8. Next Executable Tasks for Root Strict Dispatcher

1. **Authorize CPU Audit Request**: Dispatch `requests/f7_obstacle_smooth_motion_audit_request.json` through the strict runner to verify motion file and XML SHAs under guard.
2. **Authorize CPU GenCase Preflight**: Dispatch `requests/f7_obstacle_smooth_c2_gencase_request.json` through the strict runner to generate native BI4 coordinates and verify discrete particle representation.
3. **Run Multi-Resolution Spatial Convergence**: Execute coarse/medium/fine simulation suite under the strict runner to evaluate whether smooth motion regularisation resolves the spatial KE error.
4. **Trigger Legal Fallback (if needed)**: If spatial error remains $> 5\%$, terminate obstacle modifications and dispatch `F7_PUMP_STIRRER_FALLBACK_001_FINE`.
