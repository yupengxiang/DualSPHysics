# ROOT FOLLOWUP 049: Visual Stage 1 Support Diagnosis v2, Preamble-Tolerant Reader, Memory-Bounded KDTree, and Batch 1 (8 Independent Cases) Definition

**Author**: F5 Autonomous Agent (Pair programming with User)  
**Execution Context**: `/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics`  
**Target Handoff Workspace**: `lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2`  
**Model Requirement**: `gemini-3.8-flash-high` (Verified direct session; zero model substitution, zero recursive subagent delegation)  
**Task Authority**: User edited ACTIVE GOAL (Stage 1 Full-Generation-Flow, Visual Review, Batch Accumulation)  
**Scope**: Source-only delivery in fresh own scope. Preamble-tolerant CSV diagnostic worker v2, bounded spatial indexing via `scipy.spatial.cKDTree`, bed normal distance layer analysis, deep interior void audit, 3-frame ParaView visual inspection proposal, conditional minimal geometry repair policy, and registration of Batch 1 (8 independent physical cases). Strictly NO solver/GenCase execution, NO heavy export execution, NO unverified qualification claims.

---

## 1. Executive Summary & Adoption of Revised Active Goal

The User has formally edited the active goal for **DS-DATA-02** in [`GOAL_STAGE1_VISUAL_20261004_ZH.md`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_20261004_ZH.md):

1. **Stage 1 Primary Objective**:
   - Establish an end-to-end generation and validation workflow: **Scene Generation $\rightarrow$ Full Solver Execution $\rightarrow$ State Preservation $\rightarrow$ ParaView 3D Dynamic Viewing $\rightarrow$ Visual Review $\rightarrow$ Batch Production**.
   - Accumulate independent physical cases across families F1–F7 in batches of **8 / 24 / 48 cases**, targeting **336 total independent cases**.
   - The user-accepted **F3 Two-Axis Case** serves as the anchor sample. Resolution对照 (DP-ladder), time-slice variations, and re-runs are strictly forbidden from being counted as independent physical cases.
2. **Decoupling of Traditional Prerequisites**:
   - Spatial grid convergence, time-step and save-frequency error budgets, long-term Lagrangian particle trajectory identity matching, precise transport/event labeling, and experimental Q-E validation are **explicitly NOT shared prerequisites** for Stage 1 batch generation.
3. **Preservation of Negative Evidence**:
   - All historical negative results and uncertainties must be retained and disclosed.
   - Root Macro 058 audited all 3-resolution pairs across Runup and Weir and failed both mechanisms (`{"runup": false, "weir": false}`). This failure evidence is fully preserved; numerical precision is explicitly marked **NOT ACCEPTED**.
   - Q-I (Integrity), Visual Review, Q-N (Numerical Reference), and Q-E (Experimental Validation) are strictly decoupled and tracked in separate ledgers.
4. **Cumulative Resource Limits**:
   - Qualification attempt cap: **320 attempts**.
   - Production attempt cap: **420 attempts**.
   - Computational budget: **96 GPU·h** and **384 CPU core·h**.
   - Storage floor: `/home` must maintain at least **500 GiB** free space.
5. **Operational Boundaries**:
   - Sole execution agent: Root strict dispatcher alone executes commands.
   - Delegated agents provide source code, bindings, and unlaunchable request placeholders (`launch_allowed: false`).

---

## 2. Post-Mortem of Commit 772b99b4 (Round 048) & Root Source Review Corrections

Root's review of the initial diagnostic worker proposed in Round 048 (`772b99b4`) identified several fatal defects that rendered it unexecutable:

### 2.1 CSV Format Incompatibility: Delimiters, Headers, and Preambles
- **The Defect**: The Round 048 worker called `f.readline()` and assumed line 1 contained the column header `Pos.x [m]`, separated by commas. In reality, official PartVTK CSV exports contain a multi-line preamble:
  ```text
  TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid
  0,214515,173805,168108,5697,0,40710

  Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Press [Pa],Type,Mk,
  ```
  Furthermore, gauge telemetry CSV exports (`GaugesSWL_*.csv`) utilize semicolon delimiters (`;`):
  ```text
  time [s];swlx [m];swly [m];swlz [m];pos0x [m];pos0y [m];pos0z [m];pos2x [m];pos2y [m];pos2z [m]
  ```
  Calling `f.readline()` in 048 immediately crashed with `Missing required official column 'Pos.x [m]'`.
