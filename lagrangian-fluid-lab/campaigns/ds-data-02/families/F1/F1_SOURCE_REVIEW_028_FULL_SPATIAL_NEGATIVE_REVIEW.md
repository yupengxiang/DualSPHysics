# DS-DATA-02 F1 Source Review 028: Full 1601 Frozen Thick-DBC 3DP Macro Negative Review

## 1. Executive Summary & Root Artifact Binding

Root completed the full 1601-frame frozen macro comparison of the F1 Eccentric Obstacle Thick-DBC 3DP suite:
- **Artifact Path**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_ACTUAL_FULL_THREE_DP_MACRO/root-ecc-thick-dbc-full1601-three-dp-frozen-macro-009/macro-comparison.json`
- **Receipt Path**: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_ACTUAL_FULL_THREE_DP_MACRO/root-ecc-thick-dbc-full1601-three-dp-frozen-macro-009/execution-receipt.json`
- **Frozen Contract Hash**: `59d41207d2905e68d09575ddb75b14ee9393defe34eb808b4fc5e53547a7c74b`
- **Native Evaluation Window**: `[0.0s, 1.600s]` (1601 common nominal physical save bins at $\Delta t_{\text{save}} = 0.001$s; full window enforced, zero truncation, no short-prefix substitution, no 5% relaxation).

### Authoritative Metric Audit Results

