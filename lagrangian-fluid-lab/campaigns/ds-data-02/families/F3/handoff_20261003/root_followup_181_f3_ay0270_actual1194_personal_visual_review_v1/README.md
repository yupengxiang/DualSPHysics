# F3 fresh181: AY0270 personal visual review

This scoped handoff records a delegated first-stage visual screen for
`F3_STAGE1_DP006_P1000_AY0270` /
`F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW`.

The source render reached `completed`/returncode `0` and was atomically
published before the review. Root1387 independently records the actual
836-frame, 179208-particle, N3/finite/time/UID evidence. I personally viewed
all 35 published contact sheets and the nine published key frames at frames
`0,104,208,312,417,521,626,730,835`. The screen sees a coherent initial
layer, travelling crest/run-up and return/decay, with no obvious gross breakup,
blank/corrupt frame, abrupt truncation, whole-domain explosion, abnormal
initial state, or severe visible bed/wall breach. Small crest edge speckle is
recorded as display texture only.

This is a visual first-stage screen. It does not establish numerical
precision, strict containment, sub-DP behavior, run-up magnitude, Q-N, Q-E,
particle conservation beyond producer metadata, or production qualification.
The handoff grants no case credit. The original typed154 receipt remains
`running` with no returncode field; the independent artifact audit and
recovery-aware XMF receipts are recorded as separate completed evidence and
are never substituted for that original lifecycle.

Native canonical scope (`a6a7dfcc…d109e9`) and typed legacy converter scope
(`217fbe56…a3719413`) remain separate. Native and XMF source-plan condition
fields are explicitly absent/null; the canonical digest is not backfilled into
those fields. The historical outer 801-frame/194427-particle envelope remains
separate from the actual loaded 836-frame/179208-particle wrapper.

The builder and validator only read JSON/XML/XMF/Python/Markdown metadata.
PNG files are stat-checked and their SHA values are copied from the immutable
publisher receipt; the reviewer did not open or hash scientific payloads.

Run the read-only validator from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 validate_fresh181.py
```

The package manifest intentionally excludes its own hash to avoid a
self-reference cycle.
