# fresh184 — F5 M101/T100 personal visual review

This F3-owned handoff records the delegated personal visual screen for the
already completed and atomically published F5 M101/T100 rendering.  The actual
case is `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34`, with
physical id `F5_COMPACT_RUNUP_RECOVERY_C082S1_M101_T100`.

The source of truth is Root ownQI1397 and the case's completed/0 native,
typed, XMF, bed, and render receipts.  The package copies producer-declared
PNG SHA values from the immutable publish receipt and performs filesystem stat
checks only; it never opens or hashes H5, BI4, IBI4, CSV, DAT, VTK, or other
scientific payloads.  The 34 contact sheets and nine requested key frames were
personally opened with `view_image` after the completed/0 receipt and atomic
publish were available.

Run the source-only validator from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 validate_fresh184.py
```

The screen is visual evidence only.  It does not grant Q-N/Q-E, numerical
precision, strict containment, sub-DP behavior, run-up magnitude, or
production acceptance.  The 801-frame/194427-particle identity and bed
one-DP/two-DP observations are retained as producer QI evidence; they are not
recomputed here.
