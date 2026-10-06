# fresh164 — M095 Root968 disabled original138 bed binding

This F5-only source package binds the completed M095 metadata chain GenCase root640 → initial placement/Mk50 QA root661 → native root808 → typed root939 → N3 XMF root968 to the unchanged original138 full801 framewise bed worker. M095 has the original `CASE_ID`, so no M086 identity adapter is used.

The request and binding remain `disabled=true`, `execution_allowed=false`, `launch_allowed=false`, `solver_allowed=false`, `full801_authorized=false`, with zero case credit. Root may register the request later through Root142 after reviewing the actual producer closure. The scientific bed thresholds and method remain unchanged: source `mkbound=40`, native bed `Mk=50`, DP `0.02 m`, 801 states, and 1DP/2DP depth bins.

Canonical physical scope `9b51cce0a2f5940a8e6fdf2d284e407dd57f918fad42172eccfd498cbac1eaee`, source-plan scope `56fd284e56eef34a4d842697bbccb51e49f89280b32ec0d47a7af4d9706e899c`, and typed H5 legacy scope `5cf27dc2f732eb1b7f4d1ba2c95880b15f34aadbcd9bbadea9a1020c5db1e3c4` are retained separately with no cross-resolution claim. The typed H5 digest is producer-attested only; source preparation did not open or hash H5, BI4, CSV, DAT, or VTK payloads.

`metadata/fresh164-validator-report.json` is deliberately excluded from the package manifest to avoid self-reference. The validator invokes the original138 metadata verifier against a temporary binding with synthetic Part filenames only; it does not run the bed worker or read scientific payloads.
