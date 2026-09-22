# F3/F4 material T2 minimal-repair audit

This CPU-only audit consumes the retained source/window audit and remediation
preflight as JSON. It does not open HDF5, submit a job, start a solver or GPU,
change a score, or mutate the registry or ledger. The versioned artifact is
[`f3-f4-t2-minimal-repair-audit-20260920.json`](../campaigns/core-v1/material/evidence/f3-f4-t2-minimal-repair-audit-20260920.json),
SHA-256 `9a9799abd9e8f8f46b34496b61e60bf5cbab873336fb6d5c469748b72dcf4c20`.

The fixed gates remain per-source unknown mass `<= 0.01`, F3 CDF sup bound
`<= 0.02`, and a complete F4 event window of `4.34 s`. The audit reports the
smallest integer deficits that a future fixed-gate run would need to close.
Those counts are planning quantities; they do not authorize editing a trace or
relabeling an unknown seed.

For F3, the retained rows require at least 26 unknown paths to become valid
reliable paths: row 29 source 0 requires 5, row 31 source 0 requires 12, and
row 31 source 1 requires 9. Row 29 source 1 is already within the unknown
budget. The first-failure records are dominated by `wall_occluded` (24 of 25
for row 29 source 0, 19 of 19 for row 29 source 1, 27 of 32 for row 31 source
0, and 26 of 29 for row 31 source 1); low effective sample size and no support
also occur in row 31 source 0. The CDF comparison is one fixed pair reused by
both rows. Its maximum bound is `0.06103515625` for source 0 and
`0.06005859375` for source 1. To reach the fixed bound, those maxima would
need to decrease by at least 85 and 83 denominator units respectively. A CDF
bound unit is not equivalent to a recoverable seed.

For F4, every retained checkpoint is integrity-valid, but all six traces stop
before the registered event window and all six fail the unknown gate.

| retained case | unknown seeds | minimum recovery to 5/512 | observed window | minimum missing window |
|---|---:|---:|---:|---:|
| real baseline | 434 | 429 | 0.300003 s | 4.039997 s |
| native pair S2 | 459 | 454 | 0.300003 s | 4.039997 s |
| native pair S4 | 459 | 454 | 0.300003 s | 4.039997 s |
| ESS32 repair | 473 | 468 | 0.300003 s | 4.039997 s |
| affine-bound repair | 489 | 484 | 0.300003 s | 4.039997 s |
| tallwall120 short canary | 512 | 507 | 0.400015 s | 3.939985 s |

The saved-frame probe identifies the first real F4 failure for both repair
candidates at frame 81 (`0.162004 s`): 64 seeds fail the reconstruction-error
gate while support distance, ESS, rank, and anisotropy contribute zero failures.
By the last `0.300003 s` probe, ESS32 has 473 permanent unknown seeds with 361
support-distance failures, while the affine candidate has 489 unknown seeds,
488 reconstruction failures, and 416 support-distance failures. The candidate
repair therefore does not close the real unknown gate; its manufactured or
local support evidence cannot be promoted to acceptance.

A valid checkpoint supports restartability only. It cannot provide the missing
CFD frames, complete a right-censored event, or repair the already permanent
unknown state. The current material record therefore has no independent legal
qualification path: T2 remains unestablished, with `T2_macro=false`,
`T2_path=false`, and qualification credit `none`.

Coverage is also open. The registered F3 scope has 33 rows with formal
completion false, including blocked rows 16–23, 26–27, 29, and 31 plus source
available but unsubmitted rows 28 and 32. The F4 overlay has 33 registered
rows over 15 CFD source cells; exact cadence pairs, 4096-seed overlays, and
formal matrix acceptance are all incomplete.

The audit binds the retained CPU source/window audit
(`983e15aae8e1ce4df705590c7b1cc89e27a0445c8152f4a003123392e3aaa279`), the
remediation preflight
(`a4b957fa0e92c666e305ec9409f4128134e574214c4480552f6d067ae2ead63e`), and
the F4 repair diagnosis
(`e9b753a7c663d8b843aea8087f549452f4fb30f27aec09e002a84596cae5319a`).
