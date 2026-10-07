# Fresh179 F3-assigned / F5 M102-T095 personal visual review

This handoff is stored in the F3 worktree while the actual simulation family is
F5.  It records the delegated first-stage visual screen of
`F5_COMPACT_RUNUP_RECOVERY_C082S1_M102_T095`, rendered by original attempt
`root-stage1-f5-m102_t095-actual1171-bed0-full801-original116023-frozen-progress-root1174`.
The renderer completed with return code 0 and published atomically before the
review.  Root1371 supplied the independent full-chain metadata QI proof before
review; that proof is metadata evidence, not a runner receipt.

I personally used `view_image` on all 34 chronological contact sheets and the
nine requested key frames `0, 100, 200, 300, 400, 500, 600, 700, 800`.  The
review was completed at `2026-10-07T07:37:40Z` using the configured
`gpt-5.6-luna/max` profile, with no model substitution or recursive delegation.  The screen found a continuous initial blue fluid field at the
gray tank boundary, coherent bounded evolution through the crest and late
oscillatory tail, and no obvious gross explosion, blank frame, severe visible
bed/wall breach, abnormal initial state, abrupt truncation, or unexplained
large visible loss.  Small edge speckle and point/raster texture remain display
observations only.

The actual loaded/rendered result is 801 frames and 194427 particles: 158559
fixed, 31658 fluid, 4210 moving, and 0 floating, with N×3 fields and actual
window `[0.0, 16.00010761371514]`.  The native and XMF physical-plan fields
carry canonical native scope `4e06ddfc...a9eb920`; both condition-plan fields
are absent.  The typed/converter legacy scope is the separate
`e561820d...8e3` role.  The bed SourceDef is a separate XML role with SHA
`7530ddff...4139a1`; it is not the XMF physical-plan role.  These roles are
kept distinct even where evidence names are similar.

This is a visual first-stage screen.  It grants no numerical precision,
strict containment, sub-DP, runup-magnitude, Q-N, Q-E, production, or global
case credit.  The bed one/two-DP bins are diagnostics, not a sub-DP proof, and
historical initialization precision/AB limitations remain unchanged.

The package reads and hashes JSON/XML/XMF metadata only.  Published PNG paths
are checked with `stat`, while PNG bytes and SHA values are copied from the
publisher's immutable receipt.  No H5, BI4, CSV, DAT, VTK, or other scientific
payload was opened or hashed, and no job or shared state was changed.

Run the read-only validator from this directory:

```text
PYTHONDONTWRITEBYTECODE=1 python3 validate_fresh179.py
```

The older fresh177/fresh178 packages are immutable and are not modified here.
