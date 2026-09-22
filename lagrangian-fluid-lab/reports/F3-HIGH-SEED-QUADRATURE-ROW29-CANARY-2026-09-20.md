# F3 high-seed quadrature repair diagnostic

This report records a bounded CPU diagnostic and does not grant material T2 credit.
The run used the registered F3 source box, finite walls, half-space source labels,
current native mass/density semantics, all-seed event denominators, and unchanged gates.

## Result

The 8192-seed canary committed 5 frames through 0.040019958626 s. It was deliberately stopped before the 8.350012828223477 s qualification horizon. Both source cells had zero unknown seeds in this short window, but no first-passage or return event occurred, so its CDF and residence results are censored diagnostics. The acceptable T2 closure path remains **blocked**.

| item | value |
|---|---:|
| seeds | 8192 (4096 per source) |
| source mass | 14.580000378191 kg |
| source 0 / source 1 mass | 7.290000189096 / 7.290000189096 kg |
| destination current mass | 0.000000000000 kg |
| first-passage mass | 0.000000000000 kg |
| return mass | 0.000000000000 kg |
| terminal unknown fraction | 0.000000000000 |
| common reliable coverage | 1.000000000000 / 1.000000000000 |
| mass closure error | 0.000e+00 kg |
| reader/checkpoint integrity | True / True |

The first process was intentionally killed after frame 2 append. Its frame 0/1 generations remain in the checkpoint inventory; the resume process restored frame 1 from the manifest and committed frames 2–4 with the same seed hash. This demonstrates recoverability, not qualification.

## Existing full-window evidence

The completed 4096-seed row29/31 traces cover the 8.350012828223477 s .01 s source window, with closed native mass and valid reader/checkpoint artifacts. They still fail the fixed per-source unknown gate and the registered CDF bound:

| row | source unknown fractions | unknown gate | CDF maximum by source | CDF gate |
|---:|---|---|---|---|
| 29 | s0=0.012207031, s1=0.009277344 | False | s0=0.061035156, s1=0.060058594 | False |
| 31 | s0=0.015625000, s1=0.014160156 | False | s0=0.061035156, s1=0.060058594 | False |

For both full-window rows, each source denominator represents 7.290000189096 kg. The evidence JSON records terminal destination mass, first-passage mass, return mass, residence quantiles, reader integrity, checkpoint integrity, and the all-seed CDF bounds per source.

The source-window audit records CDF sup bounds of 0.06103515625 for source 0 and 0.06005859375 for source 1 against the fixed 0.02 limit. The 4096 traces also expose wall-occlusion and low-effective-sample-size failures; increasing the denominator alone cannot be treated as a repair.

## Resource and stopping record

The controlled first attempt used 102.55 s wall time and 622936 KiB peak RSS before SIGKILL. Resume used 148.08 s wall time and 739688 KiB peak RSS. The measured recovery work projects to about 11.63 h for one 8192-seed, 835-interval trace, so no full high-seed run was started.

## Legal next path

The next qualification attempt needs native .002 s CFD output for the same amp0.95 and amp1.05 source geometries, a direct [0,5,...,4175] matched .01 s selection, and a resumable 8192-seed run after a reviewed spatial-index optimization. The optimization must preserve current-frame fields, fixed walls, event semantics, denominator policy, and gates. The existing amp1.0 dense pair is an engineering diagnostic with a none claim and cannot substitute for those source rows.

Evidence: `campaigns/core-v1/material/evidence/f3-high-seed-quadrature-row29-canary-v1-20260920.json`

Evidence generator SHA256: `9012cd577960d11f4ebcde72d372694766c349563e2699b7703d11d34ccd7993`
