# F3 fresh147 native-receipt scope closure

This package is a read-only metadata sidecar for the current 48-case F3
roster. It records, case by case, the native execution receipt and the role of
each physical-condition digest. It does not grant visual credit, precision
qualification, Q-N/Q-E, or production credit.

The closure is based on the 48 rows in the immutable full336 roster and the
checkpoint183 state. It finds 44 native receipts with `completed/0` and four
accepted P1000 native receipts that remain `running` with a null return code:

- `F3_STAGE1_DP006_P1000_AY0320`
- `F3_STAGE1_DP006_P1000_AY0390`
- `F3_STAGE1_DP006_P1000_AY0460`
- `F3_STAGE1_DP006_P1000_AY0570`

Recovered typed, artifact-audit, and animation receipts for those four rows
are retained as alternate evidence. They never relabel the original native
receipt as completed.

The report keeps these scopes in separate fields:

- `source_plan_scope`: the source-plan/recipe identity when it is actually
  present in the source evidence;
- `native_canonical_scope`: derived from the native request or an explicit
  owner-native binding;
- `actual_converter_legacy_scope`: the converter/legacy-owner scope used by
  downstream metadata, when present;
- `accepted_decision_top_hash`: preserved with its recorded role, even when
  that role is legacy rather than native canonical.

Two cases are called out because they have caused integration mistakes before.
For AY0340, the accepted-decision top hash is the legacy owner scope
`4b831d05...`, while the native/source-plan scope is `f8c54693...`. For AY0270,
the current roster canonical field is null, but its render request and native
125 receipt carry the concrete native condition `a6a7dfcc...`; the independent
artifact audit 1166 and XMF 1193 are listed separately, and the original 154
conversion receipt remains nonterminal.

Run the metadata-only validator from this directory:

```text
python3 metadata/validate_scope_closure.py --synthetic
```

The validator opens only JSON metadata and hashes only those JSON files. It
does not follow `output_root`, H5, BI4, CSV, DAT, VTK, PNG, XMF payload, or
other scientific-data paths. It checks receipt/request case and physical
identity, declared JSON digests, the 44/4 completion split, pending render
bindings, and the AY0270/AY0340 role contracts.

`metadata/package-manifest.json` closes the bytes of this package itself; it
intentionally excludes its own file to avoid a self-referential digest.

The authoritative roster, checkpoint, receipts, requests, and shared ledger
are unchanged. No solver, converter, renderer, or shared-state mutation was
performed for this package. No new visual review was claimed; at package time
there was no newly published completed render available for personal review.
