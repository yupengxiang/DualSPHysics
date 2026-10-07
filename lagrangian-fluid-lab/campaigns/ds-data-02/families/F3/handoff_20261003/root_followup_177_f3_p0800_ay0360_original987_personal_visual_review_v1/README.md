# Fresh177 F3 personal visual review — P0800 / AY0360

This F3-only handoff records my personal first-stage visual review of the
actual published `F3_STAGE1_DP006_P0800_AY0360` result. Its unique physical
case is `F3_TWOAXIS_P0800_AY0360_STAGE1_FIRST48_PITCH_VARIANT`. The completed
chain is the original native receipt, typed receipt/report, N3 XMF receipt,
manifest/XML, and Root987 render receipt/publish receipt. Root1355 is an
independent full-chain QI proof; it is not a replacement for any runner
receipt.

I personally used `view_image` on all 35 chronological contact sheets and
all nine requested key frames: 0, 100, 200, 300, 400, 500, 600, 700, and 835.
The initial blue fluid field is continuous at the tank base against the gray
fixed boundary. The crest develops, migrates, rebounds, and decays through
the contacts while remaining visually bounded by the tank. I saw no obvious
whole-domain explosion, gross blank frame, severe visible bed/wall breach,
abnormal initial state, abrupt truncation, or unexplained large visual loss.
Small edge speckle and point/raster texture are retained as display
observations only.

The actual loaded wrapper is 836 frames and 179208 particles, with 111708
fixed and 67500 fluid particles, zero moving/floating particles, N×3 fields,
and the actual time window `[0.0, 8.35001341871951]`. The outer request's
801-frame/194427-particle/34-contact envelope is stale historical metadata;
it is preserved and does not override the completed 836-frame output.

Native request and actual converter scope use canonical digest
`7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5`.
The native and XMF `source_plan_condition_sha256` and
`source_plan_physical_condition_sha256` fields are genuinely absent/null.
The canonical digest is not copied into either missing source-plan field, and
the typed legacy/converter scope remains a separate role even where its
digest agrees. Parent initialization QA is recorded as reused evidence; it is
not relabeled as an independent per-case QA run.

This is a first-stage visual screen. It does not establish strict
containment, sub-DP behavior, runup magnitude, numerical precision, Q-N,
Q-E, production qualification, or a global case credit. `case_credit`,
Q-N, and Q-E remain zero/false for this handoff. UID/type/time/finite/N3
facts come from Root1355 and producer metadata, not visual inference.

The package reads JSON/XML metadata and uses the publisher's declared PNG
bytes/digests while checking PNG paths with `stat`. The reviewer did not open
or hash H5, BI4, CSV, DAT, VTK, or other scientific payloads, and did not
start, restart, stop, or modify a scientific/shared task.

Validate from this directory with:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh177.py
```
