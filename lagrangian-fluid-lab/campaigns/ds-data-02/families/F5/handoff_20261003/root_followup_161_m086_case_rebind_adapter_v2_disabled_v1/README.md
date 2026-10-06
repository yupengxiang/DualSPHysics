# fresh161 — M086 case rebind adapter v2 (disabled)

Fresh159 correctly materialized the M086 producer identity in its binding, but its adapter left the imported fresh138 worker module global `CASE_ID` at the base C082S1 value. The actual fresh138 `_verify_bound_metadata` gate therefore rejects the producer binding before the scientific audit. Fresh161 is a distinct source package; fresh159 is unchanged.

The adapter verifies the original fresh138 worker bytes have SHA `89be048d…b550e2`, loads that exact module, changes only its in-memory `CASE_ID` to `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34`, and then calls the original `main` with the unchanged numerical worker. It does not edit receipts, arrays, H5/XDMF payloads, geometry, thresholds or consumed bindings. The `--check` regression executes a stub `original.main` that observes the module/binding identity match and also verifies the real module starts with the expected base constant.

The request and binding remain disabled. Root must bind the actual XMF metadata before registration, then review full801 bed/render evidence separately.
