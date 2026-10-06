# F6 fresh130 delegated visual acceptance

This package records the delegated visual review of
`F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025` from the repaired Root951
render attempt. The actual receipt is `completed/0`, with 241 source frames
and 241 rendered frames. I personally viewed all 11 contact sheets and the
nine requested keyframes at frames `0, 30, 60, 90, 120, 150, 180, 210, 240`
using `view_image`.

The rendered sequence keeps the tank boundary, blue fluid, and red floating
body visible through the full 0–12 s window. The early splash and later body
pose changes remain inside the native-bounds camera views. I saw no blank
contact sheet, missing requested keyframe, obvious camera crop, or renderer
artifact. The delegated decision is `visual-approved-by-delegated-agent`.

The producer report records 241 frames, exact producer times, preserved native
identity, finite active fields, and zero nonfinite active states. It also
records 933 missing-particle lifecycle events across 234 frames, with a
single-frame maximum of 4. Those are retained as producer exclusion metadata;
they are not converted into a final UID or particle-death claim.

The package keeps source-canonical, classified, actual-converter, and source
plan condition scopes separate. Root582 FloatingInfo state0 and Root658 H5
audit are referenced by their actual metadata receipts. The source package
did not read or hash H5, BI4, CSV, DAT, or VTK scientific payloads. The
producer H5 SHA in the render report is recorded only as an attestation.

`case credit`, global counters, numerical precision, Q-N/Q-E, and production
status remain for Root integration. The old Root945 dict-representation CLI
failure remains preserved in fresh129 and is not changed or credited here.

Run the metadata-only validator with:

```text
python3 workers/validate_fresh130.py
```

