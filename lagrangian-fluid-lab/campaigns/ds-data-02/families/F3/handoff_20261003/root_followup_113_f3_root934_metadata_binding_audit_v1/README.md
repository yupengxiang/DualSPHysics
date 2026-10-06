# fresh113 Root934 metadata binding audit

This F3-local package audits the already registered Root934 render batch without
starting a worker and without opening, copying, or hashing H5, BI4, CSV, DAT,
VTK, or other scientific payloads. It reads only request JSON, controller
metadata, temporal manifest JSON, execution receipt JSON, and the registered
entry source.

The audit covers the 27 Root934 bindings: 23 F6 requests, three F2 requests,
and one F5 request. It checks the outer runner request against its wrapper,
keeps producer H5 digests as existing metadata attestations, verifies the
canonical source scope and actual converter scope as separate fields, checks
full reservation IDs, and validates the CPU24/env2/renderer-cap2/Home3-GiB
contract. Each actual manifest must provide matching frame and particle counts,
dimension three, and position/velocity N-by-3 metadata. Receipt JSON is read
only to distinguish completed upstream products from the still-running Root934
render batch.

The registered entry is audited separately. Its success exit is valid only
when the library returns `status == "completed"` and
`post_publish_home_floor_rechecked == True`; a library rejection must exit 1.
The existing Root932 toy evidence is retained as the bounded failure-path
proof. No claim of visual acceptance or new case credit is made here.

Run from the F3 worktree with:

```bash
python3 scripts/audit_root934.py
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

The generated report is metadata only. In the current snapshot Root934 has
one observed `renderer_failed`/returncode 1 result, 26 held rows, and zero
render credits. The attempt receipt and bounded launcher stdout are preserved,
while fresh112's rejection record confirms that renderer stderr and the
expanded argv were removed with the private stage. The report therefore does
not infer a ParaView root cause. `metadata/fresh114-logging-proposal.json`
specifies the independent follow-up: capture bounded stderr/stdout, expanded
argv, PID/PGID, and returncode before stage cleanup, then write them into the
rejection evidence. It does not modify fresh112 or retry Root934.
