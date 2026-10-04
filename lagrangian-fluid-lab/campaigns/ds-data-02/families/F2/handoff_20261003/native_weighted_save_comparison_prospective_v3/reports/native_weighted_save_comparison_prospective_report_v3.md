# DS-DATA-02 Family F2: Native-Weighted Save Comparison Prospective Suite v3

**Document Identifier:** `ds-data-02.f2.native-weighted-save-comparison-prospective-report.v3`  
**Generated:** `2026-10-04T03:30:00Z`  
**Status:** `prospective_staged_for_root_cpu_dispatch` (`launch_allowed: false`, `launch: false`)  
**Claim Boundaries:** `q_n: not_granted`, `production: none`, `q_i: not_granted`  

---

## 1. Executive Summary & Root Followup 038 F2 Mandate

This prospective report presents the specification and locally verified executable implementation for the **F2 Native-Weighted Temporal Save Comparison Worker v3**. This delivery directly addresses Root's code review and instructions following the 037/v2 submission.

### Core Enhancements in Suite v3
1. **Actual Per-UID Residence Comparison:**
   Derives per-UID residence directly from the actual `destination_code` array across all native frames for all 5 destination codes (0: unknown, 1: cup, 2: receiver, 3: tray, 4: inflight), matching the unchanged V6 trapezoidal rule:
   $$R[i, c] = \sum_{k=1}^{K-1} \frac{1}{2} \left( \mathbb{I}(d_{k-1, i} == c) + \mathbb{I}(d_{k, i} == c) \right) \Delta t_k$$
   Streams data in bounded frame chunks (64 frames $\approx 12.5\text{ MiB}$); never performs full dense trajectory copies into RAM.
2. **Per-UID Residence Invariants Verified:**
   - **Duration Equality:** $\sum_{c=0}^4 R[i, c] = t_{\text{end}} - t_{\text{start}}$ for every particle $i \in \{0 \dots 196607\}$.
   - **Aggregate Reproduction:** Weighted sum $\sum_i m_i R[i, c]$ reproduces the original observation JSON residence within floating-point summation reassociation roundoff ($< 10^{-8}\text{ kg}\cdot\text{s}$, justified as $\epsilon \sqrt{N}$ floating-point roundoff).
3. **Descriptive Per-UID Residence Reporting:**
   Reports mass-weighted mean absolute gap, mass-weighted mean signed gap, max absolute gap, p50, p90, p95, p99 percentiles, and gap particle counts/fractions descriptively, with no speculative acceptance threshold.
4. **Literal Closed Saved-Bracket Intersection:**
   Candidate event associations are formed strictly via literal closed interval intersection:
   $$\max(t_{\text{start,nom}}, t_{\text{start,dense}}) \le \min(t_{\text{end,nom}}, t_{\text{end,dense}})$$
   Completely removes the invented $+10^{-12}\text{ s}$ interval extension. Exact endpoint touching is permitted ($\le$ and $\ge$); disjoint intervals separated by any distance (even $< 10^{-12}\text{ s}$) are strictly disjoint.
5. **Event Tuple Integrity Verification:**
   Verifies every event tuple against underlying particle arrays (`idp`, `zone`, `source_mk`, `source_layer_index`, `mass_kg`) and frame brackets.
6. **Exclusive File Creation (`mode='x'`):**
   Output files (JSON and Markdown) are written exclusively with mode `'x'` preceded by prior-existence checks. Never overwrites or unlinks arbitrary prior targets.
7. **Protected Scratch Floor & Single Source Copy:**
   Enforces $\ge 100\text{ GiB}$ free space floor and registered $\le 32\text{ GiB}$ cap. Uses owned `tempfile.TemporaryDirectory` with sequential single-source-at-a-time copy and pre/post read byte hashes.
8. **Direct Path SHA Verification:**
   `expected_sha` is verified in direct-read mode as well as copy mode.

---

## 2. Completed Source Attempts Inventory

Both comparison sources are completed0 receipts produced under identical continuum conditions and the frozen V8 operator:

- **Nominal 401 Frames:** `root-offset-fine-full401-frozen-events-native-weights-024`  
  - Attempt Root: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-full401-frozen-events-native-weights-024`  
  - Receipt Status: `completed`, Returncode: `0`  
  - Labels SHA-256: `3947aee1fe5528f5605d594d578e1545e1d9c72bda30dde7e6c829e2043ca292`  
  - Report SHA-256: `0178b6cd2b708ed7f7501f17d349aad47c7f7c72e31af7f36ecd5a7ddc90b852`  
  - Exact Frames: `401`, Time Window: `[0.0, 4.000003024029022]`  
- **Dense 4001 Frames:** `root-offset-fine-full4001-frozen-events-native-weights-025`  
  - Attempt Root: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001/root-offset-fine-full4001-frozen-events-native-weights-025`  
  - Receipt Status: `completed`, Returncode: `0`  
  - Labels SHA-256: `f3af358d3f331129895a32c04ecabfbdcd8fb8846640e68f73ab706d434f2a2a`  
  - Report SHA-256: `88b635243dd6ea3d77d8c614b2bde46b48c279abf21303ee5b2fb771e737fe3f`  
  - Exact Frames: `4001`, Time Window: `[0.0, 4.000003024029022]`  

---

## 3. Detailed Algorithmic Remediations in v3