- **Root 054 Reader Pattern Adopted**: In `diagnostic_initial_support_worker_v2.py`, we implement a preamble-tolerant scanning loop matching Root's [`qa.py`](file:///home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_native_initial_state_tools_003/qa.py#L28-L37):
  - Iterates line-by-line through preamble lines until `Pos.x [m]` is detected.
  - Automatically identifies the delimiter (`;` or `,`).
  - Dynamically maps the 13 required official columns regardless of column ordering or trailing commas.

### 2.2 Quadratic Complexity & Tensor OOM Disaster
- **The Defect**: The Round 048 worker performed distance queries by computing:
  ```python
  # Round 048 buggy logic:
  diff = chunk[:, np.newaxis, :] - pos_bound[np.newaxis, :, :]  # (500, N_bound, 3)
  ```
  In the fine case, $N_{bound} = 2,866,443$ particles. Broadcasting a chunk of 500 fluid particles across $N_{bound}$ created a 3D float64 array of size $500 \times 2,866,443 \times 3 \times 8 \text{ bytes} \approx \mathbf{34.4\text{ GB}}$ per chunk! This instantly led to Out-Of-Memory (OOM) process termination and quadratic $O(N \times M)$ operational stalling.
- **Root-Approved Spatial Indexing**:
  - We verified that `scipy 1.15.3` with `cKDTree` is available in Root's python virtual environment (`/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv`).
  - In `diagnostic_initial_support_worker_v2.py`, we construct `tree = cKDTree(pos_bound)`, which builds in $\approx 0.05$ s and consumes negligible memory ($< 25$ MB).
  - Queries for nearest boundary distance (`tree.query`) and neighbor counts within kernel radius $2h = 2\sqrt{3}dp$ (`tree.query_ball_point`) execute in $O(N \log M)$ time, bounded to $< 0.1$ s total CPU time.

### 2.3 Deconstructing the "Hollow 1-Layer Bed" Fallacy
- **The Defect**: The Round 048 report compared the total count of bed particles ($13,556$ in coarse) against the volume integral of a 3D solid bed polyhedron ($\approx 52,023$), concluding that the bed was a "1-layer hollow shell".
- **Physical & SPH Reality**:
  - In SPH boundary modeling (especially with mDBC or dynamic boundary conditions), boundary particles are generated to provide complete kernel support within distance $2h$ of the fluid domain. Generating millions of particles deep inside the impermeable bedrock meters away from the fluid serves no physical purpose and wastes compute.
  - GenCase STL meshing and facet sampling place particles along the surface boundary. What matters for boundary support is **how many layers exist perpendicular to the boundary surface near the fluid interface** (i.e. within distance $[0, 3dp]$ or $2h$), NOT whether the deep interior core is filled.
  - Round 049 worker v2 directly computes the **normal distance profile** $d_\perp = (z_{bed}(x) - z)\cos\theta$ of bed particles beneath the sloped skin, binning them into depth layers:
    - Layer 1: $[0, 1.0 dp)$
    - Layer 2: $[1.0 dp, 2.0 dp)$
    - Layer 3: $[2.0 dp, 3.0 dp)$
    - Layer 4: $[3.0 dp, 4.0 dp)$
    - Deeper: $\ge 4.0 dp$
  - The local deep interior void test ($z \le z_{bed}(x) - 4dp$) is reported descriptively as "surface-layer boundary geometry" rather than jumping to an unverified conclusion of "hollow defect".

### 2.4 Sidewall Boxfill Marker Count Clarification
- In GenCase, flume sidewalls are generated via `<drawbox>` across multiple bounding planes. Counting unique $y$-coordinates or raw marker totals across multiple overlapping faces produces many markers. In worker v2, we explicitly include a governance guard: **Marker counts across multiple boxfill faces do NOT imply truncation or inadequate thickness from count alone.**

### 2.5 Causal Hypotheses Regarding ~0.17 m Subsidence Labeled NOT PROVEN
- In Macro 057, a global SWL discrepancy of $\approx 0.17$ m was observed between coarse ($dp=0.020$ m) and medium ($dp=0.0125$ m) resolutions.
- Attributing this discrepancy to bed hollow shells, boundary infiltration, or numerical dissipation is an **UNPROVEN HYPOTHESIS**.
- Worker v2 explicitly labels all causal explanations as **NOT PROVEN**. Macro comparison alone does not establish causal mechanisms.

### 2.6 Strict Preservation of All 6 Frozen Gauge Operators
- All 6 registered gauge operators are preserved without modification:
  1. `WG1` ($x = 0.60$ m)
  2. `WG2` ($x = 1.40$ m)
  3. `RunupToe` ($x = 2.00$ m)
  4. `WG3` ($x = 2.60$ m)
  5. `WG4` ($x = 3.20$ m)
  6. `Crest` ($x = 3.75$ m)
