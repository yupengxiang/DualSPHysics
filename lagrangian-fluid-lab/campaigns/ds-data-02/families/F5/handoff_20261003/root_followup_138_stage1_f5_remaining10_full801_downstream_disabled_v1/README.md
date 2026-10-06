# F5 fresh138: ten Root808 full801 downstream bindings (disabled)

This source-only pack binds the ten non-T120 C082S1 conditions `M085_T090, M085_T100, M095_T080, M095_T090, M095_T100, M105_T080, M105_T090, M105_T100, M115_T080, M115_T090` to their own completed Root808 full801 native request/receipt, their own Root640 GenCase receipt/prepared report, and their own Root661 initial placement/Mk50 QA metadata. The Root808 controller attests 10 requested, 10 completed/0, 801 saved states per case, pending_held=0, and independent_case_increment=0.

Each case has a disabled typed NVMe request, legacy-aware N3 XMF binding/request, full 801 framewise Mk50 bed-audit binding/request, and Root023 render binding/request. Future typed H5, conversion report, XMF, bed-audit and render hashes remain null. The downstream requests do not reuse either endpoint native attempt; every request points to the matching Root808 request/receipt and matching `root_followup_119_stage1_f5_c082s1_actual_gencase640_initial_qa_disabled_v1` GenCase/QA closure.

Source preparation did not read, copy, or hash BI4, DAT, H5, CSV, VTK, or solver payloads. Producer-attested payload digests remain opaque metadata. All requests are `disabled=true`, `execution_allowed=false`, `launch_allowed=false`, and `solver/conversion_allowed=false`; Root owns any later derivation and strict registration. The generic bed worker retains the exact profile, all-801 UID denominator, Mk50 mapping, 1DP/2DP diagnostics, nonfinite/lost UID reporting, and no-threshold-relaxation policy.

T120 (`M085_T120, M095_T120, M105_T120, M115_T120`) is excluded because its forcing endpoint is 19.2 s and is not contained in this 0..16 s / 801-state package. The historical A/B penetration failures and exact-DP 5e-6-vs-1e-6 negative are retained; no Q-N or new case credit is granted.

## Handoff

* source plan: `metadata/fresh138-source-plan.json`
* Root808 selected metadata: `metadata/root808-controller-summary.json` and `metadata/case-attestations/*.json`
* bindings/requests: four disabled downstream entries per tag
* workers: `workers/export_xmf_legacy_aware_fresh138.py`, `workers/bed_audit_full801_fresh138.py`
* validator: `scripts/validate_fresh138.py`
