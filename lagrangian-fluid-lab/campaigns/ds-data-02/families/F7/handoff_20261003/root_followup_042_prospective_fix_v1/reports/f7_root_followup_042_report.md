# DS-DATA-02 Family F7: Root Followup 042 Prospective Repair Report

- **Scope ID**: `handoff_20261003/root_followup_042_prospective_fix_v1`
- **Family**: `F7` (3-D Moving Obstacle Exchange & Pump Recirculation)
- **Physical Mother ID**: `F7_OBSTACLE_SMOOTH_C2_BASE`
- **Mechanism**: `moving_obstacle_exchange`
- **Authoritative Timestamp**: 2026-10-04T03:20:00Z
- **Governance State**: Prospective repair staged; `launch_allowed: false`; No Q-I / Q-N / Production Grants

---

## 1. Governance, Resource Accounting & Operational Boundaries

Per authoritative campaign accounting:
- **Campaign Goal Progress**: `0/336` (No production case completed from metadata or scripts alone)
- **Campaign Qualification Progress**: `273/320`
- **GPU Budget**: Charged `65.3 GPUh` of `96.0 GPUh` (`30.7 GPUh` remaining parent budget)
- **Storage Accounting**: Home floor `500 GiB` / free `~2978 GiB`
- **Historical Evidence & Scope Preservation**:
  - Round 041 artifacts remain byte-preserved in `handoff_20261003/root_followup_041_bounded_fallback_v1`.
  - Fresh assigned family scope is strictly `handoff_20261003/root_followup_042_prospective_fix_v1`.
  - Claims require actual solver data; no invented acceptance thresholds, guarantees, or unique causal assertions.
  - Worktree generation policy: **No actual scientific motion `.dat` files are generated in this worktree**. Root-ready execution requests are staged for Root strict dispatcher under Rootguard.

---

## 2. Rejection of Owner-041 Native Continuity Guarantee

In Round 041, the owner designed an analytic quintic polynomial trajectory and claimed:
*"elimination of velocity jumps and acceleration jumps; exact zero native velocity/acc discontinuities; all_c2_continuous: True"*.