### 3.1 Streaming Per-UID Residence Calculation
Frozen V6 stores `destination_code` as an $(N_{\text{frames}}, N_{\text{particles}})$ array of `int8`. To compute per-UID residence without loading dense multi-gigabyte arrays into RAM:
1. Initialize `residence = np.zeros((n_particles, 5), dtype=np.float64)`.
2. Iterate through frame slices in bounded blocks of 64 frames.
3. For each adjacent frame transition $k-1 \to k$, add $0.5 \times \Delta t_k$ to the destinations indicated by $\text{dest}[k-1]$ and $\text{dest}[k]$.
4. Total duration verification:
   $$\max_i \left| \sum_{c=0}^4 R[i, c] - (t_{\text{end}} - t_{\text{start}}) \right| \le 10^{-10}\text{ s}$$
5. JSON reproduction verification:
   $$\left| \sum_{i=1}^{N} m_i R[i, c] - \text{JSON\_mass\_time}[c] \right| \le 10^{-8}\text{ kg}\cdot\text{s}$$

### 3.2 Descriptive Gap Metrics
For each destination code, the gap $\Delta_i = R_{\text{dense}}[i, c] - R_{\text{nom}}[i, c]$ is evaluated:
- $\text{MW\_Mean\_Abs\_Gap} = \frac{\sum_i m_i |\Delta_i|}{\sum_i m_i}$
- $\text{Max\_Abs\_Gap} = \max_i |\Delta_i|$
- Percentiles: p50, p90, p95, p99
- Gap Particle Count and Fraction: $\sum_i \mathbb{I}(|\Delta_i| > 10^{-12})$
These metrics are reported descriptively without speculative pass/fail thresholds.

### 3.3 Strict Literal Closed Bracket Intersection
For nominal event $N_i$ and dense event $D_j$ on the same particle UID and event code:
- Nominal bracket: $[t_{\text{start}}(N_i), t_{\text{end}}(N_i)] = [t(\text{fb}), t(\text{fa})]$
- Dense bracket: $[t_{\text{start}}(D_j), t_{\text{end}}(D_j)] = [t(\text{fb}), t(\text{fa})]$
- Overlap exists if and only if:
  $$t_{\text{start}}(D_j) \le t_{\text{end}}(N_i) \quad \text{AND} \quad t_{\text{end}}(D_j) \ge t_{\text{start}}(N_i)$$
No $+10^{-12}\text{ s}$ artificial padding is permitted.
Connected components of the overlap bipartite graph:
- Unique 1:1 components $\to$ `proven_unique_1to1_joint`
- Any component with $>1$ nominal or $>1$ dense event $\to$ `ambiguous_groups` (never claimed joint)
- Degree 0 nominal $\to$ `unmatched_nominal`
- Degree 0 dense $\to$ `extra_dense`
Exact count and mass conservation is verified for all 6 event codes.

### 3.4 Protected File I/O & Scratch Management
- All output files are opened with mode `'x'`. If an output file or markdown report already exists, the worker raises `ComparisonError` immediately.
- Scratch directories are allocated via `tempfile.TemporaryDirectory` with prefix `ds02_f2_`. Only a single source is copied and held at any time, respecting the 100 GiB free space floor and 32 GiB registered cap.
- Byte hashes are verified before and after reading from temporary copies.

---

## 4. Continuum Invariance & Native Mass Precision Authority

The comparison enforces absolute identity across both runs:
- **Mother Physical Condition Hash:** `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef`
- **Geometry SHA-256:** `dc2f2d1ab3d842a25fd8025a33b1c81920e1caebe0fd354fbff68bfa89b3e9a9`
- **Motion Control SHA-256:** `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70`
- **Operator Version:** `f2-moving-cup-local-z-top-v8-native-mass-bound`
- **Operator SHA-256:** `ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406`
- **Fluid Cohort Particles:** Exactly 196,608 particles.
- **Native Single Particle Mass:** Exactly `0.0001250000059371814 kg`.
- **Native Cohort Mass:** Exactly `24.576001167297363 kg`.
- **Continuous XML Benchmark:** `24.576 kg` (unnormalized benchmark).
- **Representation Delta:** $+4.7497\times 10^{-8}$ (+1.1673 mg).
- **Legacy $10^{-12}$ Mass Diagnostic:** Reported honestly as `fail` without artificial rescaling.
- **Native Exclusions:** Exactly 2,151 particles carry Motive 1; retained as unknown (`destination == 0`), total unknown mass `0.2688750127708772 kg`. Zero relabeled as spill.

---

## 5. Temporal Save Half-Width Discretization Budgets

- **Observation Budget Threshold:** $\Delta t_{\text{save}} / 2 \le 0.00073363908\text{ s}$.
- **Nominal 401 Frames:** Observed max half-width $\approx 0.0050\text{ s} > 0.0007336\text{ s} \implies$ **FAIL** (budget exceeded).
- **Dense 4001 Frames:** Observed max half-width $\approx 0.0005\text{ s} \le 0.0007336\text{ s} \implies$ **PASS** (budget satisfied).
- **Governance Boundary:** A passing save half-width discretization budget satisfies observation resolution requirements only. It does NOT grant Q-N qualification or production acceptance.

---

## 6. Resource & Execution Specifications

- **Runner Request Kind:** `cpu` (`cpu_task_kind: audit`)
- **CPU Reservation:** 2 threads (`cpu_threads: 2`)
- **Max Wall Time:** 3,600 seconds (`max_wall_seconds: 3600`)
- **Estimated Storage Allowance:** 32 GiB (`estimated_storage_bytes: 34359738368`)
- **Scratch Space Requirement:** NVMe with $\ge 100\text{ GiB}$ free space floor.
- **Launch Flag:** `launch_allowed: false`, `launch: false` (staged for Root authorization).
- **Claim Boundaries:** `q_n: not_granted`, `production: none`, `q_i: not_granted`.
