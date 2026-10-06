# fresh111 F3-scoped fresh110 runtime/publication audit

This package is a read-only audit of the committed
`root_followup_110_f3_f6_nvme_renderer_successor_v1` source. It does not
modify fresh110, Root920, the shared renderer controller, the resource ledger,
or any scientific product. It does not open, copy, or hash BI4/H5/CSV/DAT/VTK
payloads and it never launches ParaView.

The audit checks the source manifest and all 24 disabled requests, then
inspects the source-level publication, ledger-lock, path-rebinding, byte-cap,
and process-group contracts. The existing fresh110 toy suite was rerun
separately and passed 5/5.

At capture time Root920 was still the recorded controller PID
`3946798` (`start_ticks=206541429`). Its stdout contained only the independent
preflight line; it had no controller result or child renderer visible. The
shared ledger, read under `resource-ledger.lock`, had zero active reservation
rows, so this audit cannot certify a current reservation match or a completed
publication. That is a live WAIT observation, not a failure or a reason to
retire Root920.

The source audit found three bounded follow-ups for any unattended enabled
binding:

1. fresh110 restores SIGTERM/SIGINT handlers before report rewrite and
   publication. A signal during the Home temporary-copy window can bypass its
   `except Exception` cleanup. Keep own-process cleanup active through final
   publication, or make the publication transaction catch `BaseException` and
   remove its private temporary directory.
2. PVSM rewriting and JSON validation reject the exact staging prefix and
   validate three named report outputs. A future Root adapter should also
   reject any remaining private stage-root/NVMe paths and use path-component
   containment rather than raw `startswith` for final output paths.
3. The final Home-floor check is before `os.replace`; a future adapter should
   record and recheck free space after the atomic publish while holding the
   ledger lock, with an explicit rollback policy.

These are source-audit findings. They do not alter the fresh110 bytes or grant
visual, precision, Q-N, or production credit. `metadata/fresh111-audit-report.json`
is the captured result; `scripts/validate_fresh111.py` reproduces the static
checks and can optionally make a read-only Root920 observation with
`--observe-root920`.

Validation:

```text
python3 scripts/validate_fresh111.py
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

