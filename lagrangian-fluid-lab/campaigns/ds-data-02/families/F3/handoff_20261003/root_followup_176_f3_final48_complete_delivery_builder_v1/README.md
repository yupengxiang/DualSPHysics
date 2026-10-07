# fresh176 F3 final48 delivery builder

This package is a reusable, metadata-only handoff for the eventual F3 final48 primary delivery. It accepts explicit paths for the live checkpoint, the current full336 role-aware index, the frozen Root1276 F3 membership, the previous F3 primary catalog, and a new output directory. It joins rows by the immutable `physical_case_id` in Root1276's registered order. It never sorts cases, selects a directory alias, or redefines first8/first24 from the accepted count.

At the frozen input snapshot used for this package, F3 has 42 accepted decisions and 6 pending registrations. Running the builder therefore writes only `fresh176-readiness.json`; it deliberately does not create `F3-FINAL48-COMPLETE-PRIMARY-DELIVERY.json`. The final catalog is emitted only when all 48 current rows have an authoritative accepted decision and each accepted row has a complete own native/typed/XMF/render primary reference set. Pending rows carry no primary visual references and no credit.

Run the current metadata boundary with:

```sh
python3 build_fresh176.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_267.json \
  --current-index /abs/path/full336-current307-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F3-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json \
  --output-dir /abs/path/new/fresh176-output
```

Validate the same inputs without writing into the package:

```sh
python3 validate_fresh176.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_267.json \
  --current-index /abs/path/full336-current307-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F3-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json
```

The builder reads and hashes JSON metadata only. XMF/XML and published PNG references are existence/stat checks; PNG strings and `{path, ...}` dictionaries are both accepted. H5, BI4, IBI4, CSV, DAT, VTK, VTU, and PVTU paths are rejected before open/hash. The builder preserves native canonical, typed legacy, XMF plan, source-plan, SourceDef, old runtime-unknown, recovery-audit, and missing-field roles separately. It does not turn a request/plan into a terminal receipt. The Root1348 source209 report-digest correction is accepted only when its correction sidecar agrees with the observed case-local JSON report bytes; the consumed source decision remains unchanged.

`fresh176-readiness.json` is a metadata boundary report, not a visual decision and not a case-credit update. `Q_N`, `Q_E`, new case credit, numerical precision acceptance, scientific jobs, and shared ledger writes remain zero/false.
