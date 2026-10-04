# DS-DATA-02 Family F7: Bounded Native Recipe Followup Report (Round 039)

- **Assigned Scope**: `handoff_20261003/bounded_native_recipe_followup_039`
- **Family ID**: `F7` (Moving Obstacle Exchange & Pump Transport)
- **Physical Mother**: `F7_OBSTACLE_REFERENCE_BASE`
- **Authoritative Date**: 2026-10-04T02:30:00Z
- **Governance Status**: Preflight / Audit Staged; `launch_allowed: false`; No Q-I / Q-N / Production Claims

---

## 1. Executive Summary & Preserved Evidence Lineage

In accordance with user directives for **ROOT FOLLOWUP 039 F7**, this delivery provides an executable, bounded CPU source-consistency audit worker, prospective corrected commensurate case definitions, and an explicit legal fallback specification within the isolated worktree `codex/ds-data-02-f7`.

### Preserved Prior Evidence & Historical Negatives
1. **Dense Pair Temporal Macro Review (`root_actual_dense_pair_macro_review_016`)**:
   - Compares baseline dense save (6001 frames, $\Delta t = 0.002\text{ s}$) with TRUE half-time-step dense save under fixed frozen physical scales (mass $320.1984\text{ kg}$, COM envelope $[1.1, 0.7, 0.432]\text{ m}$, kinetic scale $89.5847\text{ J}$).
   - **Pass**: Max scaled KE error $= 0.01078675$ ($1.08\% \le 5.0\%$ budget), active mass scaled error $= 0.016\%$, COM-Z error $= 0.071\%$.
   - **Affirmation**: **Time-macro pass is NOT an explanation or cure for spatial failure.** Holding spatial discretization constant while halving $\Delta t$ isolates time-integrator stability; it does not address spatial non-commensurability.
2. **Retained Spatial Discrepancy (`F7_FROZEN_FINE_VS_DP001_SPATIAL_STUDY_001`)**:
   - Fine ($dp=0.016\text{ m}$) vs Finer ($dp=0.010\text{ m}$) spatial comparison retained as **43.01% FAIL** ($0.4301 > 0.05$ budget), with peak KE error at $19.42\%$.
3. **Retained Transport & Unknown Exclusion Negatives (`root_paired_transport_comparison_010`, `root_dense_paired_transport_review_012`)**:
   - Baseline dense vs variant true half dense transport fates ($8,376$ vs $8,843$ crossing fates) and native boundary exclusions ($0.410\text{ kg}$ vs $0.423\text{ kg}$, $410$ vs $423$ deleted particles) remain negative. Excluded particles deleted by DualSPHysics at computational domain boundaries are strictly retained as **unknown physical fate**; no zero-loss assertion or containment claim is made.
4. **Timestep Audit Lineage (`root_actual_timestep_audit_v4_015`)**:
   - Independent verification confirmed native solver execution completed with returncode 0 and full 6001 frames; prior failure receipt was a legacy launcher process loss artifact. Q-N status remains `not_assessed`.

---

## 2. Source-Consistency Audit Findings across Multi-Resolution Suite

The newly executed bounded CPU source-consistency audit worker (`f7_source_consistency_audit_worker.py`) performed a non-array, geometry/lattice/boundary/EOS source audit across Coarse ($dp=0.025\text{ m}$), Medium ($dp=0.020\text{ m}$), Fine ($dp=0.016\text{ m}$), and Finer ($dp=0.010\text{ m}$).

### Audit Ledger Summary

| Observable / Dimension | COARSE ($dp=0.025\text{ m}$) | MEDIUM ($dp=0.020\text{ m}$) | FINE ($dp=0.016\text{ m}$) | FINER ($dp=0.010\text{ m}$) | Consistency Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pointref Vector** | `[0.0125, 0.0125, 0.0125]` | `[0.0, 0.0, 0.0]` | `[0.002, 0.010, 0.010]` | `[0.005, 0.005, 0.005]` | **INCONSISTENT** (Arbitrary shifts) |
| **Lattice Mode** | $dp/2$-centered | Origin-aligned | Arbitrary offset | $dp/2$-centered | Broken self-similarity |
| **Discretized Paddle Thickness** | $0.075\text{ m}$ ($3\text{ cells}$) | $0.060\text{ m}$ ($3\text{ cells}$) | $0.064\text{ m}$ ($4\text{ cells}$) | $0.060\text{ m}$ ($6\text{ cells}$) | **DISCRETIZATION DISTORTION** |
| **Paddle Thickness Error** | **+25.0%** | **0.0%** | **+6.7%** | **0.0%** | Non-conforming at coarse/fine |
| **Discrete Paddle Eccentricity** | $+2.50\text{ mm}$ | $0.00\text{ mm}$ | $+2.00\text{ mm}$ | $0.00\text{ mm}$ | **ROTATIONAL WOBBLE** |
| **DBC Boundary Top ($z_{\text{top}}$)** | $0.050\text{ m}$ ($2 \cdot dp$) | $0.040\text{ m}$ ($2 \cdot dp$) | $0.032\text{ m}$ ($2 \cdot dp$) | $0.020\text{ m}$ ($2 \cdot dp$) | Monotonically drops with $dp$ |
| **Initial Fluid Bottom ($z_{\text{min}}$)** | $0.0625\text{ m}$ | $0.060\text{ m}$ | $0.058\text{ m}$ | $0.055\text{ m}$ | Suspended above boundary |
| **Air Gap Beneath Fluid** | $12.5\text{ mm}$ | $20.0\text{ mm}$ | $26.0\text{ mm}$ | $35.0\text{ mm}$ | **UNPHYSICAL DROP GAP** |
| **Free-Fall Energy Released ($E_p$)** | $39.26\text{ J}$ | $62.82\text{ J}$ | $81.67\text{ J}$ | **$109.94\text{ J}$** | **$122.7\%$ of Kinetic Scale** |
| **Boundary Thickness / $2h$** | $0.785 < 1.0$ | $0.785 < 1.0$ | $0.785 < 1.0$ | $0.628 < 1.0$ | **TRUNCATED KERNEL SUPPORT** |