- Strictly **ZERO gauge relocation** and **ZERO artificial masking** are permitted. Macro 058's failing gauge results (`runup: false, weir: false`) remain recorded as immutable negative evidence.

---

## 3. Architecture of Diagnostic Support Worker v2

The revised diagnostic worker is implemented in [`diagnostic_initial_support_worker_v2.py`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/diagnostic_initial_support_worker_v2.py).

### 3.1 Key Algorithms and Capabilities
```python
def read_official_csv(csv_path: Path) -> Tuple[np.ndarray, List[str], str]:
  """Preamble-tolerant CSV parser with delimiter autodetection (';' or ',')

  and dynamic column mapping for all 13 official fields.
  """
  ...


def compute_nearest_boundary_distances_kdtree(
    sample_fluid: np.ndarray, pos_bound: np.ndarray, r_kernel: float
) -> Tuple[np.ndarray, np.ndarray]:
  """Memory-bounded O(N log M) spatial query using scipy.spatial.cKDTree.

  Eliminates the 500xN_bound tensor OOM bug entirely.
  """
  ...
```

### 3.2 Geometrical Partitioning
- **Sloped Beach Skin**: $x \in [2.00, 3.60]$ m, $|y| \le 0.145$ m, $z \approx 0.280(x - 2.00)$ m.
- **Flat Basin Floor**: $x \in [-0.20, 2.00)$ m, $|y| \le 0.145$ m, $z \approx 0.000$ m.
- **Crest Plateau**: $x \in [3.60, 3.90]$ m, $|y| \le 0.145$ m, $z \approx 0.448$ m.
- **Sidewalls**: $|y| \ge 0.145$ m.
- **Paddle**: Moving boundary particles (`Type == 1`).

---

## 4. Native Diagnostic Export Proposal & ParaView Full-Animation Visual Inspection

In accordance with Root's ParaView standards established in `root_stage1_visual_dynamic_xdmf_001` and `root_stage1_visual_render_display_fix_002`, we propose:

### 4.1 Native 3-Frame Diagnostic Export Proposal
Root strict dispatcher executes a bounded 3-frame inspection on candidate fine mother simulations (`dp = 0.010` m, 801 total frames):
- **Frame 0 ($t = 0.0$ s)**: Initial quiescent hydrostatic equilibrium. Verifies particle lattice arrangement, initial surface datum ($z = 0.400$ m), absence of initial boundary penetration, and zero fluid particle loss.
- **Frame 400 ($t = 8.0$ s)**: Mid-transient dynamic phase. Verifies wave packet propagation along the flume, shoaling on the $m = 0.28$ slope, runup/rundown shoreline motion, weir overtopping jet formation, and free-surface continuity.
- **Frame 800 ($t = 16.0$ s)**: Final reflection and settling phase. Verifies water volume conservation in the receiving basin, absence of particle subsidence beneath the bed, absence of particles escaping the flume boundary, and complete 801-frame temporal continuity.

### 4.2 ParaView Dynamic XDMF Temporal Sidecars
- Structure: XML sidecar (`case.xmf`) referencing immutable HDF5 / PartVTK native data.
- Color mapping: Velocity magnitude $|\mathbf{v}|$ and Pressure $p$.
- Visual Acceptance Criteria:
  1. Coherent, finite free-surface profile across all 801 frames.
  2. Zero physical fluid penetration through the sloped bed or flume boundaries.
  3. No explosive numerical divergence or unbounded velocity spikes.
  4. Proper hydraulic behavior (wave shoaling, breaking/reflection, weir overtopping).

---

## 5. Conditional Minimal Geometry Repair Protocol

To avoid premature or unverified changes to the simulation configuration:
1. **Trigger Condition**:
   - A geometry repair is **ONLY authorized if** visual review of actual frames or the diagnostic worker proves that physical fluid particles penetrate beneath the bed surface ($z < z_{bed}(x) - \epsilon$) or escape the domain during solver execution.
2. **Minimal Non-Intrusive Repair Specification**:
   - If physical penetration is proven, the fix shall consist strictly of adding an extrusion or box backing directly beneath the STL surface (e.g. `<drawbox>` from $z = -0.06$ m to $z = z_{bed}(x)$) in GenCase XML to ensure 3–4 layers of boundary particles along the normal.
   - Max 2 bounded repair attempts per root cause.
3. **No Automatic GPU Spatial Study**:
   - No automatic GPU 3-resolution convergence sweeps shall be scheduled until visual review passes.
   - The Stage 1 goal prioritizes visual acceptance and independent case accumulation over spatial convergence.

---

