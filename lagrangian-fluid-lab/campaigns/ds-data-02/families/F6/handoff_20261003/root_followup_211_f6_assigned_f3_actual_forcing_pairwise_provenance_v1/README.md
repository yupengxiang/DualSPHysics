# fresh211 actual F3 forcing pairwise provenance

This package is a read-only metadata certificate for the 48 F3 rows in
fresh209.  It resolves each row's producer report from the actual native
receipt: an input report whose `physical_case_id` matches the row is preferred,
with an exact `case_id` fallback for the mother report.  This avoids using a
stale first report from a multi-input native receipt.

The builder hashes only JSON/XML/XMF metadata files and compares their exact
SHA values with the native receipt's launch and after-run maps.  The forcing
CSV is never opened or locally hashed; its SHA is retained only as the
producer-attested value and compared with receipt pins.  All 48 producer
reports have finite numeric `drive_amplitude_G`, `amplitude_x`, `amplitude_y`,
`omega_y`, `phase_y`, and `tau_ramp`.  The resulting 1128 pair records compare
only shared known producer fields.  There are 48 unique forcing tuples, zero
collision groups, and every pair differs on at least one known field.  Numeric
pitch, resolution, time-window, and identifier labels are excluded from the
comparison.

Forty-four native receipts are completed with return code 0 and matching
report/XML launch and after pins.  The four original native-059 rows remain
`running`, have no return code and no after map, and are explicitly recorded
with `after_state=unknown`; their separate Root1449 recovery and Root1435
typed-artifact evidence is not used to rewrite the original receipt.

fresh208 and the Root1456 endpoint proof are retained as direct source roles;
fresh210 supplies the mother and native-059 role closure.  Request/owner
declarations are retained for provenance, while the producer report is the
authoritative forcing source.  Any request-versus-producer mismatch is listed
in the summary and is not silently promoted to a physical result.

Run the standalone certificate validator (67 lines, no imports of producer
workers and no referenced-file reads):

```bash
python3 scripts/validate_pairwise_proof.py --self-test
```

The self-test also rejects a fabricated completion for a running receipt and a
missing producer numeric field.  No CSV, BI4, H5, DAT, VTK, or PNG payload was
read or hashed; no job, ledger, shared-state, case credit, Q-N, or Q-E action
was performed.
