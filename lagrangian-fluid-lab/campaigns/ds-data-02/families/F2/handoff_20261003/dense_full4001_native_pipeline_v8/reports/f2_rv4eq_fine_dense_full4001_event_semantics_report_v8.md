# DS-DATA-02 Family F2: Fresh V8 Event Semantics Wrapper Report

**Report Identifier:** `f2-rv4eq-fine-dense-full4001-event-semantics-report-v8`  
**Date:** 2026-10-03  
**Case ID:** `F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001`  
**Family:** F2 (Matched Sloshing / Moving Boundary Dynamics)  
**Author:** F2 Family Delegated Owner (`gemini-3.8-flash-high`, high effort)  
**Operator Version:** `f2-moving-cup-local-z-top-v8-native-mass-bound`  
**Operator Schema:** `ds-data-02.f2.event-semantics.v8`  
**Underlying Frozen V6 Base:** `f2-moving-cup-local-z-top-v6` (`f2_handoff_20261002_event_semantics_v6.py`, SHA-256 `e200b886adfd3b4dc69c7e4f281df401d30436be1cba4bf0871f355129f626b9`)  
**Operator SHA-256:** `ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406`  
**Scientific Claim Boundary:** Evidence generation only; `q_i` not granted, `q_n` not assessed (0/336 campaign production). Zero raw array analysis outside Root runtime.  

---

## 1. Executive Summary & Context

Root reviewed owner commit `89ac87c0` (the initial v7 event observation implementation) and issued an **UNADOPTED** determination due to scientific operator drift. Rather than reusing the frozen v6 operator bytes, the v7 implementation rewrote the observation operator from scratch, inadvertently introducing 5 critical points of scientific divergence:
1. Hardcoded crossing tolerance ($0.005$ m) instead of obtaining tolerance from owner quality contract or fallback ($0.0125$ m).
2. Looked up geometry in `physical_binding.geometry` nested dictionaries where owner geometry is flat (`receiver_low_m`), failing and falling back to hardcoded defaults that compromised the receiver offset ($y = 0.14$ m).
3. Destination residence accumulated simple current-step rectangles rather than the frozen v6 second-order trapezoid rule ($0.5 \times (\text{old} + \text{new}) \times dt$).
4. Source layers were altered from monotonic unique MK indexing.
5. The full observe routine was rewritten and omitted primary v6 invalid-exclusion endpoint semantics.

This document establishes the fresh **V8 wrapper suite** (`f2_rv4eq_fine_dense_full4001_event_semantics_v8.py`) which rectifies all identified deficiencies by wrapping the EXACT existing `f2_handoff_20261002_event_semantics_v6.py` operator without altering a single consumed byte.

---

## 2. Changed Function Boundaries & Narrow Monkeypatch Architecture

In strict adherence to Root directives, V8 isolates changes to **native-weight authority ONLY**:

| Component / Function | Frozen V6 Reference | V7 Drift (Unadopted) | Fresh V8 Wrapper (Adopted) |
| :--- | :--- | :--- | :--- |
| **Code Implementation** | `f2_handoff_20261002_event_semantics_v6.py` | Full rewrite (768 lines) | Path import of V6 read-only; monkeypatch narrow hooks only |
| **Mass Authority Function** | `_native_mass_reference(owner, count, adapter_mass)` using XML decimal | Reimplemented with static constants | Hooked `_native_mass_reference_v8` using actual `adapter_mass` ($0.0001250000059371814$ kg) |
| **Crossing Tolerance** | Dynamic lookup from quality contract, fallback `0.0125` m | Hardcoded `0.005` m | Untouched frozen V6 (`_owner_geometry`), preserves `0.0125` m |
| **Geometry Authority** | Flat `owner["geometry"]` keys (`cup_low_m`, `receiver_low_m`, offset $0.14$ m) | Nested `geom.get("receiver", {})...` | Untouched frozen V6 (`_owner_geometry`), exact offset $y = 0.14$ m |
| **Residence Integration** | Trapezoidal rule: $0.5 \times (m_{\text{old}} + m_{\text{new}}) \times dt$ | Rectangle accumulation: $m_{\text{new}} \times dt$ | Untouched frozen V6 trapezoidal integration |
| **Source Stratification** | `_source_layer(source_mk)` monotonic sorted MK partition | Custom altered logic | Untouched frozen V6 `_source_layer` |
| **Invalid Accounting** | Measurement-only unknown loss; motive breakdown | Incomplete endpoint checks | Untouched frozen V6 observe loop & invalid checks |
| **Operator Spec & Version** | `f2-moving-cup-local-z-top-v6` | `f2-...-v7-native-weight` | `f2-moving-cup-local-z-top-v8-native-mass-bound` binding exact V6 code SHA |

---

## 3. Native Mass Authority & Representation Provenance

### 3.1 Verification against Root017 BI4 Header Precision Report
DualSPHysics stores fluid particle mass as an IEEE-754 binary32 scalar in solver compute kernels (`JSph.cpp` line 654: `MassFluid = (float)ctes.GetMassFluid()`), widened to double when writing output headers.

For the fine resolution case ($dp = 0.005$ m, $N_{\text{fluid}} = 196,608$):
- **Native float32 particle weight:** $0.0001250000059371814\text{ kg}$ (`0x6f120339`).
- **Native cohort sum ($196,608 \times m_{\text{native}}$):** $24.576001167297363\text{ kg}$.
- **Continuous reference mass ($M_{\text{cont}}$):** $24.576000000000000\text{ kg}$.
- **Arithmetic representation delta ($\Delta M$):** $+1.1672973627696592 \times 10^{-6}\text{ kg}$.
- **Relative arithmetic drift:** $+4.749745128457272 \times 10^{-8}$ ($\approx +4.75 \times 10^{-8}$).

### 3.2 Correction of Native vs Continuous Semantics
1. **No Automatic 1e-12 Gating:** The relative drift ($4.75 \times 10^{-8}$) exceeds the legacy strict cell-center budget ($1.0 \times 10^{-12}$). In V8, this representation delta is recognized as physical IEEE-754 arithmetic reality.
2. **Honest Diagnostic Failure:** The old frozen $10^{-12}$ diagnostic is honestly reported as `"fail"` in `strict_native_vs_continuous_status`. It is **never** artificially converted to a pass or used to trigger silent rescaling.
3. **No Rescaling or Normalization:** Converted HDF5 arrays and native observation ledgers retain exact binary32 values without normalization.
4. **Separate XML Decimal Benchmark:** The continuous XML decimal values ($m = 0.000125\text{ kg}$, $M = 24.576\text{ kg}$) are retained distinctly under the `xml_decimal_benchmark` key in report metadata.

---

## 4. Preservation of 89ac87c0 Assets with Errata

In strict compliance with campaign rules:
1. All assets committed in `89ac87c0` remain bitwise preserved in git history under `handoff_20261003/dense_full4001_native_pipeline_v2/`.
2. Official errata document `ERRATA_V2.md` is committed alongside them, detailing the Root review finding and forbidding execution of v7 files.
3. V8 wrapper suite becomes the sole adopted execution authority.
