# fresh206 — F5 M106/T085 personal visual review

This F6 handoff records the assigned agent's personal visual review of the
actual F5 M106/T085 render. The assigned family is F6; the physical/rendered
case is F5. The package keeps those roles separate and grants no case credit,
Q-N, Q-E, strict-containment, sub-DP, or numerical-precision claim.

The review used `functions.view_image` on all 34 published contact sheets
(`all_frames_000.png` through `all_frames_033.png`) and nine published key
frames (`0, 100, 200, 300, 400, 500, 600, 700, 800`). The package records
absolute paths, producer-declared PNG bytes/SHA values from the publish receipt,
and local stat sizes. It did not compute PNG hashes, copy images, open H5/BI4/CSV/
DAT/VTK payloads, start a job, or write shared state.

The visible screen shows the blue fluid response inside the gray channel with
the orange moving inlet-side boundary. The profile changes through the early,
middle, and late views and reaches frame 800. No obvious gross penetration,
explosive dispersion, malformed geometry, or premature visual cutoff was seen
in the reviewed images. These are image-level observations and retain the
producer's precision, lifecycle, and historical negative limitations.

Producer roles are preserved: native canonical `0c0013…f46bb`, typed legacy
`61d53c…4ec83`, SourceDef XML `6562d4…84fac`, and source-plan JSON
`366adc…7d324`. Native/XMF physical-plan fields are canonical; condition-plan
fields are absent in both masks. The actual window is 801 frames from 0.0 to
16.00014041930218 seconds.

Run the read-only validator from this directory:

```text
python3 scripts/validate_fresh206.py
```
