# fresh186 — F3 P1200 / AY0540 original1129 visual review

This F3-owned handoff records the delegated first-stage visual screen for
`F3_STAGE1_DP006_P1200_AY0540`, physical id
`F3_TWOAXIS_P1200_AY0540_STAGE1_FIRST48_PITCH_VARIANT`.  The render had a
completed/0 execution receipt and an atomic publish before the reviewer opened
the 35 contact sheets and nine key frames with `view_image`.

The actual producer chain is 836 frames and 179208 particles over
`[0.0, 8.350014835784549]` seconds.  Native, typed, and XMF use the same
canonical digest for this case, while their namespace roles stay separate.
Both native source-plan fields are observed absent/null.  XMF exposes its
source-plan condition digest
5f62205c3ba7074b7e56e88774b092b971cff9e4550ea4814c4ac287272ce075, while
the XMF source-plan physical field is absent; neither is filled from the
canonical digest.  The older 801-frame /
194427-particle outer envelope remains historical metadata only.

The package copies producer-declared PNG SHA values from the immutable publish
receipt and performs stat checks; it does not read or hash H5, BI4, IBI4, CSV,
DAT, VTK, or other scientific payloads.  Run the source-only validator from
this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 validate_fresh186.py
```

The result is a visual screen only.  It gives no numerical-precision,
strict-containment, sub-DP, Q-N, Q-E, or production-acceptance claim.
