# DS-DATA-02 Family F2: Prospective Native-Weighted Temporal Save Comparison Report v1

**Report Identifier:** `f2-rv4eq-fine-native-weighted-save-comparison-prospective-v1`  
**Date:** 2026-10-04  
**Family:** F2 (Sloshing / Moving Cup Dynamics)  
**Author:** F2 Family Delegated Owner (Gemini 3.8 Flash High)  
**Nominal Run (401 Frames):** `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001` (`root-offset-fine-full401-frozen-events-native-weights-024`)  
**Dense Run (4001 Frames):** `F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001` (`root-offset-fine-full4001-frozen-events-native-weights-025`)  
**Authoritative Operator Version:** `f2-moving-cup-local-z-top-v8-native-mass-bound`  
**Underlying Frozen V6 Base:** `f2_handoff_20261002_event_semantics_v6.py` (SHA-256 `e200b886adfd3b4dc69c7e4f281df401d30436be1cba4bf0871f355129f626b9`)  
**Operator SHA-256:** `ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406`  
**Physical Mother Condition SHA-256:** `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef`  
**Scientific Claim Boundary:** Prospective specification and evidence audit only; `q_i` not granted, `q_n` not assessed, production `none`. Pre-execution audit without direct manipulation of raw HDF5 arrays.  

---

## 1. Executive Summary & Problem Context

Root Followup 036 authorizes Family F2 to prepare the prospective scientific comparison suite and runner binding between the two completed native-weighted Root label runs:
1. **Nominal-Save Baseline (401 Frames, $dt = 0.010$ s):** Attempt `root-offset-fine-full401-frozen-events-native-weights-024` in `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001`.
2. **Dense-Save Benchmark (4001 Frames, $dt = 0.001$ s):** Attempt `root-offset-fine-full4001-frozen-events-native-weights-025` in `F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001`.

Both runs terminated with exit code `0` (`terminal_status: completed`) in the Root strict shared runner environment. Both runs executed the frozen `v8` operator (`f2-moving-cup-local-z-top-v8-native-mass-bound`) wrapping the frozen `v6` observer math with exact native mass authority ($m_p = 0.0001250000059371814$ kg).

This prospective report establishes:
- The exact verification of continuum physical invariance across both runs.
- The evaluation of the strict temporal save half-width budget ($0.00073363908$ s).
- The cross-audit of destination inventories, residence times, and cumulative mass fluxes.
- The mathematical formulation of stable ordered episode semantics and chord matching that strictly avoids naive zipping of repeat count mismatches.
- The execution contract, guarded private-copy lifecycle, resource reservations, and governance boundaries for Root review prior to full-array dispatch.

---

## 2. Continuum & Operator Invariance

Both runs represent the same physical continuum reality under fine discretization ($dp = 0.005$ m, $N_{\text{fluid}} = 196,608$ particles):

