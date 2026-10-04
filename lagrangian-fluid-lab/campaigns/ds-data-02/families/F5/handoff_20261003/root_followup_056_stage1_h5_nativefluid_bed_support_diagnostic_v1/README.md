# F5 Stage 1 H5/native-fluid bed-support diagnostic

This fresh scope prepares a bounded diagnostic worker for Root's strict
dispatcher.  It binds the existing F5 runup full-typed H5 from original013,
the exact Root055 compact runup physical condition, and the continuous bed
profile used by the generated XML.  The worker is source-only in this commit:
it has not opened H5/BI4/CSV arrays, run a solver or converter, or rendered a
plot.

The future worker scans all 801 native frames and retains every `valid &&
type==3` row in the count, mass, and UID denominators.  It records finite
position status, x-domain and y-flume membership, finite mass, sorted UID
digests, and piecewise-bed distances.  Distances greater than 1 DP (`0.02 m`)
and 2 DP (`0.04 m`) are diagnostic bins only.  The report keeps out-of-domain
and nonfinite rows visible, never masks or drops them, and does not infer a
root cause, rescale a coordinate, or grant Q-N.

Frame zero also receives extrema and occupancy summaries at the exact bed-node
x planes.  A Root-authorized invocation writes ordinary matplotlib x/z
overlays for frames 0, 400, and 800 with the continuous profile overlaid and
the >1-DP diagnostic points highlighted.  The overlay is a geometry diagnostic
and is separate from the existing ParaView visual evidence.

The exact compact runup bed nodes are:

```text
(-0.2, 0.0), (2.0, 0.0), (3.0, 0.28), (3.6, 0.448),
(3.9, 0.448), (4.4, 0.05), (4.8, 0.05)
```

Root must review the binding and source before changing `launch_allowed`.
`request.json` is deliberately `launch_allowed=false`; no numerical result,
bed-penetration count, visual pass, or production approval is claimed here.

The earlier Root026 three-frame display is retained as context only.  Its
late-frame appearance suggested a possible bed crossing while the far-side
wall obscured part of the profile; that observation is unconfirmed and is not
used as a result in this scope.  The existing macro failures and unknown
native exclusions remain historical evidence and do not establish this
geometry diagnosis.

Source-only API checks use a tiny in-memory synthetic frame:

```bash
python3 scripts/nativefluid_bed_support_diagnostic.py --check
python3 -m pytest -q tests/test_nativefluid_bed_support_diagnostic.py
```

Neither command opens the bound H5, BI4, CSV, XDMF, STL, or motion source.
