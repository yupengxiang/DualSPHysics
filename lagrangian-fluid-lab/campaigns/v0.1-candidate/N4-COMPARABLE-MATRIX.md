# N4 comparable matrix

Baseline: `d721473f524c71bd85ba88064f66026de8306989`  Recipe: `N4_F1_plain_dam_break_cfl010_v1`

This table keeps the five N3 CFL=0.1 cells as explicit reuse and reserves four new h09/h11 coarse/medium cells for owner-authorized solver attempts. Old CFL=0.2 data are not in the primary matrix.

| height | resolution | case | source | matrix status | full-time audit | final missing identities |
|---|---|---|---|---|---|---:|
| `h09` | `coarse` | `N4_F1_plain_h09_coarse_cfl010` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h09` | `medium` | `N4_F1_plain_h09_medium_cfl010` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h09` | `fine` | `R6_N3_F1_plain_dam_break_h09_fine_cfl010` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `coarse` | `R6_N3_F1_plain_dam_break_h10_coarse_cfl010` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `medium` | `R6_N3_F1_plain_dam_break_h10_medium_cfl010` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `fine` | `R6_N3_F1_plain_dam_break_h10_fine_cfl010` | reuse | `reused_completed` | `pass` | 0 |
| `h11` | `coarse` | `N4_F1_plain_h11_coarse_cfl010` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h11` | `medium` | `N4_F1_plain_h11_medium_cfl010` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h11` | `fine` | `R6_N3_F1_plain_dam_break_h11_fine_cfl010` | reuse | `reused_completed` | `pass` | 0 |

## Pair gates

Thresholds: TV ≤ `0.05`, COM ≤ `0.06 m`, q90 ≤ `0.06 m`; all use the registered 21-time grid.

| height | pair | status | max TV | max COM (m) | max q90 (m) |
|---|---|---|---:|---:|---:|
| `h09` | `coarse_to_medium` | `unknown` | n/a | n/a | n/a |
| `h09` | `medium_to_fine` | `unknown` | n/a | n/a | n/a |
| `h10` | `coarse_to_medium` | `fail_diagnostic` | 0.056904761904761875 | 0.04096581324518249 | 0.04397571086883545 |
| `h10` | `medium_to_fine` | `pass_diagnostic` | 0.04836915535444947 | 0.02737614558257564 | 0.026804447174072266 |
| `h11` | `coarse_to_medium` | `unknown` | n/a | n/a | n/a |
| `h11` | `medium_to_fine` | `unknown` | n/a | n/a | n/a |

The h10 coarse→medium failure is preserved and cannot be overridden by endpoint completion.

Product completion alone does not qualify N4: all four new full-time audits, native exclusion reconciliation, and both h09/h11 resolution-pair gates must pass.
