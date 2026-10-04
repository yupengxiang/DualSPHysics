# F6 frame-zero angular propagation audit (fresh056)

This scope prepares a bounded, read-only worker for root strict launch. It answers a
narrow source question for the existing corrected coarse native241 case:

`GenCase` reports zero initial particle velocity, while the floating body declares
`omega = [0.08, 0.12, 0.06] rad/s` about physical center `[2.4, 1.2, 1.08] m`.
The worker reads only Type 2 floating particles from native frame 0 and a small
number of subsequent frames, then fits

`v = Vcm + omega x (x - center)`

by bounded least squares. It reports fitted `Vcm`, fitted angular velocity, residuals,
the difference from the declared angular velocity, valid Type 2 UID coverage, and
whether native frame 0 contains nonzero floating velocity despite the GenCase zero
velocity report. Existing FloatingInfo and full241 pose paths are bound as corroborating
references.

The worker and request are source-only. This turn does not open the H5, CSV, or pose
arrays, does not read native particle arrays, and does not execute the worker. The
request stays `launch_allowed: false`, `independent_case_count_increment: 0`, with no
Q-N or numerical precision gate change. Root may enable it only after strict review.

The source mass distinction remains exact: 128 kg physical rigid mass versus 256 kg
native support weight. The worker does not rescale either quantity. Existing initial
QA mass failure, semantic interpretation boundary, native full241 timing, and visual
pending status remain unchanged.
