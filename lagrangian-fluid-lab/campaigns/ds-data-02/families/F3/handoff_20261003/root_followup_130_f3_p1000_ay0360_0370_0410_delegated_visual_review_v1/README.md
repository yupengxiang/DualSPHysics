# fresh130 — F3 P1000 first24 delegated visual review

This source-only package records the delegated visual review of `AY0360`, `AY0370`, and `AY0410`. The frozen census showed a completed native→typed→XMF→full836 render chain for all three, and checkpoint144 did not contain any of their case IDs or physical IDs. Fresh129 (`AY0290`, `AY0300`) and the root-owned registered routes were excluded before review.

For each case, all 35 chronological contact sheets (`all_frames_000..034.png`) and six full-size keyframes (`0, 260, 360, 430, 610, 835`) were inspected with `view_image`. The review records visual continuity only. It does not grant precision, Q-N, production scope, or a 2-D range. The native/source canonical condition hash and the converter `legacy-owner-scope.v0` hash remain separate.

The package only writes metadata and PNG hash sidecars. It does not open, copy, or hash BI4/H5/CSV/DAT/VTK scientific payloads, start a job, or write shared state. Root owns checkpoint integration and any count update.

Validation:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh130.py
```
