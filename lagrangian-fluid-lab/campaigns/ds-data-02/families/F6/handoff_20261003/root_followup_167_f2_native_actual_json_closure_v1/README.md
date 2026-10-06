# F2 fresh167 native actual JSON closure

This F6 handoff follows each of the 13 F2 rows that Root1205 marked as
native-request-scope unresolved through its own accepted-decision JSON chain.
It opens only declared JSON receipts and conversion reports. For every available
native receipt it records the actual request `case_id`, `physical_case_id`, the
actual `physical_condition_sha256` when present, and the true absence when the
field is missing. It also records whether an actual `physical_binding` object or
safe path alias is present; no binding is synthesized.

The accepted decision condition and the actual native request condition are
kept as separate roles. Four first24 native requests have a condition hash that
differs from the accepted semantic hash, and that actual hash is retained. The
coarse legacy row has a true absent native condition in its receipt. Three
RX047 rows have no accepted-chain native receipt declaration; the missing chain
is preserved. Ten conversion reports were followed through
`source_provenance.solver_receipt`; all declared JSON hashes were checked
against the corresponding metadata files.

No new unreviewed F2 published render was found. RX058/ROT105 remains the only
historically unaccepted published report in this scan and was already reviewed
in fresh164. The last Root951 F6 handle remains pending and was not restarted.

Run:

```text
python3 scripts/validate_fresh167.py
```

This package does not read or hash scientific payloads, start jobs, modify
shared state, or grant case credit.
