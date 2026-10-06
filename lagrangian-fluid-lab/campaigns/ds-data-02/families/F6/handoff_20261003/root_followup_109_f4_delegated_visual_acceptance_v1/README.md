# F4 delegated visual acceptance — fresh109

This F6 handoff records the first two delegated reviews for the F4 Root638 full-1201 render queue:

- `F4_DROP_gap0p18000_xoff0p08000_yoffm0p04000_uz0p60000` — `visual-approved-by-delegated-agent` after viewing all 51 chronological contact sheets and key frames.
- `F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p40000` — `visual-approved-by-delegated-agent` for the rendered artifact, with a separate late native-UID exclusion limitation and Root764 artifact-recovery evidence.

Reviewer: `/root/f6_endpoint_initial_qa`. The package does not write accepted decisions, global counters, checkpoints, ledgers, or shared registries. It does not grant Q-N/Q-E, numerical precision, production approval, or independent-case credit.

The first case uses its completed Root638 renderer receipt. The recovery case keeps the old Root638 renderer receipt `running`/unknown with a null old return code; Root764's completed audit is recorded separately and does not rewrite or adopt the old receipt. The recovery typed metadata reports two late native fluid UID exclusions beginning at frame 1102; this package records the observation and does not infer a cause or fill the missing identities.

All 51 contact-sheet paths and nine key-frame paths per case are recorded in `metadata/review-index.json`; every listed image was opened through `view_image`. PNG byte hashes were intentionally not computed by this package. Scientific H5/BI4/CSV/VTK/DAT payloads were not opened, copied, or hashed.

Validate the bounded package with:

```sh
python3 workers/validate_fresh109.py
```