| Pair | COM / $H_0$ (max) | Quantiles / $H_0$ (max) | KE / $MgH_0$ (max) | Velocity Max (m/s) | Mass Error | Macro Pass (5%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fine vs Medium** | **0.06217** (FAIL) | **0.13919** (FAIL) | **0.03300** (PASS) | 0.06601 | $8.25 \times 10^{-5}$ | **FALSE** |
| **Fine vs Coarse** | **0.23169** (FAIL) | **0.52766** (FAIL) | **0.06374** (FAIL) | 0.13247 | $8.25 \times 10^{-5}$ | **FALSE** |
| **Medium vs Coarse**| **0.17053** (FAIL) | **0.39607** (FAIL) | **0.04556** (PASS) | 0.09631 | 0.0 | **FALSE** |

**Conclusion**: All three resolution pairs **macro fail** the frozen 5% screening budget. Root Q-N qualification remains strictly **0/336**.

---

## 2. Immutable Mother Condition vs Legitimate Discrete Geometries

1. **Continuous Mother Condition**:
   - Continuous initial water volume: $[0, 0.4]\text{m} \times [0, 0.67]\text{m} \times [0, 0.3]\text{m} = 0.0804\text{ m}^3$.
   - Continuous mass: $M = 80.4000\text{ kg}$ ($\rho_0 = 1000\text{ kg/m}^3$).
   - Initial height: $H_0 = 0.3000\text{ m}$.
   - Continuous mother physical hash: `b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb` (identically verified across coarse, medium, fine).
2. **Legitimate Discrete Geometry Hash Differences**:
   - Coarse ($dp = 0.010$m): `180699622a3eba93cd3bf53a7b0d45f6b7bf86e2fd69d67ede17007290be8b9b`
   - Medium ($dp = 0.005$m): `bdee7f4728505a9bcc8ebb01738d7dde31e59f84bc6419b3f0889ca76a7555bd`
   - Fine ($dp = 0.00333333$m): `a0147786d984cf1da41520ef83c4b4a7bf43bfbacb9888f60514ce1351467a6a`
   - **Reason**: Thick-DBC boundary layers are constructed as 3 discrete lattice layers of thickness $a = 2.5 \cdot dp$ outside fluid boundaries and inside the frozen obstacle solid. The resulting discrete XML geometry primitives naturally differ with $dp$, representing identical continuous container bounds ($1.6\text{m} \times 0.67\text{m} \times 0.45\text{m}$) and obstacle bounds ($[0.9, 1.02]\text{m} \times [0.24, 0.36]\text{m} \times [0, 0.45]\text{m}$).

---

## 3. Source & Header-Only Inspection of Solver Telemetry

Inspected actual execution files:
- Coarse: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_DP010/qualification-ecc-thick-boundary-dp010-full-20261003-001-root-nvme-003/solver_output/`
- Medium: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/qualification-ecc-thick-boundary-v3-1-dp005-full-20261003-001-root-nvme-004/solver_output/`
- Fine: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/qualification-ecc-thick-boundary-v3-2-dp003333333333333333-full-20261003-001-root-nvme-004/solver_output/`

### A. Solver Numerical Configuration (Run.out)

| Parameter | Coarse ($dp = 0.010$m) | Medium ($dp = 0.005$m) | Fine ($dp = 0.00333333$m) | Source Specification |
| :--- | :---: | :---: | :---: | :--- |
| **Solver Version** | DualSPHysics5 v5.4.355 | DualSPHysics5 v5.4.355 | DualSPHysics5 v5.4.355 | Official linux64 build |
| **StepAlgorithm** | `Verlet` | `Verlet` | `Verlet` | `StepAlgorithm=1`, `VerletSteps=40` |
| **Kernel** | `CubicSpline` | `CubicSpline` | `CubicSpline` | `Kernel=1` |
| **Coefh** | 1.0 | 1.0 | 1.0 | $H = \text{Coefh} \cdot \sqrt{3} \cdot dp$ |
| **Smoothing Length $H$** | $0.017321$ m | $0.008660$ m | $0.005774$ m | $H / dp = 1.73205$ |
| **Kernel Size ($2H$)** | $0.034641$ m | $0.017321$ m | $0.011547$ m | Full interaction diameter |
| **Viscosity** | `Artificial` ($\alpha = 0.1$) | `Artificial` ($\alpha = 0.1$) | `Artificial` ($\alpha = 0.1$) | $\text{ViscoBoundFactor} = 1.0$ |
| **Speed of Sound $c_{s0}$** | $33.7337$ m/s | $33.7337$ m/s | $33.7337$ m/s | $\gamma = 7$, $\rho_0 = 1000$ |
| **CFLnumber** | 0.2 | 0.2 | 0.2 | Variable time step control |
| **CoefDtMin** | 0.05 | 0.05 | 0.05 | $\text{DtMin} = \text{CoefDtMin} \cdot H / c_{s0}$ |
| **DtMin** | $2.5672 \times 10^{-5}$ s | $1.2727 \times 10^{-5}$ s | $8.4608 \times 10^{-6}$ s | Lower clamp floor |
| **Particles (Fluid / Total)**| 80,400 / 181,836 | 643,200 / 1,032,852 | 2,170,800 / 3,035,772 | Scaled as $1 : 8 : 27$ |
| **SimRuntime** | 19.75 s ($0.0055$ GPUh) | 167.13 s ($0.0464$ GPUh) | 723.76 s ($0.2010$ GPUh) | Full 3DP suite = $0.253$ GPUh |

### B. Dt Clamping Audit (RunPARTs.csv Telemetry)

A complete inspection of all 1601 PART records in `RunPARTs.csv` yields:
- **Coarse**: `DTsMin = 0` for all 1601 parts. Actual $dt \in [1.0013 \times 10^{-4}\text{s}, 1.0024 \times 10^{-4}\text{s}]$ ($\approx 10$ steps per save bin).
- **Medium**: `DTsMin = 0` for all 1601 parts. Actual $dt \in [4.9111 \times 10^{-5}\text{s}, 4.9164 \times 10^{-5}\text{s}]$ ($\approx 21$ steps per save bin).
- **Fine**: `DTsMin = 0` for all 1601 parts. Actual $dt \in [3.2416 \times 10^{-5}\text{s}, 3.2580 \times 10^{-5}\text{s}]$ ($\approx 31$ steps per save bin).
- **Verdict**: **Dt clamping NEVER occurred** in any of the three simulations. Time step clamping is 100% ruled out as a root cause by definitive telemetry evidence.

---

## 4. Time-Resolved Error Analysis (Fine vs Medium)

Analyzing the 1601-point time series reveals where and when the 5% screening budget is exceeded:

```
Window (s)    max COM / H0    max Quantiles / H0    max KE / MgH0    Physical Regime
[0.0, 0.2]       0.00480           0.01495             0.00753       Initial dam release (column collapse)
[0.2, 0.4]       0.01946           0.07368 (FAIL)      0.01615       Wavefront travels towards obstacle
[0.4, 0.6]       0.03979           0.13499 (FAIL)      0.01877       Impact on obstacle at x=0.9m; splash
[0.6, 0.8]       0.05635 (FAIL)    0.13919 (FAIL)      0.01778       Peak quantile divergence; wave separation
[0.8, 1.0]       0.06377 (FAIL)    0.12255 (FAIL)      0.01787       Impact on back tank wall at x=1.6m
[1.0, 1.2]       0.06370 (FAIL)    0.12330 (FAIL)      0.03300       Back-wall reflection & return wave
[1.2, 1.4]       0.05019 (FAIL)    0.12611 (FAIL)      0.02820       Sloshing return towards obstacle
[1.4, 1.6]       0.02402 (PASS)    0.04900 (PASS)      0.01480       Post-reflection relaxation
```

### Key Physical Observations
1. **Initial Phase Convergent**: During $[0.0, 0.2]$s, COM error is $< 0.5\%$, quantile error is $< 1.5\%$, and KE error is $< 0.8\%$.
2. **Transient Divergence Window**: The exceedance above 5% occurs strictly during $[0.358\text{s}, 1.287\text{s}]$:
   - Quantile error peaks at $t = 0.621$s ($0.13919 \cdot H_0 \approx 4.18$ cm along X).
   - COM error peaks at $t = 0.983$s ($0.06377 \cdot H_0 \approx 1.91$ cm along X; X-component is $0.06209$ vs Y $0.00207$ and Z $0.01443$).
3. **End Phase Returns Below 5%**: In the final window $[1.4, 1.6]$s, COM error drops to $0.0240$ (2.4%), quantile error drops to $0.0490$ (4.9%), and KE error is $0.0148$ (1.5%).
4. **Dominant Axis**: Divergence is $> 95\%$ aligned with the X-axis (the streamwise wave propagation and obstacle impact axis).

---

## 5. Discriminating Root Causes & Hypotheses

### Root Cause 1: Temporal Discretization Coupling under Acoustic CFL Scaling (Hypothesis T)
- **Primary Mechanism**: The solver uses variable time-stepping controlled by $\text{CFL} = 0.2$. Because acoustic sound speed $c_{s0} \approx 33.7$ m/s dominates over flow velocity ($u \le 2.5$ m/s), actual $dt$ scales strictly with smoothing length $H$:
  $$dt \approx \text{CFL} \cdot \frac{H}{c_{s0} + u_{\max}} \propto dp$$
  As $dp$ decreases from $0.005$m to $0.00333$m, $dt$ drops from $49.1 \mu$s to $32.4 \mu$s ($1.51\times$ reduction).
- **Impact**: The macro comparison is simultaneously testing spatial grid refinement ($dp$) and temporal time-step refinement ($dt$). Verlet time integration under high-acceleration impact ($a \sim O(100\text{ m/s}^2)$ during obstacle collision) accumulates temporal phase shifts when $dt$ differs by $50\%$.
- **Prior Thinwall Errata**: Earlier F1 work performed a "half-dt" study on the *thinwall* geometry. As established in campaign boundaries, **thinwall halfdt was a different recipe and cannot replace temporal qualification on the current thick-DBC recipe**. Thick-DBC has never undergone an isolated temporal convergence qualification.

### Root Cause 2: Boundary Cushion Standoff Scaling in DBC (Hypothesis B)
- **Primary Mechanism**: Dynamic Boundary Conditions (DBC) compute pressure repulsion via kernel evaluation $\nabla W_{ij}$. The effective hydrodynamic repulsion standoff distance is proportional to $H = \sqrt{3} \cdot dp$.
- **Impact**: When the wavefront hits the obstacle face at $x = 0.90$m:
  - Medium ($H = 8.66$ mm): Repulsion begins at distance $\sim 1.5 H \approx 13$ mm ahead of the wall ($x \approx 0.887$m).
  - Fine ($H = 5.77$ mm): Repulsion begins at distance $\sim 1.5 H \approx 8.7$ mm ahead of the wall ($x \approx 0.891$m).
  - The $\approx 4.3$ mm difference in standoff creates an immediate streamwise phase shift of $\Delta x / H_0 \approx 0.0043 / 0.30 \approx 0.014$ (1.4% of $H_0$).
- **Kernel Incompleteness**: The 3-layer boundary has thickness $2.5 \cdot dp$ ($0.0125$m in medium). The full kernel interaction diameter is $2 \cdot H = 3.464 \cdot dp$ ($0.0173$m in medium). Boundary particles within $0.0048$m of the obstacle face suffer truncated kernel support into the solid.

### Root Cause 3: Artificial Viscosity Dissipation Scaling (Hypothesis V)
- **Primary Mechanism**: Monaghan artificial viscosity $\Pi_{ij}$ produces an effective kinematic dissipation $\nu_{\text{art}} \approx \frac{1}{10} \alpha H c_s$.
- **Impact**: As $H$ scales down by $3\times$ from coarse to fine, $\nu_{\text{art}}$ decreases from $5.84 \times 10^{-3}\text{ m}^2/\text{s}$ to $1.95 \times 10^{-3}\text{ m}^2/\text{s}$. The finer simulation is physically less dissipative, leading to sharper wave crests, higher splash velocities, and slower dissipation of splash kinetic energy.
- **Rule Compliance**: The prompt mandates: *"Do not attribute divergence to chaos/viscosity/clamping without actual evidence."* Therefore, viscosity scaling is documented as a physical property of SPH, but is NOT claimed as the primary discriminating root cause without direct measurement.

---

## 6. Two Justified Repair Trials & Recommended Next Branch

Under the campaign resource constraint of **remaining ~46 GPUh and 67 qualification attempts** (with a strict rule of maximum two justified repair trials per root cause, and no launching outside Root dispatcher):

### Trial 1 (Hypothesis T - Temporal Qualification on Thick DBC)
- **Objective**: Isolate temporal truncation error from spatial grid error on the actual Thick-DBC recipe.
- **Action**: Run F1 Thick-DBC Medium ($dp = 0.005$m) with $\text{CFL} = 0.133$ (reducing $dt$ from $\approx 49.1 \mu$s to $\approx 32.5 \mu$s, exactly matching Fine $dt$).
- **Evaluation**:
  1. Compare Medium($\text{CFL}=0.133$) vs Medium($\text{CFL}=0.200$) to measure pure temporal convergence.
  2. Compare Medium($\text{CFL}=0.133$) vs Fine($\text{CFL}=0.200$) using the frozen macro-comparison tool to test whether matching $dt$ brings COM error within the 5% budget ($0.06217 \to \le 0.05000$).
- **Resource Cost**: 1 solver attempt, $\approx 350$s GPU runtime $\approx 0.097$ GPUh, 1 attempt count.

### Trial 2 (Hypothesis B - 4-Layer Kernel-Complete Thick DBC)
- **Objective**: Eliminate boundary kernel truncation and equalize boundary support depth across resolutions.
- **Action**: Expand boundary support from 3 layers ($2.5 \cdot dp$) to 4 layers ($3.5 \cdot dp$). At $3.5 \cdot dp$, boundary thickness strictly exceeds $2 \cdot H = 3.464 \cdot dp$, guaranteeing 100% full kernel support for all fluid particles at the solid boundary.
- **Evaluation**: Run full 3DP suite (coarse, medium, fine) with 4-layer DBC and evaluate macro comparison.
- **Resource Cost**: 3 solver attempts, $\approx 950$s GPU runtime $\approx 0.264$ GPUh, 3 attempt counts.

### Concrete Recommended Best Next Branch
**Trial 1 (Temporal Qualification on Thick DBC)** is the single concrete best next branch:
1. **Zero Geometry Invalidation**: It requires zero changes to the immutable XML geometry definitions, preserving the identical physical condition and discrete boundary coordinates.
2. **Minimal Resource Consumption**: Consumes $< 0.10$ GPUh and only 1 qualification attempt, well within the 46 GPUh / 67 attempts budget.
3. **Discriminative Decisiveness**: It definitively proves whether the $0.06217$ COM exceedance ($1.2\%$ above budget) is a temporal phase artifact from the $50\%$ $dt$ mismatch during impact.

### Explicit Guards
- **No Solver Launch**: Request template registered only; no solver execution outside Root strict dispatcher.
- **No Repeat on F5**: Guarding against third samewallgap repeat on F5.
- **Root Q-N Status**: Remains strictly 0/336.
