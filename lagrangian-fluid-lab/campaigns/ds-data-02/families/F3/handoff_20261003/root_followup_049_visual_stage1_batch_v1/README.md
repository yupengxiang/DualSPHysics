# F3 Followup 049: Stage 1 ParaView Full-Animation Renderer & Batch 1 Independent Physical Cases

**Campaign:** DS-DATA-02  
**Family:** F3 (Open-Top Rectangular Tank Two-Axis Sloshing)  
**Authority:** Root Followup 049 / User Edited ACTIVE GOAL Stage 1 (2026-10-04)  
**Worktree:** `/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics`  
**Integration Base:** `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics`  
**Raw Data Directory:** `/home/jade/Projects/DualSPHysics-data/ds-data-02`  
**Model & Execution Policy:** Verified `gemini-3.8-flash-high`, reasoning effort `max`. SOURCE-ONLY in isolated family scope with local commit; no recursive agents; Root strict dispatcher alone.

---

## 1. Executive Summary & Active Goal Compliance

Following the user's revised **ACTIVE GOAL** (`lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_20261004_ZH.md`), the primary objective for DS-DATA-02 is now:
> **Stage 1 full-generation-flow, true 3D fulltime, ParaView dynamic + full-animation visual review, and independent physical case batches (8 / 24 / 48 per F1..7, 336 total).**

### Key Governance Principles:
1. **Separation of Stages and Certifications:**
   - **Q-I (Integrity), Visual Review, Q-N (Numerical Reference), and Q-E (External Validation)** are strictly decoupled.
   - Spatial convergence ladders (dp0.006, dp0.005, dp0.0045), integration time step / save frequency error budgets, long-term per-particle trajectory consistency, precise transport/event labels, and parameter range qualification are **NOT shared stage 1 prerequisites**.
   - Visual inspection approval does **NOT** equal numerical precision certification. Every case passing visual review is explicitly tagged: `"visual review passed; numerical precision not accepted"`.
2. **Anchor Case Definition:**
   - The user-accepted existing case `F3_TWOAXIS_AY0P50_PITCH_NOMINAL` ($A_y = 0.50\ \text{m/s}^2, A_{pitch} = 1.00$) at resolution $dp = 0.006\ \text{m}$ (full 836 saved states, native 060 / typed 067) serves as the canonical anchor.
   - Canonical physical condition hash: `49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb`.
   - Prior owner 046 range XMLs ($A_y \in \{0.25, 0.375, 0.50, 0.625, 0.75\}$) provide ready source-only foundation.
3. **Strict Non-Recounting Policy:**
   - Spatial discretization ladders (dp0.006, dp0.005, dp0.0045), temporal reruns, time slices, and derived viewing products **NEVER** count as separate independent physical cases.
   - An independent physical case must represent distinct physical forcing coordinates $(A_y, A_{pitch})$.
4. **Preservation of Negative Evidence:**
   - Historical coarse-vs-fine 5% macro discrepancies (Followup 032 kinetic energy, mean velocity, local velocity) and transport fate differences are preserved in the permanent record and not silently suppressed or overwritten.
5. **Resource Budget Caps (Maintained Unchanged):**
   - Qualification attempts: $\le 320$ (cumulative used: 300)
   - Production attempts: $\le 420$ (cumulative used: 0)
   - GPU computation: $\le 96\ \text{GPU}\cdot\text{h}$ (cumulative used: 76.17)
   - CPU computation: $\le 384\ \text{CPU core}\cdot\text{h}$ (cumulative used: 238.4)
   - Disk space requirement: Home free space $\ge 500\ \text{GiB}$ (current: 2,327 GiB, fully compliant)
   - Gemini quota status: healthy, active under `gemini-3.8-flash-high`.

---

## 2. ParaView Full-Animation Renderer (`paraview_animation_renderer.py`)

A stand-alone, robust, CPU offscreen ParaView worker script has been authored to perform full-time visual verification of XDMF temporal sidecars:

