# F3/F4 material T2 CPU source/window audit

The independent read-only audit is complete. It reopens the retained HDF5
artifacts on CPU, scans every saved F3 source frame and trace frame, checks
checkpoint provenance, recomputes per-source terminal unknown mass and first
failure reasons, and audits each retained F4 result. It submits no job, starts
no solver or GPU work, and does not modify the registry, ledger, or historical
F3/F4 scores.

The machine-readable artifact is
`campaigns/core-v1/material/evidence/f3-f4-t2-cpu-source-window-audit-v1-20260920.json`.
Its SHA256 is
`983e15aae8e1ce4df705590c7b1cc89e27a0445c8152f4a003123392e3aaa279`.
The artifact schema is `core.material.t2.cpu_source_window_audit.v1` and its
qualification claim and credit are both `none`.

## Denominators and integrity

- F3 rows: 2, each with 4,096 geometric seeds and two source denominators of
  2,048. Both complete source H5 files have 836 frames and 34,560 particles.
- F4 retained cases: 6, each with 512 geometric seeds. The source denominator
  is every seed carrying the declared source label; no contact or reliable-only
  subset is used.
- Both F3 source files and both F3 traces pass byte-hash, schema, full time-axis,
  finite active-field, mass-closure, reader-binding, and checkpoint checks.
- All six F4 traces pass byte-hash, schema, time-axis, seed-weight closure,
  monotone reliability, reader-binding, and checkpoint checks.

## Gate results

| Gate | Result | Evidence |
|---|---:|---|
| Source/reader/reconstruction integrity | pass | 2 F3 rows and 6 F4 cases |
| Per-source unknown mass <= 1% | fail | F3 and every F4 case exceed the limit |
| F3 CDF sup difference <= 0.02 | fail | retained bounds are 0.06005859375–0.06103515625 |
| F4 event window complete | fail | all six retained cases are right-censored or unresolved |
| T2 macro/path qualification | false/false | diagnostic audit only |

F3 row 29 has source 0 unknown mass 25/2,048 = 0.01220703125 and source 1
19/2,048 = 0.00927734375. Its first failures are frame 456 with one
`low_effective_sample_size` and 24 `wall_occluded`, and frame 394 with 19
`wall_occluded`, respectively. Row 31 has source 0 unknown mass 32/2,048 =
0.015625 and source 1 29/2,048 = 0.01416015625. Its first failures are frame
281 with four `low_effective_sample_size`, one `no_support`, and 27
`wall_occluded`, and frame 237 with three `low_effective_sample_size` and 26
`wall_occluded`, respectively. Full source mass closure and native trace mass
matching pass for both rows.

The six F4 unknown fractions are 0.84765625, 0.896484375, 0.896484375,
0.923828125, 0.955078125, and 1.0 in the retained case order. Failure classes
are recorded per case in the JSON; the aggregate classes are unknown mass,
reconstruction error, wall/visibility failure, and unresolved/right-censored
event window.

## Validation

```text
tests/test_f3_f4_t2_cpu_source_window_audit_v1.py: 8 passed
```

The T2 blocker remains scientific evidence: the fixed unknown-mass and F3 CDF
gates fail, every retained F4 event window is incomplete, and no independent
material calibration/acceptance record exists. This audit preserves those
failures and grants no qualification credit.
