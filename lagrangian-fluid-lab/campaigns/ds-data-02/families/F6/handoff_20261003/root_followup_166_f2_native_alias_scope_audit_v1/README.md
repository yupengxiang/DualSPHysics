# F2 fresh166 native-request alias and scope audit

This F6 handoff is a bounded metadata-only audit of the 13 F2 rows that
Root1205 explicitly left unresolved for native-request scope. All 13 rows are
already accepted legacy visual rows in that frozen index. The audit preserves
the exact `physical_case_id` and `case_id` pair from Root1205 and records that
the former is the physical identity; it never turns a case label, retry, or
resolution alias into a new physical case.

For every row, the accepted decision/top condition, source-declared fields, and
actual native-request role are separate objects. The unresolved native scope
remains `null` with an empty candidate list. No accepted decision hash or source
field is copied into the native role, and no missing field is replaced with
zero. The unresolved state is metadata alias absence, not a scientific failure.

The render census scanned the existing F2 animation-report metadata. The only
Root1205-unaccepted row with a complete published report is RX058/ROT105, which
was already personally reviewed in fresh164. No new personal visual review was
started in fresh166. The last original F6 Root951 handle remains a live pending
case and was not restarted or converted into a wait-only package.

Run:

```text
python3 scripts/validate_fresh166.py
```

This package grants no case credit, starts no job, and performs no scientific
payload I/O.
