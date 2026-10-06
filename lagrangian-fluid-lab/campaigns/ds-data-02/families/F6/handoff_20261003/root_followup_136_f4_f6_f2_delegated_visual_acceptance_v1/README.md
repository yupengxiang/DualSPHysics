# F6 fresh136 — delegated visual review of three Root951 full-event renders

This package records a delegated visual review of three Root951 cases selected from a frozen copy of the live route table and excluded from checkpoint 133 accepted decisions:

- F4 `F4_DROP_gap0p25000_xoff0p08000_yoffm0p04000_uz0p40000` — 1201/1201 frames, 51 contact sheets, 9 key frames.
- F6 `F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1125_YAWP12_DP025` — 241/241 frames, 11 contact sheets, 9 key frames.
- F2 `F2_STAGE1_FIRST48_EXPANSION_RX047_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010` / physical case `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT090` — 401/401 frames, 17 contact sheets, 9 key frames.

I personally viewed every listed contact sheet and key frame with `functions.view_image`. The three cases are recorded as `visual-approved-by-delegated-agent` for Root integration, with `case_credit=0`; this package does not update global acceptance counts.

The review checks visual continuity, initial separation, release/impact/free-surface mechanism, late-window behavior, full-domain visibility, and obvious catastrophic failure signs. It records what is visible without converting visual appearance into UID, wall-penetration, numerical accuracy, Q-N/Q-E, convergence or production claims. The F2 late lateral fluid spread is explicitly retained as an observation that Root should interpret with producer metadata.

Each case keeps native, initial-QA, typed, XMF and render receipt/report paths in `metadata/chain-closure.json`. The physical/canonical/source-plan/actual-converter scope values remain separate with an explicit equality claim of `none`. Producer-attested H5/BI4/CSV information is kept as metadata provenance only; this review did not read, copy or hash scientific H5, BI4, CSV, DAT or VTK payloads.

`metadata/routing/actual-progress.frozen.json` is a byte-exact snapshot used only to select completed Root951 records. The mutable Root951 `actual-progress.json` is intentionally excluded from fixed evidence. `metadata/routing/checkpoint-133.frozen.json` is the byte-exact accepted-decision checkpoint used for de-duplication.

Validate with:

```text
python3 workers/validate_fresh136.py
```