### Source Audit of DualSPHysics Reader Implementation:
Direct audit of official DualSPHysics C++ source reveals the native reader mechanics:
- **Reader File**: [`src/source/JMotionObj.cpp`](file:///home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/src/source/JMotionObj.cpp#L214-L226)
- **Function**: `double JMotionMovActive::DfGetNewAng(double t)`
```cpp
double JMotionMovActive::DfGetNewAng(double t){
  double newang;
  if(DfIndex==0)DfIndex=BinarySearch(DfCount,DfTimes,t);
  while(DfIndex<DfCount&&t>DfTimes[DfIndex])DfIndex++;
  if(DfIndex>=DfCount)newang=DfAng[DfCount-1];
  else{
    const double tfactor=(t-DfTimes[DfIndex-1])/(DfTimes[DfIndex]-DfTimes[DfIndex-1]);
    double ang0=DfAng[DfIndex-1],ang=DfAng[DfIndex];
    newang=ang0+tfactor*(ang-ang0);
  }
  return(newang);
}
```
- **Motion Caller Pin**: [`src/source/JMotionObj.cpp:615-627`](file:///home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/src/source/JMotionObj.cpp#L615-L627):
  Evaluates `double newang = amov->DfGetNewAng(t); double ang = newang - amov->DfLastAng; ModPos.Rotate(...)`.
- **File Loader Pin**: [`src/source/JMotionData.cpp:124-145`](file:///home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/src/source/JMotionData.cpp#L124-L145):
  `JMotionDataRotAxis::LoadFileAng` loading whitespace-separated pairs `(time, angle)`.

### Mathematical Reasons for Rejection:
1. **Piecewise Linear Evaluation**: DualSPHysics does **not** evaluate high-order spline or polynomial interpolation at runtime. It performs standard piecewise **linear** interpolation between sample knots $(t_i, \theta_i)$.
2. **Piecewise Constant Velocity**: On every interval $[t_{i-1}, t_i]$, the angular velocity is constant:
   $$v_{i-1/2} = \frac{\theta_i - \theta_{i-1}}{t_i - t_{i-1}}$$
3. **Finite Knot Slope Jumps**: At each knot $t_i$, the angular velocity changes abruptly:
   $$\Delta v_i = v_{i+1/2} - v_{i-1/2} \approx \ddot{\theta}(t_i) \cdot \Delta t \neq 0$$
   For $\Delta t = 0.001\text{ s}$, $\max |\Delta v_i| \approx 0.2598^\circ/\text{s}$.
4. **Non-Zero Start-Interval Slope**: Over the initial interval $[0, \Delta t]$, $\theta(0) = 0^\circ$ and $\theta(\Delta t) \approx 4.5 \times 10^{-7\circ}$, giving an interval slope of $v_{1/2} \approx 4.5 \times 10^{-4\circ}/\text{s}$. Since prior to $t=0$ the object is at rest ($v(0^-) = 0$), there is a finite jump at $t=0^+$.
5. **Conclusion**: The sampled `.dat` file is **not** mathematically $C^2$ in the native solver. The owner guarantee of exact zero native velocity/acceleration discontinuities is **REJECTED**.

---

## 3. Mathematical Formulation of Smooth Target & Sampled I/O Descriptor

### A. Analytic Smooth Target (Minimum-Jerk Quintic)
- Normalized coordinate: $\tau = (t - t_{\text{start}}) / T \in [0, 1]$
- Base polynomial:
  $$s(\tau) = 10\tau^3 - 15\tau^4 + 6\tau^5$$
  $$\dot{s}(\tau) = \frac{30}{T}\tau^2(1 - \tau)^2, \quad \ddot{s}(\tau) = \frac{60}{T^2}\tau(1 - \tau)(1 - 2\tau)$$
- Exact one-sided derivatives at junctions:
  $$\lim_{\tau \to 0^+} \dot{s}(\tau) = 0, \quad \lim_{\tau \to 0^+} \ddot{s}(\tau) = 0, \quad \lim_{\tau \to 1^-} \dot{s}(\tau) = 0, \quad \lim_{\tau \to 1^-} \ddot{s}(\tau) = 0$$
- Across all transition junctions ($t \in \{0, 1, 3, 5, 7, 8, 12\}\text{ s}$), analytic left and right limits are verified identical with zero velocity and acceleration.
- Rest tail: $t \in [8.0, 12.0]\text{ s}$ holds neutral pose ($\theta = 0.0^\circ$, $\dot{\theta} = 0$, $\ddot{\theta} = 0$).

### B. Distinct ACTUAL Sampled File I/O Descriptor
Rather than claiming false continuum smoothness, the descriptor calculates concrete discrete properties:

| Metric | Selected Target ($\Delta t = 0.001\text{ s}$) | Independent Control ($\Delta t = 0.0005\text{ s}$) | Scaling Behavior |
| :--- | :--- | :--- | :--- |
| **Total Knots** | 12,001 | 24,001 | $N = T / \Delta t + 1$ |
| **Start-Interval Slope ($v_{1/2}$)** | $4.493253 \times 10^{-4\circ}/\text{s}$ | $1.124156 \times 10^{-4\circ}/\text{s}$ | $O(\Delta t^2)$ |
| **Max Interval Slope** | $84.374944^\circ/\text{s}$ | $84.374986^\circ/\text{s}$ | Converges to $84.375^\circ/\text{s}$ |
| **Max Knot Slope Jump ($\max |\Delta v_i|$)** | $0.259806^\circ/\text{s}$ | $0.129904^\circ/\text{s}$ | $O(\Delta t)$ (halved) |
| **Peak Analytic Acceleration** | $259.807621^\circ/\text{s}^2$ | $259.807621^\circ/\text{s}^2$ | Continuous invariant |
| **Linear Error Bound ($\frac{1}{8}\Delta t^2 \max|\ddot{\theta}|$)** | $3.247595 \times 10^{-5\circ}$ | $8.118988 \times 10^{-6\circ}$ | $O(\Delta t^2)$ ($4\times$ reduction) |
| **Empirical Max Chord Deviation** | $3.247591 \times 10^{-5\circ}$ | $8.118986 \times 10^{-6\circ}$ | Strictly $\le$ theoretical bound |

---

## 4. I/O Precision (`.17g`) and Exclusive Output Mode (`'x'`)

1. **IEEE 754 Full Roundtrip Precision**:
   - Replaces truncated formatting (`%18.10f`) with `%.17g`.
   - Guaranteed exact bitwise floating-point roundtrip: `float(f"{val:.17g}") == val`.
2. **Overwrite-Safe Exclusive Writing**:
   - All motion file writes enforce mode `'x'` (`open(path, 'x', encoding='utf-8')`).
   - Prevents unsafe overwrites of existing provenance files by throwing `FileExistsError`.
3. **Dispatch Policy**:
   - The worker defaults to audit/dry-run mode without writing `.dat` files to disk.
   - Generation flag `--generate-controls` is restricted to Root strict dispatcher under Rootguard.

---

## 5. XML Declared Subtree Replacement & Independent Whole-Undo Verification

1. **Declared Modification Subtree**:
   Only the element `<casedef><motion><objreal ref="2">` is modified:
   ```xml
   <motion>
     <objreal ref="2">
       <begin mov="1" start="0" finish="12" />
       <mvrotfile id="1" duration="12" anglesunits="degrees">
         <file name="motion_obstacle_smooth_c2.dat" />
         <axisp1 x="-0.04" y="0" z="0.05" />
         <axisp2 x="-0.04" y="0" z="1.05" />
       </mvrotfile>
     </objreal>
   </motion>
   ```
2. **Whole-XML Undo Verification**:
   The independent verification function restores the reference motion block and serializes the tree:
   $$\text{ET.tostring}(\text{restored\_root}) == \text{ET.tostring}(\text{ref\_root})$$
   - `COARSE`: `whole_tree_identical_upon_undo: True`, `declared_motion_subtree_isolated: True`
   - `MEDIUM`: `whole_tree_identical_upon_undo: True`, `declared_motion_subtree_isolated: True`
   - `FINE`: `whole_tree_identical_upon_undo: True`, `declared_motion_subtree_isolated: True`
3. **Field-by-Field Non-Motion Preservation**:
   - `mkconfig`: identical (`boundcount="240" fluidcount="9"`)
   - `constantsdef`: identical (`gravity`, `rhop0`, `coefsound`, `coefh`, etc.)
   - `geometry`: identical (`pointref`, `pointmin`, `pointmax`, `drawbox`, `fillbox`, etc.)
   - `execution`: identical (`SavePosDouble`, `StepAlgorithm`, `Kernel`, `Visco`, `TimeMax`, etc.)
   - **No silent new geometry kernel repair**.

---

## 6. Case Count Prediction & Root-Ready Requests

### Predicted Case Matrix:
- **Base Definitions**: 3 cases (`COARSE`, `MEDIUM`, `FINE`) under physical mother `F7_OBSTACLE_SMOOTH_C2_BASE`.
- **Independent Cadence Study**: 1 control study (`dt = 0.0005 s`) evaluating time-cadence sensitivity independently from spatial refinement.
- **Independent Case Count Increment**: `0` (pending Root qualification).
- **No Production Proxy / No Pump Fallback**: No whole production claims (0/48) or pump fallback claims are made.

### Staged Root-Ready Requests (Rootguard Dispatch Only):
1. `requests/f7_obstacle_smooth_c2_motion_generation_request.json`: Rootguard CPU request to generate `.001s` and `.0005s` controls with exclusive mode `'x'`.
2. `requests/f7_obstacle_smooth_c2_gencase_request.json`: Rootguard CPU preflight request for GenCase.
3. `requests/f7_obstacle_smooth_motion_audit_request.json`: Rootguard CPU audit request.

---

## 7. Verification Summary

Unit and synthetic fixture tests executed via pytest:
- `test_quintic_polynomial_boundary_derivatives`: PASSED
- `test_analytic_c2_continuity_and_rest_tail`: PASSED
- `test_sampled_motion_io_math_synthetic_fixture`: PASSED
- `test_cadence_sensitivity_scaling_dt001_vs_dt0005`: PASSED
- `test_float_17g_exact_roundtrip`: PASSED
- `test_motion_dat_synthetic_content_format`: PASSED
- `test_exclusive_output_mode_x_prevents_overwrite`: PASSED
- `test_xml_whole_tree_undo_identity`: PASSED
- `test_case_manifests_integrity`: PASSED
- **Total**: 9 passed in 0.17s.
