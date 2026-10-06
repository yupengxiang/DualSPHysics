# F6 fresh135 — delegated visual review of DXYZ S0875 YAWP06

This package records a delegated visual review of `F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0875_YAWP06_DP025` from the actual Root951 full-event render. The Root951 execution receipt is `completed` with return code `0`; its report contains 241/241 saved frames and 11 chronological contact sheets. I personally viewed all 11 contact sheets and key frames 0, 24, 48, 72, 96, 120, 168, 192, and 240 with `view_image`. PNG paths and digests are in `metadata/png-hashes.json`.

The images show the red floating body released above the blue fluid, early sloshing, a visible central splash/impact around 2.4 s, subsequent bounded body/free-surface motion, and later settling through the 12 s terminal state. The full tank remains in view. I saw no obvious gross initial overlap, severe wall or tank penetration, explosive cloud, blank/cropped event, or premature visual termination. This is a visual screen; it does not certify numerical accuracy, Q-N/Q-E, convergence, conservation, or production approval.

Producer metadata records 241 frames, 417505 initial particles in 3D, fixed 73441/type 0/Mk30, floating 16384/type 2/Mk60, fluid 327680/type 3/Mk1, moving 0, and a native-support mass of 256 kg distinct from the physical 128 kg rigid-body mass. The state-zero FloatingInfo audit observes `[0.07, 0.105, 0.052499998]` rad/s against the declared `[0.07, 0.105, 0.0525]`; particle V0 serialization is not used as angular-velocity proof.

The lifecycle fields are kept separate: `transient_missing_frame_count=234`, cumulative particle-frame omission events `1624`, maximum missing particles in one frame `7`, and final producer metadata has 7 excluded particles with the final exclusion prefix/digest recorded. These events are not presented as a final active UID claim; the full final active UID set was not inferred from images.

The original source-canonical scope (`d7c9d06a7b07532d2e476459a415f8b3449017cb9dd954f7dafc20ab103ab1ec`), classified/actual converter scope (`2ae29a8b7b1a732c5bfcfcaa49cdbe24f66107e1470b5c24f347f0738909a979`), and source-plan scope (`f8c8f52f62e4bf1b017aa31d57fed77ef284b6bf50df839f907520a8f49d475d`) remain separate with no equality claim. Producer-attested scientific hashes remain provenance only. The reviewer did not read, copy, or hash H5, BI4, CSV, DAT, VTK, or other scientific payloads, did not start jobs, and did not update global credit; `case_credit` remains `0`.

Validate the package with:

```text
python3 workers/validate_fresh135.py
```
