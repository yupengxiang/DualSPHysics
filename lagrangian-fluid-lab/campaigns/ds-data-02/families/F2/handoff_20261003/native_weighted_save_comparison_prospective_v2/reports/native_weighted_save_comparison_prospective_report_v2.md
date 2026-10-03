# DS-DATA-02 Family F2: Native-Weighted Save Comparison Prospective Suite v2

**Document Identifier:** `ds-data-02.f2.native-weighted-save-comparison-prospective-report.v2`  
**Generated:** `2026-10-04T02:30:00Z`  
**Status:** `prospective_staged_for_root_cpu_dispatch` (`launch: false`)  
**Claim Boundaries:** `q_n: not_granted`, `production: none`, `q_i: not_granted`  

---

## 1. Executive Summary & Root Followup 037 F2 Mandate

This report delivers the prospective specification and fully executable implementation for the **F2 Native-Weighted Temporal Save Comparison Worker v2**, remediating all deficiencies identified in Root's rejection of the 036 delivery.

The objective of this prospective worker is to conduct an authoritative, rigorous cross-resolution temporal save comparison between the completed baseline fine run (**Nominal 401 frames**, $\Delta t = 0.010\text{ s}$) and the completed dense fine run (**Dense 4001 frames**, $\Delta t = 0.001\text{ s}$) under the identical physical mother continuum condition and the Root-approved frozen v8 native-mass-bound event observer.

### Completed Source Attempts
- **Nominal 401 Frames:** `root-offset-fine-full401-frozen-events-native-weights-024`  
  - Attempt Root: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-full401-frozen-events-native-weights-024`  
  - Receipt Status: `completed`, Returncode: `0`  
  - Labels SHA-256: `3947aee1fe5528f5605d594d578e1545e1d9c72bda30dde7e6c829e2043ca292` (~1.13 GiB)  
  - Report SHA-256: `0178b6cd2b708ed7f7501f17d349aad47c7f7c72e31af7f36ecd5a7ddc90b852`  
- **Dense 4001 Frames:** `root-offset-fine-full4001-frozen-events-native-weights-025`  
  - Attempt Root: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-full4001-frozen-events-native-weights-025`  
  - Receipt Status: `completed`, Returncode: `0`  
  - Labels SHA-256: `f3af358d3f331129895a32c04ecabfbdcd8fb8846640e68f73ab706d434f2a2a` (~10.9 GiB)  
  - Report SHA-256: `88b635243dd6ea3d77d8c614b2bde46b48c279abf21303ee5b2fb771e737fe3f`  

---

## 2. Root 036 Rejection Analysis & v2 Remediations

Root rejected the 036 delivery citing five core scientific and operational defects. Each is rigorously resolved in this v2 suite:

### Defect 1: `--run-full-comparison` Flag Never Implemented; Main Only Ran Metadata Audit
- **036 Flaw:** Main hardcoded a call to `run_metadata_comparison`, meaning the worker never actually inspected the HDF5 label files, never extracted UID fates, never compared per-UID residence, and never evaluated saved bracket overlaps on actual event arrays.
- **v2 Remediation:** Worker main directly parses `--binding` and `--output` and executes `execute_full_h5_comparison`. All H5 guard checks and full array comparisons run directly.

### Defect 2: Unauthorized Proximity Gates (`|dt| <= 0.010 s`) and Invented `2*dt` Flutter Bands
- **036 Flaw:** Events were paired using an invented temporal proximity tolerance `|t_nom - t_dense| <= 0.010 s`. Multiple dense events inside this tolerance were arbitrarily declared "sub-grid flutter".
- **v2 Remediation:** Completely removed all proximity gates, `tolerance_s` parameters, and invented flutter bands. Candidate association is determined **strictly by the intersection of actual saved frame bracket intervals**:
  $$[t_{\text{start}}, t_{\text{end}}] = [t(\text{frame\_before}), t(\text{frame\_after})]$$
  Overlap exists if and only if $\max(t_{\text{start,nom}}, t_{\text{start,dense}}) \le \min(t_{\text{end,nom}}, t_{\text{end,dense}})$.

