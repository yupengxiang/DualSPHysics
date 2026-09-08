# N4 latest handoff

Generated: 2026-09-08T18:17:35.205539+00:00
Baseline: `d721473f524c71bd85ba88064f66026de8306989`
Branch: `codex/lagrangian-fluid-exploration`
Code revision used for this handoff: `f5acb9edbeb80e9526471a3b444b9a376f1913c4`

## Current state

`execution_status=completed_with_findings`; new solver cells
`4/4`;
`formal_release=false`; `development_authorized=false`; `G4=not_launched`.

The N4 plan is a bounded evidence-completion task, not production data
authorization. Owner authorization is recorded against reviewed plan `6db8158` with evidence digest `76a491f4c3810fa342157725165e3eb9dff482e752d3b0ad57c0a3c2f31852a8` and original-text digest `953d6b6a61ed4dc14403ec825926594fb7d6fc8bc719589e46f8f5ee2bfda862`.

## Stage summary

- Input preparation: four unique h09/h11 coarse/medium CFL=0.1 definitions
  generated and GenCase-checked.
- Solver execution: 4 new solver attempts were launched under the recorded owner authorization; 4 completed and 0 failed. No additional attempt is permitted after the four-attempt cap.
- Reuse: five N3 CFL=0.1 cells are kept as explicit reuse; old CFL=0.2 data
  are excluded from the primary matrix.
- H10 difference analysis: the registered coarse→medium TV peak is
  `0.056904761904761875` at requested
  `1.05 s` (grid index `14`),
  classified as `registered_grid_localized_peak`.  This classification is
  diagnostic and does not close the blocker.
- Resource ledger: new N4 solver device seconds are
  `55.05572506086901`; GenCase CPU seconds
  are `0.10998452687636018`.  The five reused
  solver wall times are provenance only and are not charged to N4.  Each new
  attempt was capped at
  `441.0` seconds,
  with a total ledger cap of `1800.0`
  seconds.

## Same-CFL matrix

| height | resolution | source | status | full-time audit | missing identities |
|---|---|---|---|---|---:|
| `h09` | `coarse` | new | `completed` | `pass` | 0 |
| `h09` | `medium` | new | `completed` | `pass` | 0 |
| `h09` | `fine` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `coarse` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `medium` | reuse | `reused_completed` | `pass` | 0 |
| `h10` | `fine` | reuse | `reused_completed` | `pass` | 0 |
| `h11` | `coarse` | new | `completed` | `pass` | 0 |
| `h11` | `medium` | new | `completed` | `pass` | 0 |
| `h11` | `fine` | reuse | `reused_completed` | `pass` | 0 |

| height | pair | status | max TV |
|---|---|---|---:|
| `h09` | `coarse_to_medium` | `pass_diagnostic` | 0.04851851851851853 |
| `h09` | `medium_to_fine` | `pass_diagnostic` | 0.03580832250187088 |
| `h10` | `coarse_to_medium` | `fail_diagnostic` | 0.056904761904761875 |
| `h10` | `medium_to_fine` | `pass_diagnostic` | 0.04836915535444947 |
| `h11` | `coarse_to_medium` | `fail_diagnostic` | 0.05818181818181817 |
| `h11` | `medium_to_fine` | `fail_diagnostic` | 0.05483858247016146 |

The h10 coarse→medium result remains `fail_diagnostic`, max TV
`0.056904761904761875 > 0.05`; four new cells cannot override it.

## Review artifacts

- [N4-COMPARABLE-MATRIX.md](N4-COMPARABLE-MATRIX.md)
- [N4-H10-DIFFERENCE.md](N4-H10-DIFFERENCE.md)
- [N4-RESOURCE-LEDGER.json](N4-RESOURCE-LEDGER.json)
- [N4-DECISION.md](N4-DECISION.md)
- [N4-OWNER-APPROVAL-ORIGINAL.md](N4-OWNER-APPROVAL-ORIGINAL.md)
- [N4-OWNER-APPROVAL.json](N4-OWNER-APPROVAL.json)
- [N4-EXECUTION-HANDOFF.md](N4-EXECUTION-HANDOFF.md)
- [N4-REVIEW-PACKET.md](N4-REVIEW-PACKET.md)
- [N4-REVIEW-ROUND-1.md](N4-REVIEW-ROUND-1.md)
- [N4-REVIEW-ROUND-2.md](N4-REVIEW-ROUND-2.md)
- [N4-REVIEW-ROUND-3.md](N4-REVIEW-ROUND-3.md)

## Next authorized gate

No additional N4 solver attempt is permitted. Review the four case products, native exclusion reconciliations, full-time audits, and h09/h11 pair gates; retain the h10 blocker. Require full-time identity/quality audits and both
resolution pairs per height to pass TV≤0.05, COM≤0.06 m, and q90≤0.06 m.
Keep the h10 coarse→medium blocker even if all four new cells pass.
