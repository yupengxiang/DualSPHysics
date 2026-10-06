# F6 fresh155: F2 typed-to-XMF disabled handoff

Observed against Root checkpoint 173. The requested unaccepted F2 render registrations 1063, 1064, 1065, 1097, and 1098 were still live with no terminal receipt; registration 1132 for RX063/ROT075 was also live. The two completed/0 registrations 1066 and 1092 were already accepted and were excluded. This package therefore performs no image review and grants no case credit.

The two disabled requests are deliberately at different readiness states:

- `RX061/ROT105` has a real typed157 completed/0 receipt and conversion report. Its producer physical scope is recorded as `c826...`; the source-owner/source-plan scope `fe08...` remains separate. Root must create the actual binding and reserve an attempt before enabling the N3 XMF worker.
- `RX063/ROT105` has completed native and initial-QA metadata but no terminal typed157 producer. Its source scope is `5fd...`, its prospective legacy scope is `0cbd...`, and its actual converter scope, typed receipt/report, and XMF outputs remain null. It is blocked and must not be enabled.

The request files are sanitized disabled runner contracts. They contain no scientific input-file list or scientific payload digest. The worker contract preserves the original full401/N3 recipe, CPU2 audit policy, output child directory `{attempt_root}/xdmf`, Root-owned inventory guard, and all launch flags disabled. Future XMF/render outputs remain null. JSON metadata and the Python worker source were the only files hashed by this package; no scientific payload was read or rehashed.

Validate with:

```text
python3 scripts/validate_fresh155.py
```

This package is source-only and F6-scoped. It does not modify F2 artifacts, shared scheduling, checkpoints, or ledger state.
