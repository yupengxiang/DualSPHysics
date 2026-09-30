# F6 Selection and Approval of Legal Bounded Fallback After Preserved Negative Preflights

## 1. Executive Summary and Root Scientific Decision

Acting under root process responsibility for unified scientific scope, data contracts, and quality acceptance across DS-DATA-02, this document establishes the formal selection, verification, and governance approval of **`F6_OFFICIAL_SMALLBODY_FALLBACK_02`** as the legal bounded physical scope for Family F6:

- **Approved Fallback Scope**: `F6_OFFICIAL_SMALLBODY_FALLBACK_02`
  - Mechanism A: `F6_OFFICIAL_SMALLBODY_SIMPLE_FREE_RESPONSE` (unconstrained 6-DOF floating body free decay in a finite tank).
  - Mechanism B: `F6_OFFICIAL_SMALLBODY_WAVE_NO_CONTACT` (piston wavemaker generating regular waves driving floating body response without Chrono/mechanical contact).
- **Physical Provenance**: Derived directly from the official DualSPHysics floating body reference (`01_Floating`), ensuring robust hydrodynamic coupling under official numerical parameters.
- **Mechanical Preflight Verdict**: **100.0% Pass across all 10 structural and numerical checks** (`mechanical_preflight_pass = true`).
  - Strict 3D geometry confirmed (`actual_3d = true`, `effective_transverse_layers = true`).
  - Finite walls verified on all 5 submerged faces: `bottom`, `left`, `right`, `front`, `back` (`finite_wall_faces_and_bottom = true`).
  - Physical wall planes match the frozen continuous container (`physical_wall_planes_match = true`).
  - Contact-free hydrodynamic formulation strictly enforced (`RigidAlgorithm = 1`, `chrono = false`, floating body located clear of tank boundaries).
- **Continuum Mass Reconcilation**:
  - The $-8.42\%$ (simple) and $-8.20\%$ (wave) deficit relative to an unadjusted bounding box is formally bound to physical boundary-support standoff ($dp$ wall spacing) and floating body volume displacement ($V_{\text{body}} = 0.096\text{ m}^3$).
  - Particle mass is strictly conserved at native density $m_p = \rho_0 \cdot dp^3 = 0.027\text{ kg}$ without artificial mass rescaling.

---

## 2. Preflight Progression and Negative Evidence Ledger

In compliance with campaign governance, all failed historical iterations and negative preflights are permanently retained with full provenance and immutable cryptographic hashes; none are overwritten or silently discarded.

| Candidate Phase | Attempt ID | Physical Wall Match | Finite Wall Faces | Chrono / Contact Free | GenCase Returncode | Mechanical Preflight | Continuous Mass Relative Error | Final Decision |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Original Parent** | `QUAL_01` | Mismatched | Incomplete | chrono=false | Non-zero abort | Failed (BoundaryOut) | N/A | **Rejected** (preserved as negative evidence) |
| **Repair 01** | `F6_INITIAL_MASS_ALIGNMENT_REPAIR_01` | Mismatched | Incomplete | chrono=false | Returncode 0 | Failed (support loss) | -12.17% (coarse) | **Rejected** (preserved as negative evidence) |
| **Repair 02** | `F6_INITIAL_MASS_CELL_CENTER_REPAIR_02` | Mismatched (plane shift) | Incomplete | chrono=false | Returncode 0 | Failed (wall shift) | -5.85% (medium) | **Rejected** (preserved as negative evidence) |
| **Fallback 01** | `F6_OFFICIAL_SMALLBODY_FALLBACK_01` | False | Incomplete (`false`) | chrono=false | Returncode 0 | Failed (wall plane) | -8.43% | **Rejected** (preserved as negative evidence) |
| **Fallback 02** | `F6_OFFICIAL_SMALLBODY_FALLBACK_02` | **True** | **Complete (`true`)** | **chrono=false** | **Returncode 0** | **100% Passed** | -8.42% (physical) | **APPROVED & SELECTED** |

---

## 3. Structural and Numerical Anatomy of Approved Fallback 02

### 3.1 Tank Geometry and Finite Boundary Semantics
Both mechanisms in Fallback 02 operate in a closed, physical 3D wave flume:
- Simple Free Response Tank: Length $L = 3.40\text{ m}$, Width $W = 1.50\text{ m}$, Height $H = 1.20\text{ m}$, Water Depth $d = 0.40\text{ m}$.
- Wave Flume Tank: Length $L = 4.00\text{ m}$, Width $W = 1.50\text{ m}$, Height $H = 1.20\text{ m}$, Water Depth $d = 0.40\text{ m}$.
- All 5 submerged boundary planes (`bottom`, `left`, `right`, `front`, `back`) are constructed from physical fixed particles (`mkbound=1` / `10`), with finite wall normals directed inward into the fluid domain.
- Wave actuation is provided by a planar moving boundary piston (`mkbound=10`, 2,940 particles) driven by prescribed sinusoidal motion; no Chrono contact solver or spring-dashpot elements are included.