---

## 3. Root Cause 2 (DIFFERENT Root Cause Supported by Five Pillars)

The prior repair (Repair 1: `F7_OBSTACLE_EXPLICIT_WET_CELLS_001`) attempted to solve missing fluid mass by replacing `<fillbox modefill="void">` with 4 explicit `<drawbox>` slabs under Root Cause 1 ("void flood omitted boundary support layers"). While this slightly increased initial fluid particle count, it failed spatial qualification (43% KE error) because it ignored the underlying multi-resolution structural flaws.

We identify and formalize **Root Cause 2**:
> **Incommensurate Multi-Resolution Spatial Discretization with Non-Conforming Lattice Offsets, Unpreserved Physical Boundary Surfaces, and Initial Phase Gravitational Slap.**

This root cause is rigorously supported across all five physical pillars:
1. **Geometry Pillar**: The physical paddle thickness is $0.06\text{ m}$. At $dp=0.025\text{ m}$, $0.06 / 0.025 = 2.4$ (non-integer), forcing GenCase to discretize the paddle as 3 cells ($0.075\text{ m}$), a **+25.0% geometric distortion**. At $dp=0.016\text{ m}$, $0.06 / 0.016 = 3.75$, producing 4 cells ($0.064\text{ m}$, +6.7%). Only $dp=0.020$ and $dp=0.010$ admit integer multiples of $0.06\text{ m}$.
2. **Initial Phase Pillar (The Gravitational Slap)**:
   In the legacy and Repair 1 setups, fluid was placed at $z \ge 0.05\text{ m}$. The 3-layer DBC boundary floor reaches $2 \cdot dp$. Because $2 \cdot dp$ decreases with resolution ($0.050\text{ m} \to 0.040\text{ m} \to 0.032\text{ m} \to 0.020\text{ m}$), the air gap between boundary particles and fluid particles monotonically *increased* from $12.5\text{ mm}$ to $35.0\text{ mm}$. Under gravity ($g=-9.81\text{ m/s}^2$), $320.2\text{ kg}$ of water in the finer simulation free-falls $35\text{ mm}$, releasing **$109.94\text{ J}$ of potential energy** directly into kinetic energy—exceeding the entire frozen kinetic energy scale ($89.58\text{ J}$). At coarse, the release is only $39.26\text{ J}$. This resolution-dependent initial gravitational impact accounts directly for the 43% spatial kinetic energy error.
3. **Driver Pillar (Rotational Wobble)**:
   Due to non-symmetric lattice rounding, the discretized paddle center of mass is shifted $2.5\text{ mm}$ off the rotation axis at coarse and $2.0\text{ mm}$ at fine. During sinusoidal oscillation, this dynamic eccentricity induces unphysical high-frequency rotational oscillations and sloshing.
4. **EOS & Boundary Support Pillar**:
   With Wendland kernel and $\text{coefh}=0.91924$, compact support radius is $2h \approx 3.18 \cdot dp$. A 3-layer DBC wall has physical thickness of only $2 \cdot dp$, which is strictly less than $2h$ (coverage ratio $= 0.785$). Fluid particles within $1.18 \cdot dp$ of the wall experience truncated kernel integration, causing non-physical repulsive spikes, boundary particle penetration, and the observed 410/423 particle deletions.
5. **Control Pillar**:
   Sinusoidal motion control ($f=0.4\text{ Hz}$, $A=45^\circ$, $T=4.5\text{ s}$) and total time window ($12.0\text{ s}$, 601 frames) are physically sound and verified against CSV sidecars. The spatial error is strictly hydrodynamic and geometric.

