# fresh187 — F2 remaining-six actual-401 readiness

This F6 handoff is a metadata-only readiness index for the six F2 rows that Root1326 records as `original-render-registered-still-pending`: RX049/ROT075, RX053/ROT090, RX056/ROT090, RX061/ROT090, RX063/ROT090, and RX063/ROT105. The physical family is F2; this package is assigned to the F6 worker.

Each row binds its own completed/0 native receipt, GenCase and initial-QA JSON/XML evidence, completed typed conversion report/receipt, actual N3 XMF manifest/XML/receipt, independent XMF/typed review JSON, registered render request, loaded wrapper, controller launch record, and the current PID/start-ticks observation. The actual render receipt and publish receipt remain null because all six original controllers are still pending. The old envelope fields are retained as history and do not override the actual 401-frame wrapper contract.

Native request condition, canonical source condition, typed/XMF legacy scope, and XMF source-plan field presence are recorded separately. Missing particle counts and unknown omission causes come from each case's own metadata; no case inherits another case's statistics. GenCase/initial-QA records retain their original `not_assessed`/no-precision/no-production claim.

The package contains no scientific payload and grants no visual credit, Q-N/Q-E, precision, or production approval. Validate with:

```text
python3 scripts/validate_fresh187.py
```
