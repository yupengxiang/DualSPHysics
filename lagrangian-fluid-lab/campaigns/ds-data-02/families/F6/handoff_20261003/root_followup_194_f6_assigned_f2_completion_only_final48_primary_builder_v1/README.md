# F6 fresh194: F2 completion-only final48 primary builder

This F6-scoped package is a reusable metadata-only builder and read-only validator for the F2 final48 primary delivery. It consumes four explicit JSON inputs and joins cases by the immutable `Root1276/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json` order. It preserves `frozen8 ⊂ actual24 ⊂ registered48`; it never sorts, reselects from directories, treats aliases as new physics, or redefines first24 from the accepted count.

The frozen inputs are checkpoint 282, the current Root1375 full336 index, the Root1276 F2 membership, and the Root1330 legacy 42-accepted/6-pending catalog. The current authority contains 44 accepted F2 decisions and four still-pending rows:

- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075`
- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090`
- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090`
- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT090`

The current run therefore writes only `metadata/current-readiness/fresh194-readiness.json`. It refuses to emit `F2-FINAL48-COMPLETE-PRIMARY-DELIVERY.json` until all 48 current rows have an accepted decision and every accepted row has a complete case-local native, typed, XMF/XML, render report/receipt, and visualization reference set. Pending rows remain readiness-only and receive no primary visual reference or credit. The older Root1330 six-pending boundary is retained as compatibility provenance; current accepted decisions take precedence for rows that became accepted after that catalog.

Every accepted decision is checked against the supplied checkpoint's exact `accepted_decisions` path list and SHA, and its original `status`, `family_id`, `case_id`, and `physical_case_id` must match the current index. Accepted statuses are limited to `visual-approved-by-root` and `visual-approved-by-delegated-agent`. The output keeps native canonical, actual typed/converter legacy, XMF condition/physical plan, SourceDef, source-plan field presence/absence, original/recovery receipt status, and partial-runtime observations in separate role-labelled fields. It preserves the F2 baseline native count distinction (421566 where present versus 418104 in the later production rows), the P03 recovery-aware path, the old P03 typed/runtime unknowns, and the source175 initial-QA semantic correction without promoting any unknown runtime state.

JSON metadata is read and hashed. XMF/XML and published PNG references are checked by existence/stat; PNG bytes are not opened or hashed. H5, BI4, IBI4, CSV, DAT, VTK, VTU, and PVTU payload paths are rejected before open/hash. No solver, converter, renderer, scientific QA, registry, ledger, or case-credit operation occurs. Numeric precision, Q-N, Q-E, strict containment, all-UID survival, and mass equality remain unclaimed; native/typed/XMF scope hashes and absent fields are never reconciled by filling one namespace from another.

Run the builder into a new output directory:

```sh
python3 scripts/build_fresh194.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_282.json \
  --current-index /abs/path/full336-current313-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json \
  --output-dir /abs/path/new/fresh194-output
```

Validate the same boundary without writing into this package:

```sh
python3 scripts/validate_fresh194.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_282.json \
  --current-index /abs/path/full336-current313-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json \
  --package-dir /abs/path/root_followup_194_f6_assigned_f2_completion_only_final48_primary_builder_v1
```

The package is assigned to F6 but its actual physical rows are F2. It produces no new acceptance, Q-N/Q-E, production approval, or shared-state update.
