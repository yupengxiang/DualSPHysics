# N4 latest handoff

Generated: 2026-09-08T17:04:42.639327+00:00
Baseline: `d721473f524c71bd85ba88064f66026de8306989`
Branch: `codex/lagrangian-fluid-exploration`
HEAD: `27f72f71e559a3df8e35045037eb2f3c3de35056`

## Current state

`execution_status=awaiting_owner_budget_approval`; new solver cells
`0/4`;
`formal_release=false`; `development_authorized=false`; `G4=not_launched`.

The N4 plan is a bounded evidence-completion task, not production data
authorization.  The four new solver attempts remain guarded until the owner
provides explicit approval for at most `0.5 GPU·h` and four attempts.

## Stage summary

- Input preparation: four unique h09/h11 coarse/medium CFL=0.1 definitions
  generated and GenCase-checked; no new solver attempt was started.
- Reuse: five N3 CFL=0.1 cells are kept as explicit reuse; old CFL=0.2 data
  are excluded from the primary matrix.
- H10 difference analysis: the registered coarse→medium TV peak is
  `0.056904761904761875` at requested
  `1.05 s` (grid index `14`),
  classified as `registered_grid_localized_peak`.  This classification is
  diagnostic and does not close the blocker.
- Resource ledger: new N4 solver device seconds are
  `0.0`; GenCase CPU seconds
  are `0.10998452687636018`.  The five reused
  solver wall times are provenance only and are not charged to N4.  If
  authorized, each new attempt is capped at
  `441.0` seconds,
  with a total ledger cap of `1800.0`
  seconds.

## Same-CFL matrix

| height | resolution | source | status | full-time audit | missing identities |
|---|---|---|---|---|---:|
| `h09` | `coarse` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h09` | `medium` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h09` | `fine` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `coarse` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `medium` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `fine` | reuse | `reused_completed` | `pass` | 0 |
| `h11` | `coarse` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h11` | `medium` | new | `awaiting_owner_budget_approval` | `not_audited` | n/a |
| `h11` | `fine` | reuse | `reused_completed` | `pass` | 0 |

| height | pair | status | max TV |
|---|---|---|---:|
| `h09` | `coarse_to_medium` | `unknown` | n/a |
| `h09` | `medium_to_fine` | `unknown` | n/a |
| `h10` | `coarse_to_medium` | `fail_diagnostic` | 0.056904761904761875 |
| `h10` | `medium_to_fine` | `pass_diagnostic` | 0.04836915535444947 |
| `h11` | `coarse_to_medium` | `unknown` | n/a |
| `h11` | `medium_to_fine` | `unknown` | n/a |

The h10 coarse→medium result remains `fail_diagnostic`, max TV
`0.056904761904761875 > 0.05`; four new cells cannot override it.

## Review artifacts

- [N4-COMPARABLE-MATRIX.md](N4-COMPARABLE-MATRIX.md)
- [N4-H10-DIFFERENCE.md](N4-H10-DIFFERENCE.md)
- [N4-RESOURCE-LEDGER.json](N4-RESOURCE-LEDGER.json)
- [N4-DECISION.md](N4-DECISION.md)
- [N4-REVIEW-PACKET.md](N4-REVIEW-PACKET.md)
- [N4-REVIEW-ROUND-1.md](N4-REVIEW-ROUND-1.md)

## Next authorized gate

After explicit owner budget approval, run only h09/h11 coarse/medium with the
locked recipe.  Require full-time identity/quality audits and both resolution
pairs per height to pass TV≤0.05, COM≤0.06 m, and q90≤0.06 m.  Keep the h10
coarse→medium blocker even if all four new cells pass.