- **Strict Library Boundary:** Absolutely **no `h5py`** is imported in the `pvpython` worker process. The reader relies entirely on native ParaView/VTK readers (`XDMFReader`, verified via `reader.GetXMLName() == 'XdmfReader'`).
- **Exact Particle Separation:**
  - `valid == 1`: Active fluid and boundary particles (filters out invalid/dead slots).
  - `valid == 1 and type == 3`: Fluid particle cohort (displayed in blue `[0.0, 0.38, 0.85]`, point size 2).
  - `valid == 1 and type in [0, 2]`: Boundary tank walls (displayed with opacity $\approx 0.15$, color `[0.2, 0.25, 0.3]`).
- **Kinematic & Boundary Claim Clarification:**
  - DualSPHysics implements container motion via body acceleration input (`acctimesfile`).
  - Tank boundary particles are strictly `fixedType0` in the accelerating computational reference frame.
  - **No floating or moving rigid body claim** is made.
- **Dual-View Scientific Projections:**
  - View 0 (Isometric): Parallel projection scale 0.43, camera position `[1.10, -1.60, 0.95]`, focal point `[0.0, 0.0, 0.22]`, view up `[0.0, 0.0, 1.0]`.
  - View 1 (Transverse Side Orthogonal): Parallel projection scale 0.43, camera position `[0.0, -2.00, 0.22]`, focal point `[0.0, 0.0, 0.22]`, view up `[0.0, 0.0, 1.0]`.
- **All 836 Frames Rendered (No Subsampling):**
  - Unlike superficial 3-frame checks, every actual saved state from $t = 0.00\ \text{s}$ to $t = 8.35\ \text{s}$ (836 frames at 100 Hz) is processed and rendered.
  - Every frame image is annotated: `F3 TWOAXIS | frame XXXX/0835 | actual t=X.XXXXXX s | PRECISION NOT ACCEPTED`.
  - Contact sheets containing 24 indexed frames per sheet (`all_frames_XXX.png`) allow rapid visual indexing.
  - Full animated GIF (`full_saved_animation.gif`) at 40 ms per saved frame.
  - Complete ParaView state file (`case.pvsm`) for interactive session resumption.
- **Continuous Integrity Diagnostics:**
  - Verifies exact match with manifest timestamps (`actual_time_s`).
  - Asserts that all active particles have finite 3D coordinates.
  - Verifies strict per-particle identity axis preservation: `particle_id` and `particle_zone` must remain unchanged across all 836 frames.
  - Asserts finite physical scalar/vector fields (`mass`, `velocity`, `density`, `pressure`) on all valid particles.
  - Tracks fluid envelope bounding box $[x_{min}, y_{min}, z_{min}]$ to $[x_{max}, y_{max}, z_{max}]$.

---

## 3. Batch 1: 8 Independent Physical Cases Parameter Table

The 2D physical control domain is defined by coupling the primary longitudinal pitch motion with the second-axis transverse linear acceleration within the canonical plain 5-wall rectangular container ($0.90\ \text{m} \times 0.18\ \text{m} \times 0.51\ \text{m}$, water depth $0.09\ \text{m}$, fluid mass $14.58\ \text{kg}$):

$$\vec{a}_{forcing}(t) = \begin{pmatrix} A_{pitch} \cdot a_{x,nom}(t) \\ A_y \cdot E(t) \cdot \sin(\omega_y t + \phi_y) \\ g_z + A_{pitch} \cdot (a_{z,nom}(t) - g_z) \end{pmatrix}, \quad \vec{\alpha}_{forcing}(t) = \begin{pmatrix} 0 \\ A_{pitch} \cdot \alpha_{y,nom}(t) \\ 0 \end{pmatrix}$$

where:
- Transverse wavenumber $k_y = \frac{\pi}{W} \approx 17.4533\ \text{rad/m}$.
- Transverse eigenmode circular frequency $\omega_y = \sqrt{g k_y \tanh(k_y H)} \approx 12.5312\ \text{rad/s}$ ($f_y \approx 1.9944\ \text{Hz}$, $T_y \approx 0.5014\ \text{s}$).
- Envelope $E(t)$ is a smooth Hann/cosine ramp over $\tau_{ramp} = 0.50\ \text{s}$.
- $A_y \in [0.25, 0.75]\ \text{m/s}^2$ (transverse acceleration amplitude).
- $A_{pitch} \in [0.90, 1.10]$ (longitudinal pitch scaling ratio).

