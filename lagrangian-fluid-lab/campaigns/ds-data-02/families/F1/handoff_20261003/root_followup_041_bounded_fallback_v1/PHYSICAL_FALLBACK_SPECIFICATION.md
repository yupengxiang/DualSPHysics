# Family F1: Compact Physically Meaningful Gravity-Release Transport Fallback Specification

- **Campaign**: DS-DATA-02
- **Family**: F1
- **Scope**: `handoff_20261003/root_followup_041_bounded_fallback_v1`
- **Specification Version**: v1.0
- **Status**: Prospective Physical Fallback Specification Ready for Root Review

---

## 1. Physical Principle & Rationale of Controlled Forcing

The primary objective of this prospective fallback is to eliminate the chaotic stagnation-line trajectory divergence and turbulent spray fragmentation that prevented transport convergence in the original violent dam-break setup, while **strictly retaining true 3D fluid dynamics, asymmetric bifurcation, and complete event lifecycle mechanics**.

### 1.1 The Controlled Forcing Transition
In both mechanisms of Family F1, the initial fluid depth $H_0$ is reduced to a controlled moderate depth:
1. **Kinetic Energy Suppression**: Kinetic energy scales quadratically with initial fluid depth ($E_k \sim M g H_0 \propto H_0^2$). Reducing $H_0$ from $0.30\text{ m}$ to $0.15\text{ m}$ (in the eccentric obstacle case) cuts peak kinetic energy by $75\%$, lowering maximum impact velocity from $3.43\text{ m/s}$ to $2.43\text{ m/s}$.
2. **Stable Stagnation Line & Coherent Bifurcation**: At reduced forcing, the surge front advances as a coherent gravity wave (moderate Froude number). The upstream stagnation line on the obstacle/separator is laminar and structurally stable. Small numerical perturbations (e.g. halving $\Delta t$ or refining $dp$) do not trigger chaotic path divergence across the bifurcation boundary, stabilizing particle destination fates.
3. **Prevention of Uncontrolled Overtopping and Loss**:
   - In `F1_FALLBACK_ECC_V1`, maximum wave runup elevation $z_{\text{max}} \approx 0.30\text{ m}$ remains well below the obstacle top at $z = 0.45\text{ m}$. Zero fluid overtops the obstacle; $100\%$ of fluid is channeled laterally through the asymmetric conduits.
   - In `F1_FALLBACK_DUAL_V1`, the downstream splash jet height ($z \le 0.60\text{ m}$) remains fully contained within the $0.80\text{ m}$ tall container, eliminating the $N_{\text{out}}$ droplet loss over $z > 1.0\text{ m}$ observed in historical runs.
4. **New Physical Case Status**:
   This fallback constitutes an independent physical case definition with dedicated geometry hashes, initial state vectors, and error budgets. **It does not transfer old Q-N grants or inherit historical qualifications.**

---

## 2. Requirement for True 3D Dynamics & Non-Zero Transverse Velocity ($v_y \ne 0$)

The fallback preserves true three-dimensional hydrodynamics:
- **Lateral Expansion**: Fluid released from the reservoir undergoes immediate lateral 3D expansion and redirection upon encountering the eccentric obstacle or asymmetric channel divider.
- **Asymmetric Transverse Diversion**: In the eccentric obstacle case, fluid in $y \in [0.24, 0.30\text{ m}]$ develops negative transverse velocity ($v_y < 0$) toward the lower channel ($w = 0.24\text{ m}$), while fluid in $y \in [0.30, 0.36\text{ m}]$ develops positive transverse velocity ($v_y > 0$) toward the upper channel ($w = 0.31\text{ m}$).
- **Evidence Requirement**: Downstream data verification requires explicit extraction of $|v_y|_{\text{max}} > 0.4\text{ m/s}$ and $3\text{D}$ velocity profiles across channel cross-sections. Simulations showing degenerate 1D or quasi-2D behavior ($v_y \approx 0$) are rejected.

---

## 3. The Legal Fallback Pair: Detailed Geometric & Physical Matrix

Family F1 comprises exactly **one legal fallback pair** spanning the two canonical mechanisms:

