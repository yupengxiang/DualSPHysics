# F3 fresh072 Root-owned bounded typed-conversion recovery

fresh072 is a source-only, fail-closed recovery variant for the orphaned CPU
conversion reservations. It does not run a converter, read BI4/H5/CSV
payloads, signal a process, release a lease, or write the shared ledger. The
CLI is disabled; Root must review and import the application function in the
integration worktree.

The original runtime-v2 launch receipt records the exact launcher PID in the
reservation and the exact child PID in the receipt. Because runtime-v2 did
not persist `/proc/<pid>/stat` start ticks, each historical
`start_ticks` value is explicitly `null` with provenance
`unknown_historical_start_ticks`. No zero or synthetic anchor is accepted.
`runtime_v2.subprocess.Popen(start_new_session=True)` supplies the bounded
identity that the child is also the process-group leader.

The application accepts only the exact CPU conversion reservation id and
canonical row hash on the original host. It rejects GPU reservations and any
GPU identity. It refuses caller-supplied liveness evidence as stale. After
the exact row is found under `ledger_locked`, it performs two fresh
read-only `/proc` censuses while holding that lock and immediately before
mutation. Both samples must prove a qualified root caller, the same host,
boot id, and PID namespace; every launcher, child, and group-leader PID must
be absent with `ENOENT`; and both complete process-group censuses must be
empty. Any present PID, changing namespace, scan error, or ambiguity refuses
the operation, including AY0270 while its child was live.

After Root review, the application preserves the original receipt bytes as an
exclusive sidecar, writes a prepared journal, removes only the exact dead CPU
reservation, and appends one idempotent charge for the full original reserved
`cpu_core_seconds`. The attempt becomes `interrupted_unfinalized`; child
returncode remains `null`, tool status 143 is recorded separately, and OS
exit 0 is never claimed. A committed replay is a no-op. Runtime limits,
deadline, adoption, counters, other reservations, and other attempts are
checked for byte-equivalent preservation.

The P03 strict CPU artifact worker and request are copied byte-for-byte from
fresh071 and remain disabled. Their independent worker returncode 0, if Root
executes that audit later, cannot rewrite the old conversion receipt or
reclassify its unknown child returncode. The concrete Root166 disabled
integration binding is in
`requests/root166_p03_artifact_integrity_binding.json`.

Run the synthetic semantic checks with:

```text
python3 -B tests/test_fresh072_reconciliation.py
```