### Batch 1 Parameter Table (8 Independent Cases)

| Index | Case ID | $A_y$ (m/s²) | $A_{pitch}$ | Role / Parameter Space Location | Status & Governance |
|:---:|:---|:---:|:---:|:---|:---|
| **1** | `F3_TWOAXIS_AY0P50_P1P00_NOMINAL` | **0.500** | **1.00** | **Anchor Case (Nominal Center)** | Completed native060/typed067; user visually accepted; root review pending |
| **2** | `F3_TWOAXIS_AY0P25_P1P00` | **0.250** | **1.00** | Transverse Lower Endpoint | Source-only; disabled until Root visual review anchor |
| **3** | `F3_TWOAXIS_AY0P375_P1P00` | **0.375** | **1.00** | Transverse Interior Low | Source-only; disabled until Root visual review anchor |
| **4** | `F3_TWOAXIS_AY0P625_P1P00` | **0.625** | **1.00** | Transverse Interior High | Source-only; disabled until Root visual review anchor |
| **5** | `F3_TWOAXIS_AY0P75_P1P00` | **0.750** | **1.00** | Transverse Upper Endpoint | Source-only; disabled until Root visual review anchor |
| **6** | `F3_TWOAXIS_AY0P50_P0P90` | **0.500** | **0.90** | Pitch Lower Endpoint | Source-only; disabled until Root visual review anchor |
| **7** | `F3_TWOAXIS_AY0P50_P1P10` | **0.500** | **1.10** | Pitch Upper Endpoint | Source-only; disabled until Root visual review anchor |
| **8** | `F3_TWOAXIS_AY0P25_P0P90` | **0.250** | **0.90** | Coupled Minimal Boundary ($A_y$ min, $A_{pitch}$ min) | Source-only; disabled until Root visual review anchor |

*Note:* All 8 cases possess unique physical forcing coordinates. Discretization resolution variations ($dp = 0.006, 0.005, 0.0045\ \text{m}$) are strictly excluded from the physical case count.

---

## 4. Native GenCase Patch Generator (`gencase_patch_generator.py`)

Derived from `root-cell3-dp006-twoaxis-ay0p50-actual-gencase-056` (Followup 056 / 040):
- **Preflight Semantic Checking:** Asserts that definition XML `casedef` matches the anchor `F3_CELL3_plain_0p006_Def.xml` byte-for-byte (`d8a2ffdccd0687f8a26792c6f412a7c5b95a982874ef7471f7ff23e59f24bf74`).
- **Exact Forcing Generation:** Drives `twoaxis_pitch_forcing_transformer.py` to produce `CaseSloshingAccData.csv` for any $(A_y, A_{pitch})$ pair with verified source SHA256 (`6f42660a...`), exact 167,001 rows, strictly increasing timestamps, and IEEE-754 `.17g` precision.
- **Disabled Until Root Visual Review Anchor:** All generated runner requests are emitted with:
  ```json
  "launch_allowed": false,
  "launch_owner": "root",
  "q_n": "not_granted",
  "production_approval": "none",
  "visual_review_status": "disabled until Root visual review anchor",
  "numerical_precision_status": "not accepted"
  ```
- **CPU Resource Limits:** $\le 2$ threads, bounded runtime $\le 600\ \text{s}$, storage estimate $\le 1\ \text{GiB}$.

---

## 5. Artifacts and Directory Inventory