| Verification Item | Nominal 401 (`024`) | Dense 4001 (`025`) | Invariance Status |
| :--- | :--- | :--- | :--- |
| **Physical Condition SHA-256** | `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef` | `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef` | **Identical** |
| **Geometry SHA-256** | `dc2f2d1ab3d842a25fd8025a33b1c81920e1caebe0fd354fbff68bfa89b3e9a9` | `dc2f2d1ab3d842a25fd8025a33b1c81920e1caebe0fd354fbff68bfa89b3e9a9` | **Identical** |
| **Control SHA-256** | `c500385285845193cb16f526499b9450bc1691f9744e63e1b03c15fb996eff82` | `c500385285845193cb16f526499b9450bc1691f9744e63e1b03c15fb996eff82` | **Identical** |
| **Motion Control SHA-256** | `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` | `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` | **Identical** |
| **Operator Version** | `f2-moving-cup-local-z-top-v8-native-mass-bound` | `f2-moving-cup-local-z-top-v8-native-mass-bound` | **Identical** |
| **Operator Code SHA-256** | `ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406` | `ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406` | **Identical** |
| **Time Window** | $4.000003024029022$ s ($4.0$ s) | $4.000003024029022$ s ($4.0$ s) | **Identical** |
| **Fluid Particle Count** | $196,608$ | $196,608$ | **Identical** |
| **Cup Low Bounding Box (m)** | $[0.0, -0.15, 0.65]$ | $[0.0, -0.15, 0.65]$ | **Identical** |
| **Cup High Bounding Box (m)** | $[0.425, 0.15, 1.10]$ | $[0.425, 0.15, 1.10]$ | **Identical** |
| **Receiver Bounding Box (m)** | $[0.45, -0.16, 0.00]$ to $[1.55, 0.44, 0.45]$ | $[0.45, -0.16, 0.00]$ to $[1.55, 0.44, 0.45]$ | **Identical** |
| **Tray Bounding Box (m)** | $[-1.20, -1.00, -0.20]$ to $[2.80, 1.00, -0.05]$ | $[-1.20, -1.00, -0.20]$ to $[2.80, 1.00, -0.05]$ | **Identical** |
| **Motion Axis Origin (m)** | $[0.0, -1.0, 0.65]$ | $[0.0, -1.0, 0.65]$ | **Identical** |
| **Motion Axis Unit Vector** | $[0.0, 1.0, 0.0]$ | $[0.0, 1.0, 0.0]$ | **Identical** |

---

## 3. Native Mass Authority vs Continuous XML Benchmark

### 3.1 Arithmetic Provenance & Delta
Both runs enforce authoritative native float32 mass authority derived from DualSPHysics `JSph.cpp` solver headers (`MassFluid = (float)ctes.GetMassFluid()`):
- **Native Single-Particle Weight:** $m_p = 0.0001250000059371814$ kg (`0x6f120339`).
- **Native Cohort Total Mass:** $M_{\text{cohort}} = 196,608 \times m_p = 24.576001167297363$ kg.
- **Continuous XML Benchmark:** $M_{\text{XML}} = 24.576000000000000$ kg.
- **Arithmetic Delta:** $\Delta M = +1.1672973627696592 \times 10^{-6}$ kg.
- **Relative Arithmetic Drift:**
  $$\frac{|\Delta M|}{M_{\text{XML}}} = \frac{1.1672973627696592 \times 10^{-6}}{24.576} = 4.749745128457272 \times 10^{-8}$$

### 3.2 Preservation of Legacy 1e-12 Diagnostic Failure
The legacy campaign quality contract specifies a mass relative budget of $1.0 \times 10^{-12}$. Because the relative drift ($\approx 4.75 \times 10^{-8}$) exceeds this threshold, the diagnostic fails:
- **Nominal 401 Diagnostic Status:** `"fail"` (preserved honestly).
- **Dense 4001 Diagnostic Status:** `"fail"` (preserved honestly).
- **Scientific Policy:** Neither run rescales native mass or fabricates an artificial pass. The unnormalized continuous XML benchmark remains preserved alongside the authoritative native float32 mass.

---

## 4. Strict Temporal Save Half-Width Discretization Budget

The campaign quality contract dictates an event time absolute budget $\tau_{\text{budget}} = 0.0036681953999691376$ s and a maximum save fraction allowance of $0.20$:
$$\text{Budget}_{\text{half-width}} = 0.0036681953999691376 \times 0.20 = 0.0007336390799938275\text{ s}$$

### 4.1 Evaluation of Completed Runs

| Save Configuration | Save Interval $\Delta t_{\text{save}}$ | Nominal Half-Width | Observed Half-Width Range | Budget Compliance | Determination |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Nominal 401 (`024`)** | $0.010$ s | $0.00500$ s | $0.00498935$ s – $0.00501285$ s | Exceeds Budget ($> 0.0007336$ s) | **FAIL** |
| **Dense 4001 (`025`)** | $0.001$ s | $0.00050$ s | $0.00048616$ s – $0.00051268$ s | Within Budget ($\le 0.0007336$ s) | **PASS** |

### 4.2 Detailed Event Bracket Statistics by Code (from Observations)

