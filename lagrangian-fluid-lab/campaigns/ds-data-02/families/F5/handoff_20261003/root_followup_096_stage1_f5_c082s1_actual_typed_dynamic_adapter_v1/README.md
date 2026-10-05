# F5 fresh096: actual typed317/XMF318 dynamic-audit binding

This package binds the actual C082S1 producer metadata for a later Root-owned
51-frame bed-footprint audit. It corrects the worker's physical owner identity
to `F5_COMPACT_STILL_WATER_RUNUP_RECOVERY_C082S1` and preserves the source
mapping `mkbound40 -> native Mk50`.

GenCase293, placement/Mk50 audit315, short native316, typed conversion317,
and XMF export318 all have completed-zero producer receipts. The binding keeps
the complete placement `actual_counts` object, including `solver_dimension` and
`xml_particle_counts`, and separately checks the five scalar particle counts:
194427 total, 158559 fixed, 4210 moving, 0 floating, and 31658 fluid in 3-D.
The typed report is checked as a 51-frame 3-D product with native types
0/1/3 and Mk50. The XMF manifest is bound to the same canonical owner,
source-plan identity, legacy H5 scope, H5 producer digest, typed receipt, and
native receipt.

Canonical physical owner `e691d030...49dbf` and source plan
`5bad3ec9...4fbfa6` remain distinct from the producer legacy H5 scope
`3cd1ceab...44ccd0`; the latter is recorded as
`legacy-owner-scope.v0` with no cross-resolution claim. The H5 digest in the
binding/request is copied from the actual typed317 `output_sha256` field for
Root dispatch revalidation; this source package did not open or rehash H5,
BI4, or CSV arrays.

`workers/bed_audit.py` retains the fresh093 science logic: all 51 frames,
frame-zero Type-3 UID denominator, finite active fluid rows inside the exact
profile x domain and bed y interval `[-0.22, 0.22]` m, diagnostic 1DP/2DP
counts/fractions/depths, and unexplained UID/nonfinite reporting. Its
thresholds remain diagnostic only. The worker was not run here. The disabled
request keeps `execution_allowed=false`, `launch=false`, `full801_authorized=false`,
and future audit output hashes null. Root must register and explicitly enable
it after review; no dynamic penetration or visual acceptance is inferred by
this package.

Run the source-only checks from the F5 worktree:

```text
python3 scripts/preflight_fresh096.py
```

The request uses `cpu_task_kind=audit`, attempt
`root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321`, and
waits on actual XMF318. It is a disabled template for Root's strict runner;
this package starts no job and writes no shared ledger.
