# DS-DATA-02 Family F7: Round 046 Three-DP All-Pairs Frozen Macro & Moving Paddle Actual Pose Worker

**Directory**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_046_quintic_three_dp_frozen_macro_v1`  
**Physical Case**: `F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1`  
**Lineage Group**: `F7_OBSTACLE_REFERENCE_BASE_AND_QUINTIC_SHARED_GEOMETRY_NO_LEAK`  
**Physical Condition SHA256**: `512cb217f29e716346c249339545ed2599e7cb1aeb8e81fe7f1c0cf7f341c34c`  

---

## 1. Scope & Governance Boundary

- **Source-Only Ownership**: Pure source code, mathematical specifications, request building, input validation, and unit tests.
- **Compute Guarding**: Solver executions, GenCase runs, HDF5 reading/processing, and numerical conversions are strictly guarded and executed by Root on shared runner infrastructure.
- **Q-N Status**: `not_granted`
- **Production Approval**: `none`
- **Spatial Negative Preservation**: The historical ~43% kinetic energy discrepancy from previous kinematics is retained. The 5% macro relative budget failure gate is strictly preserved and not waived or circumvented.
- **Refinement Ratio Boundary**:
  - Coarse: $dp = 0.020$ m (40,700 fluid, 1,984 moving Type 1, 27,495 fixed Type 0)
  - Medium: $dp = 0.016$ m (78,732 fluid, 3,798 moving Type 1, 42,612 fixed Type 0)
  - Fine: $dp = 0.010$ m (318,716 fluid, 4,899 moving Type 1, 100,662 fixed Type 0)
  - Ratios: Coarse / Medium = $1.25$, Medium / Fine = $1.60$, Coarse / Fine = $2.00$.
  - **Explicit Rejection**: Constant refinement ratio claim is rejected ($1.25 \neq 1.60$).
  - **Explicit Rejection**: No particle UID match exists across discretizations.

---

## 2. Mathematical Formulations & Exact Equations

### 2.1 Analytic Quintic Minimum-Jerk Target Motion
The reference trajectory is defined across $[0, 12]$ s as two symmetric $45^\circ$ cycles in $[0, 8]$ s and a neutral rest tail in $[8, 12]$ s:
- Base polynomial on $\tau \in [0, 1]$:
  $$s(\tau) = 10\tau^3 - 15\tau^4 + 6\tau^5$$
  $$\frac{ds}{d\tau} = 30\tau^2(1 - \tau)^2$$
  $$\frac{d^2s}{d\tau^2} = 60\tau(1 - \tau)(1 - 2\tau)$$
  Satisfies $s(0) = 0$, $s(1) = 1$, and $s'(0) = s'(1) = s''(0) = s''(1) = 0$.
- Five active segments:
  1. $[0, 1]$ s: $0^\circ \to +45^\circ$, $\theta(t) = 45 \cdot s(t)$
  2. $[1, 3]$ s: $+45^\circ \to -45^\circ$, $\theta(t) = 45 - 90 \cdot s((t - 1)/2)$
  3. $[3, 5]$ s: $-45^\circ \to +45^\circ$, $\theta(t) = -45 + 90 \cdot s((t - 3)/2)$
  4. $[5, 7]$ s: $+45^\circ \to -45^\circ$, $\theta(t) = 45 - 90 \cdot s((t - 5)/2)$
  5. $[7, 8]$ s: $-45^\circ \to 0^\circ$, $\theta(t) = -45 + 45 \cdot s(t - 7)$
  6. $[8, 12]$ s: $\theta(t) \equiv 0^\circ$ (neutral rest)

### 2.2 DualSPHysics Native Reader & Rejection of C2 Claim
- Official reader `JMotionMovActive::DfGetNewAng` (`src/source/JMotionObj.cpp:214-226`):
  $$\theta(t) = \theta_{i-1} + \frac{t - t_{i-1}}{t_i - t_{i-1}} (\theta_i - \theta_{i-1})$$
- Forcing is **piecewise linear** with piecewise constant angular velocities and finite knot slope jumps $\Delta v_i \neq 0$. Native C2 continuity in the solver is **rejected**.

### 2.3 Moving Type 1 Marker Actual Pose Path
- Rotating paddle boundary markers have `initial_type == 1`.
- Rotation axis: point $P_0 = [-0.04, 0.0, 0.05]$ m, vertical direction $\hat{z} = [0, 0, 1]$.
- From actual marker positions in the $xy$-plane at time $t$ relative to $t = 0$:
  $$\Delta x_i(t) = x_i(t) - (-0.04), \quad \Delta y_i(t) = y_i(t) - 0.0$$
  $$\theta(t) = \text{atan2}\left( \sum_{i=1}^{N_1} (\Delta y_i(t) \Delta x_i(0) - \Delta x_i(t) \Delta y_i(0)), \sum_{i=1}^{N_1} (\Delta x_i(t) \Delta x_i(0) + \Delta y_i(t) \Delta y_i(0)) \right)$$
  $$\vec{x}_{\text{centroid}}(t) = \frac{1}{N_1} \sum_{i=1}^{N_1} \vec{x}_i(t)$$
  $$\text{RMS}_{\text{rigid}}(t) = \sqrt{\frac{1}{N_1} \sum_{i=1}^{N_1} |\vec{r}_i(t) - R(\theta(t)) \vec{r}_i(0)|^2}$$

### 2.4 Frozen Macro Observables & Normalizers
- Uniform 601-point evaluation grid: $t \in [0, 12]$ s, $\Delta t = 0.02$ s.
- Standard 5 operators:
  1. `active_mass_kg`: $M(t) = \sum_{i \in \text{fluid}, \text{valid}} m_i$, scaled by $M_0 = 320.1984$ kg.
  2. `com_x_m`, `com_y_m`, `com_z_m`: mass-weighted center of mass, scaled by envelope widths $[1.1, 0.7, 0.432]$ m.
  3. `kinetic_energy_j`: $KE(t) = \frac{1}{2} \sum_{i \in \text{fluid}, \text{valid}} m_i |\vec{v}_i|^2$, scaled by Fine reference peak KE over $[0, 12]$ s.
- Scaled error metrics across all 3 pairs (`coarse_vs_medium`, `medium_vs_fine`, `coarse_vs_fine`):
  $$e_O(t) = \frac{|O_{\text{cand}}(t) - O_{\text{base}}(t)|}{S_O}$$
  $$\text{max\_scaled\_error} = \max_t e_O(t) \le 0.05$$
  $$\text{kinetic\_time\_mean} = \frac{1}{12 \cdot S_{KE}} \left| \int_0^{12} (KE_{\text{cand}} - KE_{\text{base}}) dt \right| \le 0.05$$
  $$\text{kinetic\_peak} = \frac{|\max KE_{\text{cand}} - \max KE_{\text{base}}|}{S_{KE}} \le 0.05$$

### 2.5 Native Unknown Exclusions Policy
- Policy: `native_unknown_exclusions_retained`.
- Fluid particles with `valid == False` are logged as unknown physical fates. Closed-cohort assumption is strictly rejected.

---

## 3. Package File Layout

```
root_followup_046_quintic_three_dp_frozen_macro_v1/
├── README.md                           # Documentation, exact formulas, governance boundaries
├── exact_equations_and_normalizers.json # Machine-readable exact equations, normalizers, pins
├── binding.json                        # Comprehensive 3DP binding connecting coarse, medium, fine
├── request.json                        # Runner request adhering to ds02.runner-request.v2
├── f7_three_dp_frozen_macro_worker.py  # Source-only worker for macro & actual moving pose review
├── request_builder_cli.py              # CLI tool for building bindings, requests, and validating inputs
└── tests/
    ├── __init__.py
    └── test_f7_three_dp_frozen_macro.py # Complete test suite (11 unit/synthetic tests)