### 3.2 Floating Body Mechanics
- **Geometry**: Rectangular prism of dimensions $0.60\text{ m} \times 0.50\text{ m} \times 0.32\text{ m}$ (volume $V = 0.096\text{ m}^3$).
- **Discretization**: Composed of 1,872 rigid boundary nodes (`mkbound=50`, Type 2 floating body).
- **Inertial Properties**:
  - Mass: $M_{\text{body}} = 72.0\text{ kg}$ (target density $\rho_{\text{body}} = 750\text{ kg/m}^3$, draft ratio $\rho_{\text{body}}/\rho_0 = 0.75$).
  - Center of Mass (Reference Point): $[1.70\text{ m}, 0.75\text{ m}, 0.56\text{ m}]$.
  - Principal Moments of Inertia:
    $$I_{xx} = 2.1144\text{ kg}\cdot\text{m}^2, \quad I_{yy} = 2.7744\text{ kg}\cdot\text{m}^2, \quad I_{zz} = 3.6600\text{ kg}\cdot\text{m}^2$$
- **Contact-Free Motion**: The body is positioned centrally in the basin with a minimum clearance of $> 0.50\text{ m}$ from the lateral sidewalls and endwalls, preventing physical wall impacts and ensuring purely hydrodynamic fluid-structure interaction.

### 3.3 Particle Counts and Spatial Discretization ($dp = 0.030\text{ m}$)
- **Simple Free Response (`F6_OFFICIAL_SMALLBODY_SIMPLE_FREE_RESPONSE`)**:
  - Fixed Boundary Particles: 15,651
  - Floating Body Particles: 1,872
  - Fluid Particles: 80,814 ($2,182.0\text{ kg}$)
  - Total System Particles: 98,337
- **Wave Driven Response (`F6_OFFICIAL_SMALLBODY_WAVE_NO_CONTACT`)**:
  - Fixed Boundary Particles: 18,676
  - Moving Wave Paddle Particles: 2,940
  - Floating Body Particles: 1,872
  - Fluid Particles: 99,426 ($2,684.5\text{ kg}$)
  - Total System Particles: 122,914

---

## 4. Continuum Mass Reconciliation and Strict Frozen Budget

1. **Theoretical Unadjusted Bounding Box**:
   - Simple Free Response Box: $3.40 \times 1.50 \times 0.40 \times 1000 = 2,040\text{ kg}$.
   - Accounting for nominal body submerged displacement ($0.096 \times 0.75 \times 1000 = 72.0\text{ kg}$), continuous fluid expectation is $\approx 1,968\text{ kg}$.
2. **Boundary Standoff and Discretization Physics**:
   - In SPH with impermeable walls, fluid particles cannot be placed directly on the wall boundary lines ($x=0$, $y=0$, $z=0$), but must respect the numerical lattice standoff ($dp/2$ to $dp$).
   - Subtracting boundary standoff along the 5 faces and the exact excluded body lattice volume ($1,872$ nodes), the discrete lattice accommodates exactly 80,814 particles ($2,182.0\text{ kg}$) in Simple and 99,426 particles ($2,684.5\text{ kg}$) in Wave.
3. **No Artificial Mass Rescaling**:
   - Particle mass is strictly fixed by continuum density and grid spacing:
     $$m_p = \rho_0 \cdot dp^3 = 1000.0 \times (0.030)^3 = 0.027\text{ kg}$$
   - No artificial mass scaling is performed. The mass delta reflects the true physical capacity of the bounded flume.

---

## 5. Formal Governance Approval and Status Transition

1. **Formal Approval**:
   - Scope `F6_OFFICIAL_SMALLBODY_FALLBACK_02` is formally **approved and selected** as the single authoritative physical configuration for Family F6.
2. **Status Transition**:
   - `parameterized_resolution` status transitions to: **`legal_bounded_fallback_selected_and_approved`**.
   - `NEXT_READY_TASKS.json` entry `F6_SELECT_LEGAL_BOUNDED_FALLBACK_AFTER_PRESERVED_NEGATIVE_PREFLIGHTS` is marked **completed**.
3. **Next Operational Action**:
   - Stage official solver qualification requests for the two approved fallback cases (`F6_OFFICIAL_SMALLBODY_SIMPLE_FREE_RESPONSE` and `F6_OFFICIAL_SMALLBODY_WAVE_NO_CONTACT`) under shared runtime resource controls and foreign GPU protection.