### 3.1 Background A: `F1_FALLBACK_ECC_V1` (Eccentric Obstacle Transport Fallback)
- **Mechanism ID**: `eccentric_obstacle`
- **Physical Case ID**: `F1_FALLBACK_ECC_V1`
- **Continuous Geometry**:
  - **Tank Enclosure**: $x \in [0.00, 1.60\text{ m}]$, $y \in [0.00, 0.67\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$. Open top.
  - **Eccentric Solid Obstacle**: $x \in [0.90, 1.02\text{ m}]$ (length $0.12\text{ m}$), $y \in [0.24, 0.36\text{ m}]$ (width $0.12\text{ m}$), $z \in [0.00, 0.45\text{ m}]$ (height $0.45\text{ m}$).
    - Lower bypass channel: $y \in [0.00, 0.24\text{ m}]$ (width $0.24\text{ m}$).
    - Upper bypass channel: $y \in [0.36, 0.67\text{ m}]$ (width $0.31\text{ m}$).
    - Asymmetry width ratio: $0.24 / 0.31 \approx 77.4\%$.
  - **Fluid Reservoir**: $x \in [0.00, 0.40\text{ m}]$ (length $0.40\text{ m}$), $y \in [0.00, 0.67\text{ m}]$ (width $0.67\text{ m}$), $z \in [0.00, 0.15\text{ m}]$ (controlled depth $H_0 = 0.15\text{ m}$).
  - **Theoretical Fluid Volume**: $V_0 = 0.40 \times 0.67 \times 0.15 = 0.0402\text{ m}^3$.
  - **Theoretical Fluid Mass**: $M_0 = \rho_0 V_0 = 1000 \times 0.0402 = 40.200\text{ kg}$.
  - **Event Window**: $T_{\text{max}} = 1.60\text{ s}$.

- **Commensurate 3-Ladder**:
  - **Coarse** ($dp = 0.010\text{ m}$): Counts $(40, 67, 15) \to 40,200$ fluid particles ($M = 40.200\text{ kg}$).
  - **Medium** ($dp = 0.005\text{ m}$): Counts $(80, 134, 30) \to 321,600$ fluid particles ($M = 40.200\text{ kg}$).
  - **Fine** ($dp = 0.0033333333333333335\text{ m}$, or $1/300\text{ m}$): Counts $(120, 201, 45) \to 1,085,400$ fluid particles ($M = 40.200\text{ kg}$).
  - **Mass Invariance**: $M_{\text{coarse}} = M_{\text{medium}} = M_{\text{fine}} = 40.200\text{ kg}$ exactly ($|\Delta M| / M_0 = 0$).

---

### 3.2 Background B: `F1_FALLBACK_DUAL_V1` (Asymmetric Dual-Channel Transport Fallback)
- **Mechanism ID**: `asymmetric_dual_channel`
- **Physical Case ID**: `F1_FALLBACK_DUAL_V1`
- **Continuous Geometry**:
  - **Tank Enclosure**: $x \in [0.00, 3.20\text{ m}]$, $y \in [0.00, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$. Open top.
  - **Longitudinal Separator Block**: $x \in [1.20, 2.00\text{ m}]$ (length $0.80\text{ m}$), $y \in [0.34, 0.40\text{ m}]$ (thickness $0.06\text{ m}$), $z \in [0.00, 0.70\text{ m}]$ (height $0.70\text{ m}$).
    - Lower channel conduit: $y \in [0.00, 0.34\text{ m}]$ (width $0.34\text{ m}$).
    - Upper channel conduit: $y \in [0.40, 1.00\text{ m}]$ (width $0.60\text{ m}$).
    - Asymmetric width fraction: $0.34 / (0.34 + 0.60) = 0.34 / 0.94 \approx 36.17\%$.
  - **Fluid Reservoir**: $x \in [2.20, 3.20\text{ m}]$ (length $1.00\text{ m}$), $y \in [0.00, 1.00\text{ m}]$ (width $1.00\text{ m}$), $z \in [0.00, 0.30\text{ m}]$ (controlled depth $H_0 = 0.30\text{ m}$).
  - **Theoretical Fluid Volume**: $V_0 = 1.00 \times 1.00 \times 0.30 = 0.300\text{ m}^3$.
  - **Theoretical Fluid Mass**: $M_0 = \rho_0 V_0 = 1000 \times 0.300 = 300.000\text{ kg}$.
  - **Event Window**: $T_{\text{max}} = 4.00\text{ s}$ (compact complete window covering release, passage, re-merging, wall impact, and return wave).

- **Commensurate 3-Ladder**:
  - **Coarse** ($dp = 0.020\text{ m}$): Counts $(50, 50, 15) \to 37,500$ fluid particles ($M = 300.000\text{ kg}$).
  - **Medium** ($dp = 0.010\text{ m}$): Counts $(100, 100, 30) \to 300,000$ fluid particles ($M = 300.000\text{ kg}$).
  - **Fine** ($dp = 0.005\text{ m}$): Counts $(200, 200, 60) \to 2,400,000$ fluid particles ($M = 300.000\text{ kg}$).
  - **Mass Invariance**: $M_{\text{coarse}} = M_{\text{medium}} = M_{\text{fine}} = 300.000\text{ kg}$ exactly ($|\Delta M| / M_0 = 0$).

---

## 4. Proven Body Wall Coverage & Lattice Specifications

The fallback strictly adheres to the proven **thick Dynamic Boundary Condition (DBC)** implementation established in `root_thick_dbc`:
1. **Lattice Alignment**:
   - `pointref` anchored at $(dp/2, dp/2, dp/2)$.
   - All fluid particles are cell-centered, exactly 1 particle per $dp^3$ cell.
   - Nearest fluid particle center is at $0.5 \cdot dp$ inside the physical fluid envelope.
2. **Three-Layer Solid Boundary Slabs**:
   - Outer tank faces (bottom, left, right, front, back) are generated as explicit solid slabs wholly outside the continuous envelope.
   - The nearest boundary row is at $0.5 \cdot dp$ outside the wall, providing full $3 \cdot dp$ support thickness ($0.5 \cdot dp$, $1.5 \cdot dp$, $2.5 \cdot dp$).
   - Obstacles and separators are generated with internal solid slabs inside their physical envelope, ensuring complete solid coverage.
3. **No Hollow Face Drawmodes**:
   - GenCase commands specify `<setshapemode>dp | actual | bound</setshapemode>` and `<setdrawmode mode="full" />`.
   - Silent hollow boundary drawmodes (`mode="face"`) are strictly prohibited to prevent particle penetration.

---

## 5. Canonical Destination Regions & Event Apertures

Both fallback cases define exact spatial destination partitions and first-passage planes:

### 5.1 `F1_FALLBACK_ECC_V1` Partitions
- **Canonical Destination Regions**:
  - `upstream`: $x \in [0.00, 0.90\text{ m}]$, $y \in [0.00, 0.67\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$
  - `lower_channel`: $x \in [0.90, 1.02\text{ m}]$, $y \in [0.00, 0.24\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$
  - `upper_channel`: $x \in [0.90, 1.02\text{ m}]$, $y \in [0.36, 0.67\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$
  - `downstream`: $x \in [1.02, 1.60\text{ m}]$, $y \in [0.00, 0.67\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$
- **First-Passage Event Apertures**:
  - `lower_channel_entry`: Plane $x = 0.90\text{ m}$, aperture $y \in [0.00, 0.24\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$
  - `upper_channel_entry`: Plane $x = 0.90\text{ m}$, aperture $y \in [0.36, 0.67\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$
  - `downstream_arrival`: Plane $x = 1.20\text{ m}$, aperture $y \in [0.00, 0.67\text{ m}]$, $z \in [0.00, 0.40\text{ m}]$

### 5.2 `F1_FALLBACK_DUAL_V1` Partitions
- **Canonical Destination Regions**:
  - `upstream`: $x \in [2.00, 3.20\text{ m}]$, $y \in [0.00, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
  - `lower_channel`: $x \in [1.20, 2.00\text{ m}]$, $y \in [0.00, 0.34\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
  - `upper_channel`: $x \in [1.20, 2.00\text{ m}]$, $y \in [0.40, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
  - `downstream`: $x \in [0.00, 1.20\text{ m}]$, $y \in [0.00, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
- **First-Passage Event Apertures**:
  - `lower_channel_entry`: Plane $x = 2.00\text{ m}$, aperture $y \in [0.00, 0.34\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
  - `upper_channel_entry`: Plane $x = 2.00\text{ m}$, aperture $y \in [0.40, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
  - `downstream_remerge`: Plane $x = 1.20\text{ m}$, aperture $y \in [0.00, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$
  - `downstream_arrival`: Plane $x = 0.30\text{ m}$, aperture $y \in [0.00, 1.00\text{ m}]$, $z \in [0.00, 0.80\text{ m}]$

---

## 6. Physically Scaled Prospective Error Budgets

The prospective error budgets are scaled rigorously to the new characteristic timescales:

| Mechanism | $H_0$ [m] | Characteristic Time $T = \sqrt{H_0/g}$ [s] | 2% Event Budget [s] | 20% Save Budget [s] | Control $\Delta t_{\text{ctrl}}$ [s] | Ref $\Delta t_{\text{ref}}$ [s] | Macro Budget |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `F1_FALLBACK_ECC_V1` | $0.150$ | $0.123652$ | **$0.002473$** ($2.47\text{ ms}$) | **$0.000495$** | $0.0005$ | $0.010$ | $5.0\%$ |
| `F1_FALLBACK_DUAL_V1` | $0.300$ | $0.174874$ | **$0.003497$** ($3.50\text{ ms}$) | **$0.000699$** | $0.0010$ | $0.010$ | $5.0\%$ |

No quiet frames or dropout masks are permitted. Full-window transport accounting and mass conservation apply.
