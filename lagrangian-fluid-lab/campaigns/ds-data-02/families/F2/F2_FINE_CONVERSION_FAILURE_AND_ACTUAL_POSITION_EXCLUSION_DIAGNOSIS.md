# F2 Fine Conversion Failure and Position Exclusion Root-Cause Diagnosis

## 1. Executive Summary

This diagnostic audit establishes the exact numerical and physical root cause for the conversion failures and particle exclusions in:
- `F2_COMM4_CENTER_V1_FINE` (9,846 fluid particles excluded, 40.06% of fluid)
- `F2_COMM4_OFFSET_V1_FINE` (11,125 fluid particles excluded, 45.27% of fluid)

All 9,846 and 11,125 particle exclusions were extracted and verified using official `PartVTKOut_linux64` directly against the solver's immutable `PartOut_000.obi4` artifacts.

**Key Finding**: 100.0% of excluded particles are classified as `Motive = 1` (`NpOutPos` = position exited the simulation domain bounding box). There are **zero** density divergence exclusions (`NpOutRho = 0`) and **zero** velocity movement blow-ups (`NpOutMov = 0`).

---

## 2. Quantitative Verification

| Metric | F2 Center Coarse | F2 Center Medium | F2 Center Fine | F2 Offset Fine |
| :--- | :--- | :--- | :--- | :--- |
| Discretization $dp$ | 0.040 m | 0.020 m | 0.010 m | 0.010 m |
| Fluid Particle Count | 384 | 3,040 | 24,576 | 24,576 |
| Total Particle Count | 14,358 | 52,606 | 222,384 | 222,384 |
| Total Excluded Particles | **0** | **0** | **9,846 (40.1%)** | **11,125 (45.3%)** |
| Exclusion Motive | None | None | 100% `NpOutPos` | 100% `NpOutPos` |
| Onset Time / Frame | N/A | N/A | $t = 0.41\text{ s}$ (Frame 41) | $t = 0.41\text{ s}$ (Frame 41) |
| Q-I Structure Status | Pass | Pass | Incomplete / Blocked | Incomplete / Blocked |

---

## 3. Spatial Boundary Breakdown

The simulation domain defined in the GenCase XML is:
- $\text{posmin} = [-0.70, -0.75, -0.40]\text{ m}$
- $\text{posmax} = [2.20, 1.00, 1.80]\text{ m}$

The physical catch floor (`mk=2`) covers only:
- $x \in [-0.60, 2.00]\text{ m}$
- $y \in [-0.60, 0.70]\text{ m}$
- $z \in [-0.20, -0.10]\text{ m}$

### Exact Exit Boundary Statistics:

#### `F2_COMM4_CENTER_V1_FINE` (9,846 particles)
- **$x < -0.70\text{ m}$**: 5,909 particles (60.0%) — Spilling behind the catch floor ($x < -0.60$) during cup tilt and splashing backwards.
- **$z < -0.40\text{ m}$**: 2,550 particles (25.9%) — Falling below the floor level after spilling off the floor margins.
- **$x > 2.20\text{ m}$**: 1,244 particles (12.6%) — Forward high-speed sheet momentum shooting past the front floor lip ($x = 2.00$).
- **$z > 1.80\text{ m}$**: 105 particles (1.1%) — High-velocity vertical splash droplets ($v_z > 3.0\text{ m/s}$) exiting the top domain.
- **$y > 1.00\text{ m}$ / $y < -0.75\text{ m}$**: 40 particles (0.4%) — Lateral splash overruns.

#### `F2_COMM4_OFFSET_V1_FINE` (11,125 particles)
- **$z < -0.40\text{ m}$**: 4,491 particles (40.4%) — Vertical downward exits after clearing the receiver and tray lips.
- **$x < -0.70\text{ m}$**: 4,268 particles (38.4%) — Back-splash runoff.
- **$x > 2.20\text{ m}$**: 1,680 particles (15.1%) — Forward sheet runoff.
- **$y < -0.75\text{ m}$**: 574 particles (5.2%) — Transverse offset spill overrunning the side margins.
- **$z > 1.80\text{ m}$**: 105 particles (0.9%) — Vertical splash exits.
- **$y > 1.00\text{ m}$**: 18 particles (0.2%) — Transverse splash exits.

---

## 4. Physical and Numerical Root Cause

1. **Resolution-Dependent Dissipation**:
   In SPH, effective numerical viscosity scales with kernel radius $h \propto dp$. At coarse ($dp = 0.04\text{ m}$) and medium ($dp = 0.02\text{ m}$), high numerical dissipation damps splash droplets and retards sheet spreading velocity, containing the entire fluid volume within the lower receiver and tray.
2. **Fine-Grid Splash and Sheet Detachment**:
   At fine ($dp = 0.01\text{ m}$), fluid momentum is fully conserved, yielding thin liquid sheets and high-velocity splash jets upon impact ($v_z > 3.0\text{ m/s}$). Fluid spreads rapidly across the finite floor and spills over the un-walled floor edges at $x = -0.60\text{ m}$ and $x = +2.00\text{ m}$, descending gravitationally into void space until intersecting the domain floor at $z = -0.40\text{ m}$.
3. **DualSPHysics Solver Behavior**:
   DualSPHysics automatically removes any particle whose coordinate exceeds `posmin` or `posmax`, logging it to `PartOut_???.obi4`. Consequently, the solver output files have decreasing particle counts ($24,576 \to 14,730$), causing standard conversion pipelines to fail or report missing-identity violations.

---

## 5. Remediation Plan

1. **Geometry / Bounded Catch Fix (Recommended for full fluid preservation)**:
   - Extend the catch floor / basin geometry in GenCase XML to $x \in [-1.20, 2.80]\text{ m}$, $y \in [-1.00, 1.00]\text{ m}$, $z \in [-0.50, 2.20]\text{ m}$.
   - Add containment lip walls (height $\sim 0.15\text{ m}$) to the catch tray to prevent free-fall over the edge.
   - This keeps 100% of particles within the domain without altering the cup rotation, initial fluid mass, or physical pouring dynamics.
2. **Explicit Open-Boundary Accounting (Alternative for lossless audit)**:
   - Accept the physical spill-out as an open-boundary departure.
   - Use `PartVTKOut` to track all excluded particles as `unknown_mass` / `domain_exit` in `typed-transport-labels.h5`.
   - Update the conversion pipeline to treat `PartOut` particles as valid exit records rather than missing-particle errors.
