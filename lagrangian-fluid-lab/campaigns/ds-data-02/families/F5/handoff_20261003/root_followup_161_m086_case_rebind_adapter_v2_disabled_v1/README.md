# fresh161 — M086 case rebind adapter v2 (disabled)

Fresh159 correctly materialized the M086 producer identity in its binding, but its adapter left the imported fresh138 worker module global `CASE_ID` at the base C082S1 value. The actual fresh138 `_verify_bound_metadata` gate therefore rejects the producer binding before the scientific audit. Fresh161 is a distinct source package; fresh159 is unchanged.

The adapter verifies the original fresh138 worker bytes have SHA `89be048d…b550e2`, loads that exact module, changes only its in-memory `CASE_ID` to `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34`, and then calls the original `main` with the unchanged numerical worker. It does not edit receipts, arrays, H5/XDMF payloads, geometry, thresholds or consumed bindings. The `--check` regression keeps a stub identity check, then invokes the unchanged original `_verify_bound_metadata` on a temporary fixture made from actual JSON/XML metadata after the rebind and reaches the original XMF-manifest checks. Empty `Part_*` names are used only as toy frame-name placeholders; no H5/BI4/CSV/DAT/VTK payload is opened or hashed.

The request and binding remain disabled. Root must bind the actual XMF metadata before registration, then review full801 bed/render evidence separately.

The producer binding now carries `initial_qa_output_root` copied from the actual completed initial-QA receipt. The only fields allowed to be filled later by Root are that receipt-derived output root and actual downstream XMF identity/provenance fields (`xmf_manifest`, `xdmf`, `xmf_receipt`, their metadata hashes, and `xmf_attempt_id`). Execution/source/physics flags and all producer counts, receipts, hashes, thresholds, and marker mappings remain immutable.

The `actual_counts` object is copied exactly from the actual M086 initial-QA report. Its numeric fixed/moving/fluid/floating/total values are unchanged; this removes only the old binding's extra `data2d: false` bookkeeping key so the unchanged original gate's exact object comparison can pass. The fresh158/fresh159 bytes remain preserved as historical evidence.
