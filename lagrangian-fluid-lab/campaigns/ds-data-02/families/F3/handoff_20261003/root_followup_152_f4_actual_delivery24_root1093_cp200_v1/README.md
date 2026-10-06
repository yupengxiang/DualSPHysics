# fresh152 F4 actual delivery24 from Root1093 and checkpoint-200

This F3-scoped metadata package defines the main-process delivery subset for F4. It keeps the eight rows in the frozen Root1093 `FIRST8_PER_FAMILY_STAGE1_SUBSET56.json` order, then appends the first sixteen unseen F4 physical IDs in the order of checkpoint-200 `accepted_decisions`. Identity is `physical_case_id`; selection does not use lexical, directory, alias, or source-plan sorting.

Each of the 24 selected decision records is read as JSON metadata and records a 1201-frame visual-approved decision with an independent-case increment of one. The package preserves the decision path and digest, observed time window/count fields, and the available source/canonical/actual-converter scope role fields without equating those scopes. It does not reissue visual decisions or grant numerical precision, Q-N, or Q-E.

The delivery set is a subset of the 48 F4 IDs selected from checkpoint 200, and its first eight are exactly the frozen Root1093 rows. It intersects the current F4 exact24 source plan in 19 IDs; five delivered accepted IDs are outside that source-plan set and five source-plan IDs are absent. The exact24 source plan therefore remains a separate source/prospective set. The historical root053 candidate8 and fresh151 reconciliation are retained as evidence only; the historical candidate has zero case-count increment and does not fill the delivery list.

A metadata-only priority check found no newly published unaccepted F3 render eligible for personal visual review at checkpoint 200. No PNG, BI4, H5, CSV, DAT, or VTK payload was opened or hashed. No simulation, conversion, rendering job, shared-index update, ledger write, or new case credit was performed.

Run the validator from this package directory:

```text
python3 scripts/validate_fresh152.py
```

The main process may use this package to freeze its own delivery manifest after its independent integration review. This package itself is not a global delivery or credit update.
