# F1 M3 alternative assessment

Status: planning only; no launch, no gate change, no tranche reset.

The prepared `dp=0.015` numerical bridge is unavailable for physical children. The frozen bridge comparison reports H1 RMSE `0.0836121 m` against the predeclared `0.0275 m` limit; H2-H4 pass their metric rows, but native-integrity evidence is still pending. The failure policy in [`numerical-bridge-acceptance.json`](./numerical-bridge-acceptance.json) therefore stops promotion and child launch. H050/H060 at `dp=0.015` remain prepared metadata only.

The existing official fine F1 run is also diagnostic rather than an accepted mother. Its corrected comparison report labels the result `diagnostic_only_no_source_derived_tolerance`, with H1-H4 RMSE values `0.153322`, `0.036727`, `0.093130`, and `0.046728 m`. The M3 derivative design requires applicable 3D mother evidence; catalog counts and a successful solver receipt do not supply that evidence.

## Full-event fine recipe

The viable storage alternative is to keep the official physical resolution and full event while changing only the saved-frame interval:

* `dp=0.01 m`, `TimeMax=6 s`, and the official physics/geometry controls remain fixed.
* H050 and H060 change only `fillbox size@z` from the mother value `0.55 m` to `0.50 m` and `0.60 m`.
* `TimeOut=0.025 s` is the preferred recipe because it retains 241 frames over `0..6 s`; `TimeOut=0.03 s` retains 201 frames and provides more storage margin.
* The output interval is a separately recorded numerical/output-sampling difference. It does not make the run equivalent to the `.01 s` mother, and the proxy below does not grant acceptance.

The full event is required by the frozen F1 observation contract. It binds all four elevation probes and all eight pressure probes over `0..6 s`; H4 is the reservoir history, and the pressure impact window is defined as the full official run. No narrower interval is supported by the reference package. Reducing saved-frame density keeps the full event and all labels. Truncating the run would remove required transport or impact evidence.

## Prospective sampling proxy

I read only the existing fine-run MeasureTool CSVs (27,768-byte elevation and 43,422-byte pressure files, 601 data rows each) and the 5,046,272-byte mapped SPHERIC workbook. I selected nearest existing samples at the candidate interval, kept the final `6.00005 s` sample, and reran the frozen comparison. This tests the likely observation effect of a save-interval change; it is not a solver run and does not verify native binary output behavior.

| proxy interval | rows/channel | max absolute change in H RMSE | max absolute change in H MAE | max absolute change in H signed bias | max absolute change in pressure RMSE |
| --- | ---: | ---: | ---: | ---: | ---: |
| `.025 s` | 241 | `0.002641 m` | `0.001088 m` | `0.001138 m` | `132.6 Pa` |
| `.03 s` | 201 | `0.002874 m` | `0.001303 m` | `0.001720 m` | `108.8 Pa` |

Both proxies retain H1-H4/P1-P8, finite values, and the full `0..6.00005 s` simulation bracket. Each channel has the same one sample outside the SPHERIC reference bracket as the original comparison. Pressure errors are already hundreds to thousands of pascals and have no source tolerance, so these pressure deltas are diagnostic evidence only. The primary proxy changes are small relative to the already diagnostic fine curves, but they do not establish an acceptance threshold or numerical equivalence.

## Storage tradeoff

The current completed usage is 29,500,166,968 bytes (`27.474 GiB`) against the first-tranche `50 GiB` cap, leaving 24,186,924,232 bytes (`22.526 GiB`). The estimate below uses the measured fine solver output of 19,560,649,964 bytes for 601 frames, scales fluid particles with fill height, keeps the fixed boundary count, and scales saved output by 241 or 201 frames. It is a planning estimate, not a reservation.

| physical child | output interval | estimated solver bytes | estimated solver GiB |
| --- | ---: | ---: | ---: |
| H050 | `.025 s` | 7,385,952,133 | 6.879 |
| H060 | `.025 s` | 8,301,624,043 | 7.731 |
| H050 | `.03 s` | 6,160,067,962 | 5.737 |
| H060 | `.03 s` | 6,923,761,131 | 6.448 |

The pair estimate is 14.610 GiB for `.025 s` or 12.185 GiB for `.03 s`. Adding either pair to the current completed usage gives about 42.084 GiB or 39.659 GiB before GenCase, postprocess, receipts, and temporary peak overhead. Thus a full-event fine pair is plausibly within the first tranche after the save-interval change. The terminal runtime guard must still use a measured per-request estimate and include every required product. The original `.01 s` pair is about 36.43 GiB of solver output alone and cannot fit the remaining headroom.

## Decision

Do not launch the failed `dp=.015` children. If the root establishes a valid 3D mother acceptance path without changing the frozen bridge threshold, the `.025 s` full-event fine pair is the smallest defensible next recipe; `.03 s` is a higher-margin contingency. Both must be labelled as new numerical/output-sampling recipes and revalidated from their own native receipts and H/P products. If the mother remains diagnostic only, retain the existing fine and bridge outputs as diagnostic evidence and report the M3 physical branch blocked. This assessment does not create physical-condition credit or elevate catalog counts into passed cases.

