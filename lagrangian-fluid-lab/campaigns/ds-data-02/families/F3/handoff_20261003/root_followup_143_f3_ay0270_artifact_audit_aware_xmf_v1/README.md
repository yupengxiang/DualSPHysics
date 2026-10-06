# F3 fresh143: AY0270 audit-aware full836 XMF handoff

This package prepares a disabled, Root-owned CPU2/serial1 XMF request for
`F3_STAGE1_DP006_P1000_AY0270`. Root1166 independently audited the existing
trajectory and returned zero after checking all 836 frames, 835 transitions,
179208 particles, N-by-3 position/velocity, UID lifecycle, type/Mk ledgers,
finite fields, and the producer H5 digest. That audit is a new evidence role.

The original typed conversion attempt remains preserved separately: its
`execution-receipt.json` still says `status: running` and has no `returncode`
field. The binding therefore exposes four roles explicitly:

- `original_conversion_receipt`: unresolved old attempt, never rewritten;
- `artifact_audit_receipt` and `artifact_audit_report`: independent Root1166
  completed/0 audit evidence;
- `native_receipt`: the completed/0 native full836 receipt; and
- `conversion_report`: producer metadata, which does not settle the old OS
  lifecycle.

The new adapter does not call the old exporter with a fabricated typed receipt.
It verifies the immutable fresh104 `export_xmf.py` source and reuses its
`FIELDS`, HyperSlab/DataItem writer, temporal frame loop, N3 geometry and
read-only H5 check. Its preflight checks the separated receipt roles and
canonical native scope versus `legacy-owner-scope.v0` converter scope. During a
future Root CPU job, it reads the same immutable trajectory H5 and writes only
an XMF/manifest sidecar; it never edits the old receipt, audit report, native
receipt, conversion report, or H5.

`--metadata-preflight` was run successfully. The package is source-only and
contains no H5/BI4/CSV/DAT/VTK payload. The H5 digest is copied as Root1166 and
producer attestation only; this source review did not open or hash the H5.
Future XMF/manifest/visual hashes remain null, `case_credit` is zero, numerical
precision is not accepted, and no Q-N or production approval is granted.
