# DS-DATA-02 Family F2: Fine Dense-Save Full-4001 Native Event Labels Pipeline Report v2

**Date:** 2026-10-03  
**Family:** F2 (Matched Sloshing / Moving Boundary Dynamics)  
**Case ID:** `F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001`  
**Base Case ID:** `F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001`  
**Status:** Staged for Root CPU Dispatch (Converter 020 live)  
**Errata Reference:** `ERRATA_V1.md` published in v1 handoff directory  

---

## 1. Executive Summary & Root Review Outcome

Root dispatcher reviewed commit `5b1d0f78` (`dense_full4001_event_validation_v1`) and marked it **UNADOPTED**:
- The v1 validation routine defaulted to invented mock event counts (`194457`, `160000`, `25000`, etc.) and destination counts (`135000`, `45000`, etc.), with an in-flight adjustment forcing mass closure.
- Static config declarations were treated as telemetry rather than referencing saved solver telemetry.
- Arbitrary mandatory payload aliases did not match the actual typed contract of the converted trajectory.

In response, the F2 family owner has prepared this **FRESH v2 / v7 Native-Weight Pipeline suite** (`dense_full4001_native_pipeline_v2`):
1. **Preservation of History:** Commit `5b1d0f78` bytes are preserved bitwise in git history without mutation; official errata `ERRATA_V1.md` is published.
2. **Complete Removal of Fabricated Values:** All hardcoded event/destination default counts and closure-by-adjustment logic have been eradicated. Routines fail cleanly (`SourceUnavailableError`) if actual source data is missing.
3. **Saved Telemetry Binding:** Actual save performance is bound directly to `root-offset-fine-dense-full4001-native-save-allocation-021` and `RunPARTs.csv`.
4. **Mandatory 13-Dataset Contract:** Strictly verifies the 13 bitwise invariant datasets from Root actual pose payload 013/014.
5. **Fresh v7 Native-Weight Operator:** Reuses frozen V6 operators and physical geometry while binding non-rescaled actual H5 native float32 MassFluid weights (`0.0001250000059371814` kg, cohort sum `24.576001167297363` kg) and preserving the historical XML decimal benchmark (`24.576` kg) separately without normalization.

---

## 2. Saved Telemetry Verification (Attempt 021)

Root actual native save allocation attempt `root-offset-fine-dense-full4001-native-save-allocation-021` verified the realized solver execution:

| Metric | Realized Value | Contract Budget / Allowance | Margin / Status |
| :--- | :--- | :--- | :--- |
| **Max Save Half-Width** | `0.0005126755832800534` s | `0.0007336390799938275` s | **+30.12% Margin (PASS)** |
| **DTsMin Adjustments** | `0` | `0` | **DTsMin 0 (PASS)** |
| **Native NpOut (Exclusions)** | `2151` | Recorded in telemetry | **Classified unknown_invalid** |
| **Integration Steps** | `201238` | Telemetry verified | **Nominal Symplectic** |
| **Effective CLI Override** | `-tout:0.001` | Overrides nominal XML `0.01` | **Full 4001 Frames** |

> [!IMPORTANT]
> The realized maximum save half-width (`~0.000513` s) natively passes the frozen contract allowance (`0.0007336` s) with a 30.1% safety margin. This is the first fine-resolution simulation in Family F2 to natively pass the temporal quality bracket.

---

## 3. Non-Rescaled Native Mass Precision Authority

Dual mass accounting is strictly maintained:

1. **Authoritative Native float32 Header Mass:**
   - Single particle mass $m_p$: `0.0001250000059371814` kg (widened float32 hex `0x6f120339`).
   - Initial fluid cohort (N=196,608): `24.576001167297363` kg ($M = 24.5760011673$ kg).
   - Source: Authoritative solver saved float32 value from BI4 header / H5 `initial_mass`.
   - **Policy:** NEVER rescaled or normalized to continuous decimal value.

2. **Historical XML Decimal V6 Benchmark:**
   - Single particle mass: `0.000125` kg.
   - Initial cohort sum: `24.576` kg.
   - Source: Historical XML `<massfluid value="0.000125"/>`.
   - **Policy:** Preserved separately as an unnormalized historical reference benchmark.

- **Representation Delta:** $+1.167297\times 10^{-6}$ kg (relative error $\approx 4.75\times 10^{-8}$).

---

## 4. Scientific Event Semantics: Flux vs. Cohort Inventory

In the fresh v7 operator (`f2_rv4eq_fine_dense_full4001_event_semantics_v7.py`):
1. **Dynamic Transition Flux ($\sum N_{\text{events}} \cdot m_p$):**
   - Cumulative transition flux integral across control apertures (moving cup mouth, receiver, tray).
   - Particles splashing or sloshing across boundaries repeatedly increment crossing counters.
   - **Rule:** This flux integral reflects dynamic fluid motion and must NEVER be equated with or forced to equal fluid cohort mass.
2. **Terminal Destination Inventory ($t = 4.0$ s):**
   - Mutually exclusive spatial partitioning into cup, receiver, tray, inflight, and unknown.
   - Strictly accounts for 100% of the initial 196,608 particles without duplicate counting or artificial adjustment.
3. **Unknown Native Exclusions:**
   - 2,151 invalid particles exiting the numerical domain are classified strictly as `unknown_invalid`.
   - `physical_spill_inferred = False`; closed wall crossings = 0; zero physical defect is unasserted.

---

## 5. Mandatory Trajectory Payload (13 Datasets Contract)

Converted trajectories follow the exact typed contract verified in Root payload audit 013/014:
- `time`, `particle_id`, `particle_zone`, `initial_type`, `initial_mk`, `initial_mass`, `mass`, `type`, `mk`, `valid`, `position`, `velocity`, `density`.
- These 13 datasets are retained bitwise-identical before and after separately named rigid pose enrichment (`rigid_body_state`).
- Fluid UID range: strictly 1,470,641 to 1,667,248 (196,608 particles).

---

## 6. Staged Pipeline Requests for Strict Dispatcher

All three requests pass `ds_data02_runtime_v2.validate_request`:
1. `offset_fine_dense_pose_request_v2.json`: Pose enrichment stage (20 verified input files).
2. `offset_fine_dense_labels_request_v2.json`: Fresh v7 native-weight event labels stage (12 verified input files).
3. `f2_rv4eq_fine_dense_full4001_event_validation_request_v2.json`: Event validation stage (14 verified input files).

---

## 7. Claim Boundary

- **Q-I Evidence:** Observation evidence ready; staged for Root dispatcher.
- **Q-N Qualification:** Not assessed (0/336 products across campaign).
- **Production Status:** Not evaluated; no product approval from scripts.