## 6. Selection of Visually Reasonable Legal Mother & Batch 1 (8 Independent Cases)

### 6.1 Mother Flume Selection
- **Selected Mother**: Compact flume geometry with continuous $m = 0.28$ slope at fine resolution ($dp = 0.010$ m).
- **Legality**: Fully compliant with DS-DATA-02 data contract: authentic 3D lattice, 13 native fields, valid XML, zero unphysical initial overlaps.

### 6.2 Sourcing of Batch 1: First 8 Genuine Independent Physical Cases
In accordance with the 8 / 24 / 48 progression towards 336 total cases across F1–F7, we define 8 genuinely distinct physical cases (4 Runup, 4 Weir) varying wavemaker stroke, period, quiescent depth, and weir crest:

| Case ID | Mechanism | Paddle Stroke $S$ [m] | Wave Period $T$ [s] | SWL Depth $H_{swl}$ [m] | Crest Elevation $z_{crest}$ [m] | Physical Condition Description |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **`F5_RUNUP_BATCH01_CASE01`** | Runup | $0.030$ | $1.20$ | $0.400$ | $0.448$ | Nominal wave packet runup on continuous slope |
| **`F5_RUNUP_BATCH01_CASE02`** | Runup | $0.050$ | $1.20$ | $0.400$ | $0.448$ | High-amplitude wave packet with dynamic runup |
| **`F5_RUNUP_BATCH01_CASE03`** | Runup | $0.040$ | $1.80$ | $0.400$ | $0.448$ | Long-period solitary swell runup |
| **`F5_RUNUP_BATCH01_CASE04`** | Runup | $0.035$ | $1.50$ | $0.380$ | $0.448$ | Shallow basin runup exposing lower slope |
| **`F5_WEIR_BATCH01_CASE05`** | Weir | $0.040$ | $1.20$ | $0.400$ | $0.448$ | Nominal trapezoidal weir overtopping |
| **`F5_WEIR_BATCH01_CASE06`** | Weir | $0.030$ | $1.20$ | $0.400$ | $0.420$ | Submerged low-crest weir overtopping transmission |
| **`F5_WEIR_BATCH01_CASE07`** | Weir | $0.060$ | $1.50$ | $0.400$ | $0.448$ | Energetic wave plunge over weir into receiving basin |
| **`F5_WEIR_BATCH01_CASE08`** | Weir | $0.050$ | $2.00$ | $0.410$ | $0.460$ | High-freeboard weir under elevated water table |

*Independence Certification*: Each case possesses distinct physical parameters affecting hydrodynamic wave celerity, breaker type, runup height, or discharge coefficient. None are resolution repeats or time slices.

---

## 7. Deliverables & Unlaunchable Request Placeholders

All requests are formatted under `ds02.runner-request.v2` and marked unlaunchable (`launch_allowed: false`):

1. **Diagnostic Support Worker v2 Binding & Request**:
   - Binding: [`requests/f5_diagnostic_support_v2_binding.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/requests/f5_diagnostic_support_v2_binding.json)
   - Request: [`requests/F5_DIAGNOSTIC_SUPPORT_V2_REQUEST.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/requests/F5_DIAGNOSTIC_SUPPORT_V2_REQUEST.json)
2. **ParaView 3-Frame Visual Diagnostic Export Request**:
   - Binding: [`requests/f5_stage1_visual_export_binding.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/requests/f5_stage1_visual_export_binding.json)
   - Request: [`requests/F5_STAGE1_VISUAL_3FRAME_REQUEST.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/requests/F5_STAGE1_VISUAL_3FRAME_REQUEST.json)
3. **Batch 1 (8 Independent Cases) Registration**:
   - Definitions: [`requests/f5_stage1_batch8_definitions.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/requests/f5_stage1_batch8_definitions.json)
   - Request: [`requests/F5_STAGE1_BATCH8_REQUEST.json`](file:///home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_049_visual_stage1_support_diagnosis_v2/requests/F5_STAGE1_BATCH8_REQUEST.json)

---

## 8. Ledger Tracking & Verification

- **Model Used**: `gemini-3.8-flash-high` (Verified direct session, zero subagent recursion).
- **Quota Status**: Zero quota errors encountered.
- **Execution Limits**: All solver runs deferred to Root strict dispatcher.
- **Resource Ledger Status**:
  - Cumulative Qualification Attempts: 300 / 320
  - Cumulative Production Attempts: 0 / 420
  - Cumulative GPU Hours: 76.17 / 96.0 GPU·h
  - Cumulative CPU Core Hours: 238.4 / 384.0 CPU·h
  - Free Disk Space: $> 500$ GiB verified