```

---

## 4. CLI Usage Instructions

### Build Binding
```bash
python request_builder_cli.py build-binding --output binding.json
```

### Build Runner Request
```bash
python request_builder_cli.py build-request --binding binding.json --output request.json
```

### Validate Inputs (Source-Only)
```bash
python request_builder_cli.py validate-inputs --binding binding.json
```

### Inspect Pinned Geometry & Governance
```bash
python request_builder_cli.py inspect
```

### Run Unit Tests
```bash
pytest tests/test_f7_three_dp_frozen_macro.py -v
```

---

## 5. Explicit Gaps & Future Dependencies

1. **Three-DP Macros Qualification Boundary**: ThreeDP macros alone do not grant whole Q-N. Independent time-step sensitivity, save cadence sensitivity, and motion file sampling cadence sensitivity ($0.001$ s vs $0.0005$ s) remain strictly required.
2. **Residence Observable Budget**: Residence-specific registered budget is currently `None`. Unnormalised seconds and $\text{kg}\cdot\text{s}$ are reported as diagnostic metrics without qualification claims.
3. **Pending Fine Conversion**: Coarse typed conversion is completed (returncode 0), medium conversion is completed, and fine typed conversion is registered under Root guarded compute. Actual numeric review will be executed once Root guarded compute finishes fine conversion.