| Event Code | Event Name | Nominal 401 Half-Widths | Nominal Status | Dense 4001 Half-Widths | Dense Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `1` | `cup_top_departure` | $[0.00499121, 0.00500882]$ s | fail | $[0.00048790, 0.00051217]$ s | pass |
| `2` | `cup_top_return` | $[0.00499770, 0.00500284]$ s | fail | $[0.00049414, 0.00050422]$ s | pass |
| `3` | `receiver_entry` | $[0.00498935, 0.00501285]$ s | fail | $[0.00048616, 0.00051268]$ s | pass |
| `4` | `receiver_exit` | $[0.00498981, 0.00501285]$ s | fail | $[0.00048660, 0.00051268]$ s | pass |
| `5` | `tray_entry` | $[0.00498981, 0.00501285]$ s | fail | $[0.00048616, 0.00051268]$ s | pass |
| `6` | `tray_exit` | $[0.00498981, 0.00501285]$ s | fail | $[0.00048616, 0.00051268]$ s | pass |

### 4.3 Governance Boundary on Discretization Pass
> [!IMPORTANT]
> **Strict Governance Rule:** Meeting the save half-width discretization budget ($0.00051268\text{ s} \le 0.00073364\text{ s}$) confirms that the temporal bracket resolution satisfies the quality contract specification. However, **this does NOT grant Q-N convergence** or imply numerical convergence of fluid continuum fields. No arbitrary CDF or percentage threshold can be substituted as a convergence gate. Q-N remains `not_granted` and production approval remains `none`.

---

## 5. Aggregate Destination Mass Inventories & Native Exclusions

### 5.1 Terminal Destination Inventories at $t = 4.0$ s

| Destination | Code | Particles (Nominal) | Mass (kg, Nominal) | Particles (Dense) | Mass (kg, Dense) | Delta Mass (kg) | Bitwise Match |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `unknown` | `0` | 2,151 | $0.2688750127708772$ | 2,151 | $0.2688750127708772$ | $0.0000000000000000$ | **Bitwise Identical** |
| `cup` | `1` | 0 | $0.0000000000000000$ | 0 | $0.0000000000000000$ | $0.0000000000000000$ | **Bitwise Identical** |
| `receiver` | `2` | 24,411 | $3.0513751449325355$ | 24,411 | $3.0513751449325355$ | $0.0000000000000000$ | **Bitwise Identical** |
| `tray` | `3` | 161,580 | $20.197500959329773$ | 161,580 | $20.197500959329773$ | $0.0000000000000000$ | **Bitwise Identical** |
| `inflight` | `4` | 8,466 | $1.0582500502641778$ | 8,466 | $1.0582500502641778$ | $0.0000000000000000$ | **Bitwise Identical** |
| **Total** | — | **196,608** | **24.576001167297363** | **196,608** | **24.576001167297363** | **0.0000000000000000** | **Bitwise Identical** |

### 5.2 Native Exclusion Invariance
- **Total Excluded Identities:** Exactly $2,151$ particles in both runs.
- **Motive Distribution:** $100\%$ Motive 1 (DualSPHysics domain boundary exit).
- **Physical Spill Inference:** `False`. In both runs, native Motive 1 exclusions are retained strictly as `unknown` (`native_invalid_after_open_top_or_domain: 512,310` frame-particle records; `native_invalid_legal_tray_candidate: 1,236`).
- **Closed Wall Crossings:** $0$ closed-wall crossing segments detected.

---

## 6. Residence Mass-Time & Cohort Fraction Comparison

Residence mass-time is computed via the frozen second-order trapezoid rule:
$$I_{\text{dest}} = \int_0^T M_{\text{dest}}(t) \, dt \approx \sum_{k=0}^{K-1} \frac{1}{2} \left[ M_{\text{dest}}(t_k) + M_{\text{dest}}(t_{k+1}) \right] \Delta t_k$$

