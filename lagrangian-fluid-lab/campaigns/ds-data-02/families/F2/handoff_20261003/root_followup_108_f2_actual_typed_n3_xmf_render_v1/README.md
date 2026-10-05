# F2 fresh108 actual typed to N3 XMF and Root023 render handoff

Fresh108 binds only the currently completed Root typed conversion reports and
execution receipts. The current metadata snapshot selects 16
completed cases and leaves 0 later typed cases deferred until
their producer report is present.

Each selected case has a disabled dynamic N3 XMF request and a disabled Root023
full-401-frame renderer request. XMF dimensions are derived from the actual
conversion report at Root execution: vectors are N 3 and scalars are N. The
renderer keeps all native geometry and asks Root023 to scan every saved frame
for bounds; no camera or domain bounds are prefilled.

The producer H5 path and its conversion-report output_sha256 are bound as an
attestation. The source builder did not read, hash, copy, or decode
H5/BI4/CSV/DAT/VTK payloads. XMF/render receipts, output hashes, canonical
physical scope, Q-N, precision, and production status remain null or ungranted.
Source-plan, actual legacy-owner scope, future converter scope, and canonical
physical binding remain separate.

The package does not launch jobs or modify shared registry/ledger state. Root
must independently review and enable each disabled request.
