# F5 C082S1 fresh093 short51 pipeline

This source-only F5 handoff keeps the analytic C082S1 XML, motion and canonical physical identity unchanged. The actual GenCase producer is `root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293` with `194427` native 3-D particles (`158559` fixed, `4210` moving, `0` floating, `31658` fluid). The native bed marker is Mk50 from source `mkbound=40`.

Root319's actual stage-one placement/Mk50 audit is bound in `metadata/root319-placement-mk50.json`. It passed all basic placement checks, 15 fluid y levels, no initial below-bed/outside-box fluid and central Mk50 support counts `[208, 27, 22, 15, 20, 20]`. Its exact-DP lattice residual (`5.000000015797923e-06` cells against `1e-6`) remains a numerical-precision failure and is not relabelled or used as a dynamic acceptance gate.

Root324 completed the Root-owned native short attempt `root-stage1-f5-c082s1-solid-fluid-recovery-short-native-qualification-316` with return code 0. `metadata/actual-short-native-316.json` records its receipt and all 51 `solver_output/data/Part_0000.bi4` through `Part_0050.bi4` filenames from directory metadata only. No native array bytes or hashes are included.

The disabled downstream chain is:

1. `requests/typed-conversion-request.json` — NVME conversion, CPU2, exact actual count axis `194427`, all 51 saved states and native Mk50/type identity; future conversion report/H5 hashes are null.
2. `requests/xmf-request.json` — legacy-aware full temporal XMF sidecar. It preserves the canonical owner hash separately from the producer H5 legacy scope and uses the reviewed exporter only after a real conversion.
3. `requests/dynamic-bed-audit-request.json` — allowlisted CPU `audit` worker. It scans every actual 0..1 s frame, every initial Type-3 UID, exact bed profile x and y footprint, 1DP/2DP counts/fractions/depths, nonfinite/lost UIDs and unexplained states. Thresholds are diagnostic only.
4. `requests/render-root023-request.json` — Root023's verified renderer, all 51 frames, native fields and time axis preserved. Camera bounds are absent so the renderer scans all actual valid native points.

All four requests have `execution_allowed=false`, `launch_allowed=false`, `solver_allowed=false`, `full801_authorized=false`, and future product hashes null. Root must bind actual typed/conversion/XMF products before enabling downstream requests. The short right-censored result does not authorize the 16 s/801-frame run or add an independent case.

Run only the metadata preflight (no arrays, jobs or ParaView):

```text
python3 scripts/preflight_fresh093.py
```

No shared ledger, registry, consumed source file or previous attempt is modified by this package.