```
root_followup_049_visual_stage1_batch_v1/
├── README.md                                       # Comprehensive specification (this document)
├── batch_param_table.json                         # 8 independent physical cases parameter table
├── twoaxis_pitch_forcing_transformer.py           # 2-axis forcing transformer (Ay + Apitch)
├── paraview_animation_renderer.py                 # Stand-alone ParaView full-animation worker
├── gencase_patch_generator.py                     # Native GenCase patch generator (derived from 056)
├── run_stage1_visual_batch_audit.py               # Stand-alone automated audit runner
├── test_stage1_visual_batch.py                    # 22-case unit test suite (100% pass)
├── audit-report.json                              # Structured audit receipt (all_checks_passed: true)
├── definitions/                                   # Definition XML files for all 8 cases
│   ├── F3_CELL3_plain_0p006_Def.xml
│   ├── F3_TWOAXIS_AY0P50_P1P00_Def.xml (Anchor)
│   ├── F3_TWOAXIS_AY0P25_P1P00_Def.xml
│   ├── F3_TWOAXIS_AY0P375_P1P00_Def.xml
│   ├── F3_TWOAXIS_AY0P625_P1P00_Def.xml
│   ├── F3_TWOAXIS_AY0P75_P1P00_Def.xml
│   ├── F3_TWOAXIS_AY0P50_P0P90_Def.xml
│   ├── F3_TWOAXIS_AY0P50_P1P10_Def.xml
│   └── F3_TWOAXIS_AY0P25_P0P90_Def.xml
├── bindings/                                      # Case binding specifications for all 8 cases
│   ├── binding_01_f3_twoaxis_ay0p50_p1p00_nominal.json
│   ├── binding_02_f3_twoaxis_ay0p25_p1p00.json
│   ├── binding_03_f3_twoaxis_ay0p375_p1p00.json
│   ├── binding_04_f3_twoaxis_ay0p625_p1p00.json
│   ├── binding_05_f3_twoaxis_ay0p75_p1p00.json
│   ├── binding_06_f3_twoaxis_ay0p50_p0p90.json
│   ├── binding_07_f3_twoaxis_ay0p50_p1p10.json
│   └── binding_08_f3_twoaxis_ay0p25_p0p90.json
└── requests/                                      # Unlaunchable runner request templates
    ├── request_paraview_software_animation_anchor.json
    ├── request_01_gencase_f3_twoaxis_ay0p50_p1p00_nominal.json
    ├── request_02_gencase_f3_twoaxis_ay0p25_p1p00.json
    ├── request_03_gencase_f3_twoaxis_ay0p375_p1p00.json
    ├── request_04_gencase_f3_twoaxis_ay0p625_p1p00.json
    ├── request_05_gencase_f3_twoaxis_ay0p75_p1p00.json
    ├── request_06_gencase_f3_twoaxis_ay0p50_p0p90.json
    ├── request_07_gencase_f3_twoaxis_ay0p50_p1p10.json
    └── request_08_gencase_f3_twoaxis_ay0p25_p0p90.json
```

---

## 6. Verification and Audit Results

1. **Unit Test Suite:**
   - Command: `pytest -v test_stage1_visual_batch.py`
   - Result: `22 passed in 0.27s` (100% pass).
2. **Automated Audit Script:**
   - Command: `python run_stage1_visual_batch_audit.py`
   - Result: `all_checks_passed = True`.
   - Verified:
     * 8 unique physical parameter coordinates.
     * All 9 definition XMLs match anchor SHA256 `d8a2ffdccd0687f8a26792c6f412a7c5b95a982874ef7471f7ff23e59f24bf74`.
     * All 8 binding files mark numerical precision `not accepted`.
     * All 9 runner requests have `launch_allowed = False`, `launch_owner = root`, `q_n = not_granted`.
     * `paraview_animation_renderer.py` has no `h5py` import, asserts `XdmfReader`, sets opacity $\approx 0.15$, dual cameras, and checks identity axis preservation.
     * `twoaxis_pitch_forcing_transformer.py` satisfies fundamental transverse eigenfrequency $\omega_y \approx 12.5312\ \text{rad/s}$, zero-drive identity, and pitch scaling formula.
     * Resource usage respects cumulative caps (GPU 76.17/96 h, CPU 238.4/384 h, qualification 300/320, production 0/420, disk free 2,327 GiB $\ge 500$ GiB).