### Defect 3: Failure to Isolate Ambiguous Overlaps (Fake Joint Matches)
- **036 Flaw:** Overlapping multi-event clusters were zipped or greedily assigned to the closest timestamp, creating false "joint matches".
- **v2 Remediation:** Formulates a bipartite overlap graph for each particle UID and event code. Any connected component containing more than one nominal event or more than one dense event (1-to-many, many-to-one, many-to-many) is strictly classified as **AMBIGUOUS**. Ambiguous groups are isolated, recorded separately, and **NEVER claimed genuinely joint**. Only isolated 1:1 components are accepted as proven unique joint matches.

### Defect 4: Conflating Aggregate Inventory Equality with Per-UID Fate Identity
- **036 Flaw:** 036 reported aggregate destination mass differences of 0.0 kg and made blanket assertions of bitwise physical equality without verifying per-UID fates.
- **v2 Remediation:** Formulates an explicit distinction:
  - **Aggregate destination mass inventory** (sum of mass in each destination at final frame).
  - **Per-UID final destination fate** (vector $d_i \in \{0, 1, 2, 3, 4\}$ for $i=1 \dots 196608$).
  - Computes `fate_switch_mask = (nom_final != dense_final)`, counting switched particles, switched mass, and a full 5x5 destination transition matrix.
  - Enforces the explicit scientific disclaimer: *"Equal aggregate inventory does NOT establish identical per-UID fates."*

### Defect 5: Unproven Physical Labeling of Unmatched Dense Events
- **036 Flaw:** 036 labeled all excess dense events as "physical sub-grid flutter" without proof.
- **v2 Remediation:** Unmatched dense events are objectively reported as `extra_dense`. No physical flutter or transient claim is made without rigorous dynamical proof.

---

## 3. NVMe Protected Floor & Single-Copy Protocol

To safeguard local NVMe storage and prevent disk full errors during execution on large H5 label datasets (~10.9 GiB):

1. **100 GiB Protected Floor Check:**
   Before touching any scratch disk, the worker verifies that:
   $$\text{FreeSpace}(\text{scratch\_parent}) \ge \text{SingleSourceMaxBytes} + 100\text{ GiB}$$
   If free space is less than 100 GiB plus the file size, execution immediately halts with `ComparisonError`.

2. **Single Private Copy Protocol:**
   The worker never copies both label files simultaneously. It processes sources strictly sequentially:
   - Copy nominal labels (~1.13 GiB) to temporary private file using `verified_copy`.
   - Open temporary file with `h5py`, extract required arrays into memory, close file.
   - Immediately delete temporary file (`unlink`).
   - Copy dense labels (~10.9 GiB) to temporary private file using `verified_copy`.
   - Open temporary file with `h5py`, extract required arrays into memory, close file.
   - Immediately delete temporary file (`unlink`).
   At peak, only a single H5 file exists in scratch (~10.9 GiB), fitting well within the 16 GiB storage cap.

3. **Removal on Terminal:**
   A robust `try ... finally` block guarantees that temporary files are deleted even if an unexpected exception occurs or SIGTERM is received.

4. **Zero Trajectory Copying:**
   The full 60 GiB raw trajectory files are NEVER copied or accessed. The worker operates exclusively on the compact labels H5 files and JSON reports.

---

## 4. Continuum Invariance & Native Mass Precision Authority

The comparison rigorously verifies that both runs share identical continuum and operator parameters:

- **Mother Physical Condition Hash:** `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef`
- **Geometry SHA-256:** `dc2f2d1ab3d842a25fd8025a33b1c81920e1caebe0fd354fbff68bfa89b3e9a9`
- **Motion Control SHA-256:** `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70`
- **Operator Version:** `f2-moving-cup-local-z-top-v8-native-mass-bound`
- **Operator Code SHA-256:** `ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406`
- **Fluid Cohort Size:** Exactly 196,608 particles.
- **Native Particle Mass:** Exactly `0.0001250000059371814 kg` (IEEE-754 binary32 `0x6f120339` widened to float64).
- **Native Cohort Mass:** Exactly `24.576001167297363 kg`.
- **Continuous XML Benchmark:** `24.576 kg` (unnormalized benchmark).
- **Representation Drift:** `+4.7497e-08` (+1.1673 mg).
- **Legacy $10^{-12}$ Mass Diagnostic:** Honestly reported as `fail` (representation delta exceeds legacy threshold; no artificial rescaling applied).

---

## 5. Native Exclusions & Unrelabeled Unknowns

