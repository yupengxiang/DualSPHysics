# DS-DATA-02 Family F2: 3DP Matched OFFSET Spatial Transport Comparison Report v2

**Document Identifier:** `f2-rv4eq-matched-offset-3dp-spatial-comparison-report-v2`  
**Date:** 2026-10-03  
**Family:** F2 (Matched Sloshing / Moving Boundary Dynamics)  
**Author:** F2 Family Delegated Owner (`gemini-3.8-flash-high`, high effort)  
**Scope:** `F2_RV4EQ_MATCHED_OFFSET_3DP_SPATIAL_REFERENCE_STUDY`  
**Physical Condition Hash:** `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef` (bitwise preserved)  
**Motion Control Digest:** `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` (bitwise identical)  
**Status:** ALL THREE RESOLUTIONS COMPLETED (Coarse 012, Medium 012, Fine 015). Staged for Root runner dispatch.

---

## 1. Executive Summary & Series Overview

This report executes the definitive 3DP spatial transport cross-comparison across all three completed resolutions of the preregistered matched OFFSET configuration under the full 4.0-second event window:
- **Coarse ($dp = 0.010\text{ m}$):** [`root-offset-coarse-actual-native-labels-v2-012`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010/root-offset-coarse-actual-native-labels-v2-012) ($N = 421,566$, fluid $= 24,576$)
- **Medium ($dp = 0.008\text{ m}$):** [`root-offset-medium-actual-native-labels-v2-012`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010/root-offset-medium-actual-native-labels-v2-012) ($N = 668,673$, fluid $= 48,000$)
- **Fine ($dp = 0.005\text{ m}$):** [`root-offset-fine-actual-native-labels-v1-015`](file:///home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001/root-offset-fine-actual-native-labels-v1-015) ($N = 1,667,249$, fluid $= 196,608$)

All observations are bound to the actual canonical V6 labels observation reports and completed execution receipts. Canonical keys extracted directly:
- `source_population`
- `final_mass_kg_by_destination`
- `native_exclusion_and_boundary`
- `native_exclusion_ledger`
- `event_ledger`
- `residence`
- `qi_evidence`
- `q_n`

| Resolution | Case Identifier | Particles (Fluid / Total) | Labels H5 Size | Actual Observation Source | Execution Receipt SHA |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **COARSE** | `F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010` | 24,576 / 421,566 | 134.1 MB | `8f9e8eaa5dc05548...` | `52f23bf5b214a8e6...` |
| **MEDIUM** | `F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010` | 48,000 / 668,673 | 266.3 MB | `68ce2efd82a4f227...` | `dce28a271466403e...` |
| **FINE** | `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001` | 196,608 / 1,667,249 | 1,076.7 MB | `f1cb455db7e23fe7...` | `a5c892ccf245bf38...` |

---

## 2. Final Destination Mass Distribution (4.0 s Window)

Authoritative mass accounting from the frozen V6 XML decimal ledger ($24.576\text{ kg}$ total cohort):

| Destination Zone | Coarse Mass (kg / %) | Medium Mass (kg / %) | Fine Mass (kg / %) | Spatial Transport Trend |
| :--- | :--- | :--- | :--- | :--- |
| **Receiver ($y=+0.14\text{ m}$ Offset)** | 3.7870 kg (15.41%) | 3.4842 kg (14.18%) | 3.0514 kg (12.42%) | Asymptotic capture convergence |
| **Catch Tray** | 20.4360 kg (83.15%) | 20.7124 kg (84.28%) | 20.1975 kg (82.18%) | Primary catchment (~82–84%) |
| **In-Flight** | 0.2350 kg (0.96%) | 0.2719 kg (1.11%) | 1.0583 kg (4.31%) | Higher fine spray droplet retention |
| **Cup Residue** | 0.0000 kg (0.00%) | 0.0000 kg (0.00%) | 0.0000 kg (0.00%) | 100% complete cup evacuation |
| **Unknown Loss (Domain Exit)** | 0.1180 kg (0.48%) | 0.1075 kg (0.44%) | 0.2689 kg (1.09%) | Bounded solver domain exit loss |
| **Total Cohort Sum** | **24.5760 kg (100.0%)** | **24.5760 kg (100.0%)** | **24.5760 kg (100.0%)** | **Exact Decimal Conservation** |

### 2.1. Unknown Loss Mass Integrity & Policy
- **Coarse Unknown Loss:** `0.118000 kg` (118 particles, 0.48%)
- **Medium Unknown Loss:** `0.107520 kg` (210 particles, 0.44%)
- **Fine Unknown Loss:** `0.268875 kg` (2,151 particles, 1.09%)
- **Scientific Policy Invariant:** Native invalid particles exiting the simulation domain remain classified strictly as `unknown_invalid`. Zero physical defect is NOT claimed; no unearned Q-N grant is made. Missing mass is never silently defaulted to 0 or None.

---

## 3. First Passage Dynamics & Residence Times

### 3.1. First Event Occurrence Times (s)

| Event Code / Description | Coarse First Time | Medium First Time | Fine First Time | Discretization Invariance |
| :--- | :--- | :--- | :--- | :--- |
| **Cup Top Departure** | 0.8793 s | 0.8797 s | 0.8894 s | Consistent slosh spill onset |
| **Receiver Entry** | 0.8699 s | 0.8698 s | 0.8598 s | Rapid leading-edge transfer |
| **Catch Tray Entry** | 1.1199 s | 1.1199 s | 1.1200 s | Identical gravitational fall time |
| **Receiver Exit (Splash Spill)** | 1.0598 s | 1.0598 s | 1.0598 s | Identical first splash egress frame |
| **Tray Exit (Secondary Splash)** | 1.1599 s | 1.1599 s | 1.1599 s | Identical tray impact frame |

### 3.2. Integrated Cohort Residence Mass-Time (kg·s)

| Destination Zone | Coarse Mass-Time (kg·s) | Medium Mass-Time (kg·s) | Fine Mass-Time (kg·s) | Fine Cohort Fraction (s / 4.0s) |
| :--- | :--- | :--- | :--- | :--- |
| **Cup Interior** | 27.712 | 29.667 | 27.454 | 1.117 s |
| **Receiver Interior** | 11.771 | 10.516 | 8.985 | 0.366 s |
| **Tray Interior** | 49.192 | 50.535 | 48.969 | 1.993 s |
| **In-Flight** | 9.357 | 7.392 | 12.255 | 0.499 s |
| **Unknown Loss** | 0.271 | 0.195 | 0.641 | 0.026 s |

---

## 4. Quality Contract Compliance & Negative Evidence Disclosures

### 4.1. Save Bracket Budget Allocation Failure (Negative Evidence)
- **Frozen Contract Save Half-Width Budget:** `0.0007336390799938275 s` ($0.7336\text{ ms}$)
- **Executed Simulation Save Interval:** `0.010 s` (effective bracket half-width $\approx 0.0050\text{ s}$)
- **Compliance Status across All 3 Resolutions:** **FAIL** across all event codes (`cup_top_departure`, `cup_top_return`, `receiver_entry`, `receiver_exit`, `tray_entry`, `tray_exit`).
- **Allocation Policy:** This negative evidence is reported honestly without relaxing contract gates or synthesizing fake passes.
- **Dense-Save Remediation Strategy:** Candidate [`F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001`](file:///home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/dense_save_fine_strategy_v1/definitions/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001.xml) (4001 frames, $\text{TimeOut} = 0.001\text{ s}$, effective half-savewidth $0.0005\text{ s} < 0.0007336\text{ s}$) has been staged for Root review and GPU dispatch.

### 4.2. Converted-Native Float32 vs XML Decimal Reference Weights
- **XML Decimal Continuous Reference:** $24.576\text{ kg}$ (exact cohort sum across all resolutions)
- **Coarse H5 Float32 Adapter Mass:** `24.576001167297 kg` (delta `+1.1673e-06 kg`, rel `+4.75e-08`)
- **Medium H5 Float32 Adapter Mass:** `24.575999937952 kg` (delta `-6.2048e-08 kg`, rel `-2.52e-09`)
- **Fine H5 Float32 Adapter Mass:** `24.576001167297 kg` (delta `+1.1673e-06 kg`, rel `+4.75e-08`)
- **Representation Delta:** IEEE-754 single-precision float32 rounding in solver kernels and HDF5 storage is documented explicitly and separated from integer-count event ledgers.
