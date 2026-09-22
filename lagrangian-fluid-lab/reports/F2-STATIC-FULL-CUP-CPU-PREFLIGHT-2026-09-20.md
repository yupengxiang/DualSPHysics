# F2 static full-cup CPU/native preflight — 2026-09-20

The existing v4 matrix already contains fresh CPU GenCase output and native `bi4_dump` decoding for all 15 registered cells. The new [read-only audit](../campaigns/core-v1/evidence/f2-static-full-cup-cpu-preflight-v1.json) rehashed each row's prepared receipt, preflight receipt, generated definition, zero-angle motion file, native BI4, decoded directory, and all 23 declared closure inputs per cell. It did not rerun GenCase or the decoder.

All 15 rows pass input closure and native preflight. The fixed denominator remains 15, with 15 passed and 0 failed/unresolved; rows remain registered even if a future run fails, and survivor renormalization is disabled. The audit SHA-256 is `6f5fbe8bef63db9f2cb64c26698bd27a3b597d03763a4995bfa71b5315010115`.

| index | q | dp (m) | design | artifact (MiB) | closure | status |
| ---: | ---: | ---: | --- | ---: | ---: | --- |
| 0 | 0.00 | 0.0100 | spatial | 30.772 | 23/23 | passed |
| 1 | 0.00 | 0.0075 | spatial | 56.097 | 23/23 | passed |
| 2 | 0.00 | 0.0050 | spatial | 135.559 | 23/23 | passed |
| 3 | 0.50 | 0.0100 | spatial | 30.772 | 23/23 | passed |
| 4 | 0.50 | 0.0075 | spatial | 56.097 | 23/23 | passed |
| 5 | 0.50 | 0.0050 | spatial | 136.374 | 23/23 | passed |
| 6 | 1.00 | 0.0100 | spatial | 30.973 | 23/23 | passed |
| 7 | 1.00 | 0.0075 | spatial | 56.451 | 23/23 | passed |
| 8 | 1.00 | 0.0050 | spatial | 137.189 | 23/23 | passed |
| 9 | 0.25 | 0.0075 | spatial held-out | 56.098 | 23/23 | passed |
| 10 | 0.25 | 0.0050 | spatial held-out | 136.375 | 23/23 | passed |
| 11 | 0.75 | 0.0075 | spatial held-out | 56.452 | 23/23 | passed |
| 12 | 0.75 | 0.0050 | spatial held-out | 137.190 | 23/23 | passed |
| 13 | 0.50 | 0.0075 | internal time | 56.098 | 23/23 | passed |
| 14 | 0.50 | 0.0075 | native output | 56.099 | 23/23 | passed |

Observed prepared-input artifacts occupy 1,168.60 MiB in total; the largest cell occupies 137.19 MiB. The candidate reservation envelope is 2 CPU cores, up to 24,576 MiB RAM, and 36,000 seconds of per-cell timeout budget in aggregate. GPU values are recorded estimates only; no GPU timing or launch was performed.

Cell 0 (`q=0`, `dp=0.010 m`) is worth a separate root review for one static canary because its CPU/native closure passes and it is the nominal lowest-resolution row. The current [root review](../campaigns/core-v1/cfd/f2-static-full-cup-root-review-v1.json) authorizes CPU preparation/decode only; it does not authorize solver, GPU, job, queue, registry, or ledger actions. The audit therefore reports `current_runtime_authorized=false` and starts nothing.

This candidate means a fixed cup at zero angle with a resting initial volume hold. It is numerical static F2 scope evidence only and cannot establish dynamic pouring, receiving, overflow, side-wetting, or F2 T1 qualification. The [scope review](../campaigns/core-v1/cfd/f2-static-full-cup-root-scope-review-v1.json) remains `prerequisite_only`.

Validation: 12 targeted tests pass, including the new audit, matrix audit/preparation contracts, and root-review controls. The audit implementation is [f2_static_full_cup_cpu_preflight_audit.py](../scripts/f2_static_full_cup_cpu_preflight_audit.py), SHA-256 `d567bad233d9afad3f639516fa92e3d35454adafb3b22758541d237a724c0af4`.
