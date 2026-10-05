# F1 fresh099: Root497 actual typed conversion to disabled N3 XMF

This source-only package binds the 24 fresh098 F1 full-native typed requests to actual Root497 conversion metadata when a producer report and completed/0 receipt exist. At generation time, 8 cases are completed/0 and 16 remain waiting; waiting cases retain null producer scope/H5/report hashes.

The copied `workers/export_xmf.py` is the frozen N3 writer used by the successful XMF460/411 path. Requests pass both `expected_frames` and `expected_native_frames`, require `{attempt_root}/xdmf` as an empty output directory, and preserve vector `N 3` / scalar `N` through `outshape = shape[1:]`. The actual conversion report supplies `hash_scopes.physical_condition_sha256` and its producer scope schema. Source canonical owner, source-plan hash, and legacy H5 scope remain separate; no equality is asserted.

All XMF and Root023 render requests are disabled, with future output hashes null. The source package did not read or hash H5, BI4, CSV, DAT, or scientific arrays.

Run the metadata-only verifier from this package before Root enables any request:

```text
python3 scripts/verify_fresh099_metadata.py .
```
