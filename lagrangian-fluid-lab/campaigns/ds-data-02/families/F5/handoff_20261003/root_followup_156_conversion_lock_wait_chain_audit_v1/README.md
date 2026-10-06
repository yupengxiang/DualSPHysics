# F5 fresh156: conversion-lock wait-chain audit and safe handoff

This is a source-only, metadata-only audit taken at `2026-10-06T10:49:40.488134+00:00` from F5 commit `2776ccd2` (fresh155). It did not start, stop, signal, retire, replace, or restart a controller, and it did not open, hash, copy, or decode BI4/H5/CSV/DAT/VTK or other science payloads.

## Lock owners

- `stage1-fullnative-conversion-dispatch.lock`: Root854 PID 3840219 is owner. Its log records M095_T080 acquiring the lock; M085_T100 is completed/0 and retained. Seven live waiters are Root864, Root865, Root872, Root877, F3 Root879, F3 Root885, and F2 Root891.
- `stage1-fullnative-native-registration.lock`: F3 Root884 PID 3885447 owns it; F5 Root871 PID 3868473 waits.
- `stage1-fullnative-render-registration.lock`: F4 Root924 PID 3952170 owns it. Root920's controller had exited after its renderer work by the snapshot, while its Root142 reservation/metadata was retained; Root924 was the live render-lock owner. The retained Root920 attempt is protected and was not retired or reused.

The resource ledger is accounting only. At this snapshot it has one Root924 renderer reservation (24 CPU threads, 12 GiB output admission); the earlier Root920 controller has exited and its metadata is retained. OS locks plus live PID/start-tick observations provide lock ownership. A changing or empty ledger reservation list is not proof that a conversion lock is free.

## F5 handoff

Root854 remains the only current conversion owner. Its queue is M095_T080, then M095_T090, M095_T100, M105_T080, M105_T090, M105_T100, M115_T080, and M115_T090, with the 32 GiB estimate and 16 GiB wait margin unchanged. Completed Root820/Root854/Root864 typed outputs remain immutable.

Next34 has 23 native completed/0 and 11 native tags pending. Root871 reports `pending_not_launched=5`, while seven native request files have no result and the overall pending roster is 11. This is a metadata mismatch, not a launch instruction. Only M086_T095 (Root864) and M098_T085 (Root872) have concrete typed requests among the untyped native-ready cases. Root865 and Root877 have concrete downstream XMF requests for typed M086_T085 and M085_T100. Root873 has no request or receipt and must not be filled by inference.

## Safe action

Keep every live owner/waiter and all completed receipts/results. After Root854 reaches a real terminal state, Root may continue its existing queue under unchanged Root142 lock/storage guards. Any independent 4 GiB successor needs a new attempt/reservation and actual producer metadata; this package registers none and leaves future hashes null. Fresh155 remains byte-exact; `_report_bytes` and `SystemExit`/partial cleanup repair belongs to distinct fresh157.

Validate without touching runtime state:

```bash
python3 -B scripts/validate_fresh156.py
```