- Exactly **2,151 fluid identities** carry official native exclusion motive 1.
- All 2,151 identities are verified to have:
  - `destination_code == 0` (`unknown`)
  - `unknown_reason_code == 1` (`native_invalid`)
- Total retained unknown mass:
  $$2151 \times 0.0001250000059371814\text{ kg} = 0.2688750127708772\text{ kg}$$
- **Zero native exclusions are relabeled as physical spill.**

---

## 6. Strict Saved-Bracket Episodic Event Matching Algorithm

For each particle index $p \in \{0 \dots 196607\}$ and each event code $c \in \{1 \dots 6\}$:

1. Let nominal events be $\mathcal{N} = \{N_1, \dots, N_k\}$ and dense events be $\mathcal{D} = \{D_1, \dots, D_m\}$.
2. Each event $E$ has an actual saved bracket interval $[t_{\text{start}}, t_{\text{end}}] = [t(\text{frame\_before}), t(\text{frame\_after})]$.
3. Construct the bipartite overlap matrix $\mathbf{O} \in \{0, 1\}^{k \times m}$:
   $$O_{ij} = \mathbb{I}\left( \max(t_{\text{start}}(N_i), t_{\text{start}}(D_j)) \le \min(t_{\text{end}}(N_i), t_{\text{end}}(D_j)) \right)$$
4. Compute degrees: $d_i^{\mathcal{N}} = \sum_j O_{ij}$ and $d_j^{\mathcal{D}} = \sum_i O_{ij}$.
5. Classification:
   - **Unmatched Nominal:** Events $N_i$ with $d_i^{\mathcal{N}} = 0$.
   - **Extra Dense:** Events $D_j$ with $d_j^{\mathcal{D}} = 0$.
   - **Proven Unique 1:1 Joint:** Component $\{N_i, D_j\}$ where $O_{ij} = 1$ and $d_i^{\mathcal{N}} = 1$ and $d_j^{\mathcal{D}} = 1$.
   - **Ambiguous Overlap Group:** Any component containing $>1$ nominal events or $>1$ dense events. Reported under `ambiguous_nominal` and `ambiguous_dense`.
6. Exact Conservation:
   $$k = |\text{UniqueJoint}| + |\text{AmbiguousNom}| + |\text{UnmatchedNom}|$$
   $$m = |\text{UniqueJoint}| + |\text{AmbiguousDense}| + |\text{ExtraDense}|$$

---

## 7. Residence Time vs Cumulative Event Flux

- **Residence:** Time-integrated destination occupancy ($\text{kg}\cdot\text{s}$) computed via trapezoidal integration.
- **Cumulative Event Flux:** Total mass crossing aperture boundaries.
- **Scientific Preservation:** Due to repeated crossings of aperture boundaries (chords/flutter), cumulative flux across the receiver entry (~15.2 kg / ~20.6 kg) and tray entry (~100.8 kg / ~133.9 kg) **naturally exceeds the initial fluid cohort mass (24.576 kg)**. Flux and residence are reported as distinct physical observables.

---

## 8. Save Half-Width Discretization Budget

- **Budget Threshold:** $\Delta t_{\text{save}} / 2 \le 0.00073363908\text{ s}$.
- **Nominal 401 Frames:** Observed half-width $\approx 0.0050\text{ s} > 0.0007336\text{ s} \implies$ **FAIL** (budget exceeded).
- **Dense 4001 Frames:** Observed half-width $\approx 0.0005\text{ s} \le 0.0007336\text{ s} \implies$ **PASS** (budget satisfied).
- **Governance Notice:** A passing save half-width discretization budget satisfies observation resolution requirements only. It does NOT grant Q-N qualification or production acceptance.

---

## 9. Resource & Execution Specifications

- **Runner Request Kind:** `cpu` (`cpu_task_kind: audit`)
- **CPU Reservation:** 2 threads (`cpu_threads: 2`)
- **Max Wall Time:** 3,600 seconds (`max_wall_seconds: 3600`)
- **Estimated Storage Allowance:** 16 GiB (`estimated_storage_bytes: 17179869184`)
- **Scratch Space Requirement:** NVMe with $\ge 100\text{ GiB}$ free space floor.
- **Launch Flag:** `launch: false` (staged for Root review and authorization).
- **Claim Boundaries:** `q_n: not_granted`, `production: none`, `q_i: not_granted`.
