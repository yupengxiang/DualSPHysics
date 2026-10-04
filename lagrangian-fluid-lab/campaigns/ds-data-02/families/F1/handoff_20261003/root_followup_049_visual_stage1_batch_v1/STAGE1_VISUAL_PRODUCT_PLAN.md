# Stage 1 Visual Product and Batch Plan for Family F1

## 1. Overview and Purpose

Under the user-edited Active Goal, DS-DATA-02 focuses on **Stage 1: full-generation-flow, true 3D full-time, ParaView dynamic + full-animation visual review, and independent physical case batch accumulation (8 / 24 / 48 per family, 336 total)**.

Spatial convergence ($Q\text{-}N$), integration step/save frequency error budgets, long-term particle trajectory consistency, and precise transport/event labels are **NOT** shared prerequisites for Stage 1 batch generation. Prior negative precision results are preserved as historical evidence, but do not block visual acceptance.

---

## 2. Visual Product Architecture (ParaView XDMF Sidecar Pattern)

Reusing the validated Root pattern from `root_stage1_visual_dynamic_xdmf_001`:
1. **Source Immutability**: The typed SPH trajectory (`trajectory.h5`) produced by `ds_data02_nvme_convert_v1.py` remains immutable and read-only.
2. **ParaView XDMF 2.0 Temporal Sidecar (`case.xmf`)**:
   - Written in XML linking directly to the HDF5 datasets via `DataItem` hyperslabs.
   - Polyvertex topology with $N$ particles per frame.
   - Exposes primary fields: `valid`, `type`, `particle_id`, `particle_zone`, `initial_mk`, `initial_mass`, `mass`, `velocity`, `density`, `pressure`.
3. **Dual-View Inspection Setup**:
   - Camera 1 (Isometric View): Full perspective overview capturing 3D flow structure, lateral wake deflection, and vortex formation.
   - Camera 2 (Transverse Side View): Side elevation monitoring free-surface profile, wave runup, and wall clearances.
4. **Visual Review Acceptance Criteria**:
   - No explosive particle blowup or non-finite coordinates ($NaN$/$\pm\infty$).
   - No severe boundary penetration (fluid particles penetrating the $4$-layer thick DBC walls).
   - No unexplained massive particle loss.
   - Full time coverage ($1.6\ \text{s}$ for ECC, $4.0\ \text{s}$ for DUAL).
   - Natural free-surface evolution and wave dynamics.
5. **Product Gate Label**:
   All passed products are explicitly tagged:
   ```json
   {
     "visual_status": "visual_review_passed",
     "numerical_precision_status": "not_accepted_for_stage1_product; precision_pending"
   }
   ```

---

## 3. Product Status for Existing Lower-Head Assets

| Asset / Case ID | Attempt ID | Frames / Time | Typed Conversion Status | XDMF Sidecar Status | ParaView Render Status |
|:---|:---|:---:|:---:|:---:|:---:|
| `F1_FALLBACK_ECC_COARSE` | `root-fallback-ecc-coarse-full161-native-032` | 161 / $1.6\ \text{s}$ | `root-fallback-ecc-coarse-full161-typed-034` (Done) | Binding & Request Ready | Render Request Ready |
| `F1_FALLBACK_ECC_MEDIUM` | `root-fallback-ecc-medium-full161-native-032` | 161 / $1.6\ \text{s}$ | `root-fallback-ecc-medium-full161-typed-034` (Done) | Binding & Request Ready | Render Request Ready |
| `F1_FALLBACK_ECC_FINE` | `root-fallback-ecc-fine-full161-native-033` | 161 / $1.6\ \text{s}$ | Queued in 034/036 | Binding Bound to Typed Output | Queued behind Typed |
| `F1_FALLBACK_DUAL_COARSE` | `root-fallback-dual-coarse-full401-native-032` | 401 / $4.0\ \text{s}$ | Queued in 034/036 | Binding Bound to Typed Output | Queued behind Typed |
| `F1_FALLBACK_DUAL_MEDIUM` | `root-fallback-dual-medium-full401-native-032` | 401 / $4.0\ \text{s}$ | Queued in 034/036 | Binding Bound to Typed Output | Queued behind Typed |
| `F1_FALLBACK_DUAL_FINE` | `root-fallback-dual-fine-full401-native-storage-fix-035` | 401 / $4.0\ \text{s}$ | Queued in 034/036 | Binding Bound to Typed Output | Queued behind Typed |

---

## 4. Batch 1 Scope and Mother Review Dependency

Under Stage 1, Family F1 targets 8 independent physical cases in Batch 1 (4 ECC cases + 4 DUAL cases).
- Mother cases (Row 1 and Row 5) are already simulated and under visual review.
- The remaining 6 proposed cases (Rows 2, 3, 4 for ECC and Rows 6, 7, 8 for DUAL) are defined with full XML, metadata, and runner requests, but **disabled from solver execution** until the user and Root complete visual review of the mother cases.
- Accounting Rule: Multi-resolution runs (coarse/medium/fine) are resolution convergence checks; they do **not** increment the independent physical case count.