| Destination | Nominal Mass-Time (kg·s) | Dense Mass-Time (kg·s) | Absolute Delta (kg·s) | Relative Delta | Nominal Cohort Frac | Dense Cohort Frac |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `unknown` | $0.64058595$ | $0.64064849$ | $+6.2536 \times 10^{-5}$ | $+9.76 \times 10^{-5}$ | $0.02606551$ | $0.02606805$ |
| `cup` | $27.45432942$ | $27.45284916$ | $-1.4803 \times 10^{-3}$ | $-5.39 \times 10^{-5}$ | $1.11711947$ | $1.11705924$ |
| `receiver` | $8.98516266$ | $8.98500045$ | $-1.6221 \times 10^{-4}$ | $-1.81 \times 10^{-5}$ | $0.36560719$ | $0.36560059$ |
| `tray` | $48.96935906$ | $48.96907679$ | $-2.8226 \times 10^{-4}$ | $-5.76 \times 10^{-6}$ | $1.99256823$ | $1.99255674$ |
| `inflight` | $12.25464189$ | $12.25650409$ | $+1.8622 \times 10^{-3}$ | $+1.52 \times 10^{-4}$ | $0.49864263$ | $0.49871840$ |

The relative delta across all destinations is on the order of $10^{-5}$ to $10^{-4}$, confirming that aggregate fluid residence trajectories are remarkably stable between nominal and dense temporal saves.

---

## 7. Event Ledger & Boundary Flux Analysis

### 7.1 Cross-Resolution Event Comparison

| Code | Event Name | Nominal Count | Dense Count | Delta Count | Nominal Flux (kg) | Dense Flux (kg) | Delta Flux (kg) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `1` | `cup_top_departure` | 189,939 | 189,940 | $+1$ | $23.742376$ | $23.742501$ | $+0.000125$ |
| `2` | `cup_top_return` | 23 | 24 | $+1$ | $0.002875$ | $0.003000$ | $+0.000125$ |
| `3` | `receiver_entry` | 121,991 | 164,872 | $+42,881$ | $15.248876$ | $20.609001$ | $+5.360125$ |
| `4` | `receiver_exit` | 97,580 | 140,461 | $+42,881$ | $12.197501$ | $17.557626$ | $+5.360125$ |
| `5` | `tray_entry` | 806,356 | 1,071,635 | $+265,279$ | $100.794505$ | $133.954381$ | $+33.159877$ |
| `6` | `tray_exit` | 644,776 | 910,055 | $+265,279$ | $80.597004$ | $113.756880$ | $+33.159877$ |

### 7.2 Physical Interpretation of Event Discrepancies
1. **Cup Top Boundary Stability:** The departure and return counts differ by exactly **$+1$ particle** ($+0.000125$ kg). This confirms that cup emptying dynamics are governed by large-scale body motion rather than high-frequency boundary flutter.
2. **Paired Sub-Grid Flutter:**
   - **Receiver Entry/Exit:** $\Delta N_{\text{entry}} = +42,881$ and $\Delta N_{\text{exit}} = +42,881$. The net flux difference is identically zero ($\Delta N_{\text{entry}} - \Delta N_{\text{exit}} = 0$).
   - **Tray Entry/Exit:** $\Delta N_{\text{entry}} = +265,279$ and $\Delta N_{\text{exit}} = +265,279$. The net flux difference is identically zero ($\Delta N_{\text{entry}} - \Delta N_{\text{exit}} = 0$).
   - **Mechanism:** Particles splashing near liquid-gas or liquid-boundary interfaces cross the geometric boundary planes back and forth in rapid succession. At $dt=0.010$ s, nominal sampling misses rapid intra-step roundtrips. At $dt=0.001$ s, the dense observer captures every micro-chord excursion.

---

## 8. Mathematical Specification: Stable Ordered Episode Semantics

### 8.1 Rejection of Naive Zipping
> [!CAUTION]
> **Prohibited Anti-Pattern:** A naive `zip(events_nom, events_dense)` blindly pairs the $i$-th nominal event with the $i$-th dense event. When dense sampling captures 42,881 additional flutter events, zipping causes a progressive phase shift where an event at $t=1.2$ s in nominal is erroneously matched to a flutter event at $t=0.8$ s in dense. **Naive zipping of mismatched counts is strictly prohibited.**