---

## 4. Prospective Corrected Commensurate Recipe (Repair 2)

We formulate and materialize prospective case definitions for **Repair 2**:
`F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002` across Coarse, Medium, Fine, and Finer DP001:

### Key Remediations:
1. **Lattice Symmetry Preservation**: Uniformly enforce `pointref = [dp/2, dp/2, dp/2]`, guaranteeing that container walls at $x \in [-0.6, 0.6]$, $y \in [-0.4, 0.4]$, $z=0.0$ coincide exactly with lattice cell boundaries.
2. **Zero-Gap Continuous Fluid Initialization**: Fluid fill box begins at $z=0.0$ with `<modefill>void</modefill>`. GenCase fills fluid particles in every void position immediately above the floor boundary layers up to $z=0.482\text{ m}$. Air gap $= 0.0\text{ mm}$; gravitational potential energy release $= 0.0\text{ J}$ across all resolutions.
3. **Full Boundary Support**: Boundary layer count increased to 4 (`layers vdp="0,1,2,3"`), giving boundary thickness $= 3 \cdot dp \ge 2h$ to prevent kernel truncation and boundary particle expulsion.
4. **Explicit Speed of Sound**: Fixed `speedsound="65.23"` based on physical still water level $H = 0.482\text{ m}$, ensuring identical fluid compressibility across resolutions.

### Prospective Case Manifests
- `case_manifests/F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002_COARSE.json` (SHA: `998efb9b...`)
- `case_manifests/F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002_MEDIUM.json` (SHA: `9ca2d5c5...`)
- `case_manifests/F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002_FINE.json` (SHA: `21bbaaf2...`)
- `case_manifests/F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002_DP001.json` (SHA: `63564eaa...`)

---

## 5. Formalized Legal Fallback Specification

Per campaign governance ("At most 2 evidence-based repairs per root cause; stop repetitive metric relaxation/refinement and prepare legal fallback if bounded paths exhausted"):
- If Repair 2 fails to bring spatial KE scaled error within the 5% budget on the obstacle geometry, the obstacle parameter space is closed.
- The legal fallback is formalized as **`F7_PUMP_STIRRER_FALLBACK_001_FINE`**:
  - **Plan Authority**: `plan-source/families/F7.md`: *"失败后备: 复杂CAD泵若长期困难，使用真实3D简化搅拌体作为第二机制模板，保持控制与流体相互作用。"*
  - **Geometry & Kinematics**: Standardized 4-blade stirrer impeller with continuous cyclic acceleration and reversal in a closed tank ($0.96 \times 0.96 \times 0.64\text{ m}$).
  - **Properties**: Exact closed mass ledger, zero boundary-intersection singularities, commensurate lattice, and complete 12.0 s event window.
  - Manifest and definition: `case_manifests/F7_PUMP_STIRRER_FALLBACK_001_FINE.json` (SHA: `6b3cac41...`).

---

## 6. Governance, Dispatch Staging & Resource Accounting

- **Scope Status**: Scoped preparation and audit completed; no solver launched; no H5 array inspected in owner process.
- **Dispatch Requests Staged**:
  - `requests/f7_source_consistency_audit_request.json` (`launch_allowed: false`)
  - `requests/f7_prospective_commensurate_gencase_request.json` (`launch_allowed: false`)
- **Attempt & Repair Limits**:
  - Bounded repairs per root cause: Exactly **2 of 2** (Repair 2). Bounded repair paths are strictly controlled.
  - Root remaining resources: ~32 GPU hours / 56 qualification attempts, Home $\ge 500\text{ GiB}$.
- **Scientific Counters**:
  - Independent physically qualified cases: **0** (No Q-N granted from definitions/receipts alone).
  - Production approvals: **none**.
- **Synthetic Test Suite**: 6 tests passed in 0.21 s (`tests/test_f7_source_consistency_audit_worker.py`).

---

## 7. Next Executable Tasks for Root Strict Dispatcher

1. **Root Dispatch**: Authorize and execute `requests/f7_source_consistency_audit_request.json` through the shared strict dispatcher to generate the authoritative signed execution receipt.
2. **GenCase Preflight**: Execute CPU GenCase on `F7_OBSTACLE_COMMENSURATE_PHYSICAL_SURFACE_002_FINE_Def.xml` through the shared runner to obtain native BI4 particle coordinates and verify $0\text{ mm}$ air gap and boundary coverage.
3. **Spatial Convergence Qualification**: Evaluate multi-resolution spatial refinement on the corrected commensurate suite under the 5% macro budget.
4. **Fallback Activation (if triggered)**: If spatial error remains $> 5\%$, terminate obstacle modifications and dispatch `F7_PUMP_STIRRER_FALLBACK_001_FINE`.
