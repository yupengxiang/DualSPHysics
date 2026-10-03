# Errata and Preservation Notice: Full-4001 Native Pipeline & Event Semantics v7

**Date:** 2026-10-03  
**Status:** UNADOPTED by Root Dispatcher (Scientific Operator Drift Identified)  
**Commit:** `89ac87c081387076938e11b4318b6b2bb3911686` (`f2: publish full4001 event-semantic validation v1 errata and fresh native-weight pipeline v2`)  
**Case ID:** `F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001`  
**Superseded By:** Fresh V8 Wrapper Suite (`f2_rv4eq_fine_dense_full4001_event_semantics_v8.py` / `dense_full4001_native_pipeline_v8`)  

---

## 1. Executive Summary & Root Review Findings

Root dispatcher conducted a line-by-line source comparison of commit `89ac87c0` (v7 event observation implementation in `f2_rv4eq_fine_dense_full4001_event_semantics_v7.py`) against the frozen reference v6 operator (`f2_handoff_20261002_event_semantics_v6.py`).

Root issued an **UNADOPTED** determination:
> "Root reviewed owner 89ac87c0 V7 implementation and cannot adopt its claim of frozen V6 reuse. Source compare shows V7 hardcodes tolerance 0.005 while V6 gets owner quality contract or fallback 0.0125; V7 uses physical_binding.geometry nested defaults because owner geometry is flat, potentially wrong receiver offset 0.14; V7 residence accumulates current destination rectangles instead of frozen V6 trapezoid; source layers altered; full observe operator rewritten and primary V6 invalid-exclusion endpoint semantics omitted. This is scientific operator drift, not native-weight correction. Do NOT execute v7 or rewrite consumed v6 bytes. Preserve 89ac87c0 assets with errata."

---

## 2. Identified Operator Drift Deficiencies in v7

### 2.1 Crossing Tolerance Hardcoding
- **Defect:** In `f2_rv4eq_fine_dense_full4001_event_semantics_v7.py` line 352, tolerance was hardcoded as `tolerance = 0.005`.
- **Reference Semantics (v6):** V6 extracts tolerance dynamically from `owner["quality_contract"]["event_thresholds"]["cup_mouth"]["crossing_tolerance_m"]` with a standard fallback to `0.0125` m (as defined in the Root015 owner metadata).
- **Scientific Impact:** Arbitrarily tightening or changing crossing tolerance alters aperture crossing detection and flux integrals across moving boundary edges.

### 2.2 Nested Defaults vs. Flat Owner Geometry
- **Defect:** V7 parsed geometry via `geom = owner.get("physical_binding", {}).get("geometry", {})` and accessed nested dictionaries `geom.get("cup", {}).get("low_m", [0.0, -0.15, 0.65])` and `geom.get("receiver", {}).get("low_m", [0.45, -0.16, 0.0])`.
- **Reference Semantics (v6):** Owner metadata definitions (`owner.v1.json`, `config.json` from Root015) use flat keys under `geometry`: `cup_low_m`, `cup_size_m`, `receiver_low_m`, `receiver_offset_y_m: 0.14`, `receiver_size_m`, `tray_low_m`, `tray_size_m`.
- **Scientific Impact:** Because `geom.get("receiver")` was empty, V7 relied entirely on hardcoded nested fallbacks rather than binding actual owner geometry, risking misrepresenting the critical offset geometry (`receiver_offset_y_m = 0.14` m).

### 2.3 Destination Residence Numerical Integration Drift
- **Defect:** V7 accumulated destination residence by integrating simple current-step rectangles.
- **Reference Semantics (v6):** Frozen V6 enforces strict trapezoidal numerical integration:
  ```python
  residence_mass_time[code] += 0.5 * (old_mass + new_mass) * dt
  residence_time[code] += 0.5 * (float(np.sum(previous_destination == code)) / n + float(np.sum(destination == code)) / n) * dt
  ```
- **Scientific Impact:** Rectangle integration creates first-order numerical lag drift relative to the frozen second-order trapezoid integral, altering the cumulative residence evidence.

### 2.4 Alteration of Source Layer Encoding
- **Defect:** V7 altered the source layer mapping logic from the initial particle MK partition.
- **Reference Semantics (v6):** Frozen V6 indexes unique sorted `source_mk` values monotonically via `_source_layer(source_mk)`.
- **Scientific Impact:** Distorts spatial stratigraphic layer tracking for fluid particles exiting the tilted cup.

### 2.5 Rewritten Full Observe Loop & Omitted Invalid-Exclusion Endpoint Semantics
- **Defect:** Rather than wrapping the tested V6 operator, V7 completely reimplemented `observe()` from scratch in 768 lines, omitting key invalid-exclusion classification logic, motive ledger binding, and endpoint checks.
- **Scientific Impact:** Unreviewed code modifications introduce untracked bugs and break bitwise provenance comparability with historical V6 runs.

---

## 3. Rectification in V8 Suite

1. **Exact V6 Wrapper:** `f2_rv4eq_fine_dense_full4001_event_semantics_v8.py` imports `f2_handoff_20261002_event_semantics_v6.py` by path as a read-only module. Not a single byte of V6 code is modified.
2. **Narrow Native Mass Hook:** Monkeypatches `_native_mass_reference` ONLY, replacing the XML decimal authority (`0.000125` kg) with the verified native float32 mass from `adapter_mass` (`0.0001250000059371814` kg, total cohort `24.576001167297363` kg) verified against Root017 actual BI4 header precision audit report.
3. **Preserved XML Benchmark:** The continuous XML decimal benchmark ($24.576$ kg) is retained separately as an unnormalized reference benchmark.
4. **Representation Delta Transparency:** The arithmetic representation drift ($\approx +4.75 \times 10^{-8}$) is preserved honestly. No automatic mass gating under $10^{-12}$ nor artificial rescaling is performed. The old frozen $10^{-12}$ diagnostic is reported as `fail`.
5. **Byte-Identical V6 Observe:** All first passage, interpolated cup top aperture, rotation matrices, actual receiver geometry with offset $y = 0.14$ m, original crossing tolerance ($0.0125$ m), source layers, trapezoid residence integration, and invalid/exclusion accounting execute the exact frozen V6 implementation.
6. **Code & Operator Version Hash:** V8 registers operator version `f2-moving-cup-local-z-top-v8-native-mass-bound`, binding the exact code SHA-256 of `f2_handoff_20261002_event_semantics_v6.py` (`e200b886adfd3b4dc69c7e4f281df401d30436be1cba4bf0871f355129f626b9`) and native header bound mass.

---

## 4. Preservation of History

All files in commit `89ac87c0` are preserved bitwise in worktree history for auditability:
- `f2_rv4eq_fine_dense_full4001_event_semantics_v7.py`
- `f2_rv4eq_fine_dense_full4001_event_validation_v2.py`
- `f2_rv4eq_fine_dense_full4001_native_pipeline_v2.py`
- `handoff_20261003/dense_full4001_native_pipeline_v2/*`

Per Root instructions, **V7 files are NEVER executed for scientific evidence**. All downstream executions bind exclusively to V8.