### 8.2 Chronological Bracket-Overlap Matching Algorithm
Let $S_{\text{nom}}^{(p, c)} = \langle u_1, u_2, \dots, u_m \rangle$ be the chronological list of events for particle $p$ under event code $c$.  
Let $S_{\text{dense}}^{(p, c)} = \langle v_1, v_2, \dots, v_k \rangle$ be the corresponding dense list.

1. **Candidate Match Condition:** A candidate pair $(u_i, v_j)$ is eligible for joint matching if:
   $$[t_{\text{before}}(u_i), t_{\text{after}}(u_i)] \cap [t_{\text{before}}(v_j), t_{\text{after}}(v_j)] \neq \emptyset \quad \text{OR} \quad |t(u_i) - t(v_j)| \le \Delta t_{\text{nom}} = 0.010\text{ s}$$
2. **Greedy Chronological Pairing:** For each nominal event $u_i$, select the unmatched dense event $v_j$ satisfying the candidate condition that minimizes $|t(u_i) - t(v_j)|$.
3. **Classification of Events:**
   - **Genuinely Joint Events:** Matched $(u_i, v_j)$ pairs. For each joint event, compute time shift $\delta t = t(v_j) - t(u_i)$ and bracket narrowing ratio $(t_{\text{after}}(v_j) - t_{\text{before}}(v_j)) / (t_{\text{after}}(u_i) - t_{\text{before}}(u_i)) \approx 0.10$.
   - **Repeated / Boundary Flutter Events:** Unmatched dense events $v \in S_{\text{dense}}$ that occur within $2 \Delta t_{\text{nom}}$ of a matched joint event (representing sub-grid oscillation).
   - **New Transient Events:** Unmatched dense events $v \in S_{\text{dense}}$ in isolated time windows where no nominal crossing occurred.
   - **Missing Events:** Unmatched nominal events $u \in S_{\text{nom}}$ with no corresponding dense crossing.
4. **Transit Chord Analysis:**
   For receiver ($c_{\text{in}}=3, c_{\text{out}}=4$) and tray ($c_{\text{in}}=5, c_{\text{out}}=6$), pairs of successive entry and exit events define a transit chord:
   $$\tau_{\text{chord}} = t_{\text{exit}} - t_{\text{entry}}$$
   Compare chord transit durations $\Delta \tau_{\text{chord}} = \tau_{\text{chord}}^{\text{dense}} - \tau_{\text{chord}}^{\text{nom}}$ for matched entry-exit pairs.

---

## 9. Computational & Resource Budget Bounds

The scientific comparison worker is prepared for future Root shared runner dispatch under strict constraints:
- **Runner Request Schema:** `ds02.runner-request.v2`
- **Execution Mode:** CPU audit (`kind = "cpu"`, `cpu_task_kind = "audit"`)
- **CPU Threads:** 2 (`cpu_threads = 2`)
- **Max Wall Time:** 3,600 seconds (`max_wall_seconds = 3600`)
- **Estimated Storage:** 8 GiB (`estimated_storage_bytes = 8589934592`)
- **Launch Gating:** `launch = false`, `conversion_launch_forbidden = true`, `status = "prospective_staged_for_root_cpu_dispatch"`.
- **Scratch Space & Private-Copy Policy:**
  - Operating on H5 labels (~1.1 GiB for nominal, ~10.9 GiB for dense).
  - Scratch directory: `/tmp/ds02-f2-save-comparison` (cap 16 GiB).
  - One guarded private copy created in scratch; strictly cleaned up on exit.
  - Zero access to the raw 60 GiB trajectory files is required.

---

## 10. Governance & Root Review Summary

1. **Pre-Execution Submission:** All configurations, request JSONs, sidecars, and worker implementations are committed locally in isolated branch `codex/ds-data-02-f2`.
2. **Review Barrier:** Root must review this prospective specification before scheduling actual full-array execution.
3. **Scientific Claims:**
   - `q_n`: **not_granted**
   - `production`: **none**
   - `q_i`: **not_granted; post-labels observation cross-comparison**
