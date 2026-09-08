# N4 reviewer packet

This is the stage handoff for the cloud reviewer.  It is based on baseline
`d721473f524c71bd85ba88064f66026de8306989` and the locked N4 input plan.  No new N4 solver attempt has
been started while owner budget status is pending.

## Requested review

1. Confirm the N3 five-cell reuse and the four unique N4 input definitions
   (`cflnumber=0.1`, `dp=0.035/0.024`, h09/h11, 1.5 s, 0.001 s output).
2. Review the h10 TV peak at `1.05 s`: max TV
   `0.056904761904761875`, with the
   reported region contributions and the same-resolution CFL=0.2 diagnostic.
3. Confirm that the proposed next action is exactly four bounded new solver
   attempts, each governed by the recorded timeout/cap, not a scan, F6/G4 run,
   development tranche, or release.
4. After runs exist, require per-case native exclusion evidence, full-time
   identity audit, and both pair gates for h09 and h11.  Do not let successful
   endpoints override the h10 coarse→medium blocker.
5. Recheck the round-1 P1 corrections: persisted audit propagation, exact
   launch-set/hash binding, durable attempt accounting, process-group timeout,
   native exclusion reconciliation, scoped approval evidence, and round-2
   lock/latest consistency.

## Current disposition

- `owner_budget_status=pending_owner_approval`
- `new_solver_authorized=false`
- `new_n4_cells=0/4`
- `formal_release=false`
- `development_authorized=false`
- `G4=not_launched`

## Evidence files

- `N4-COMPARABLE-MATRIX.json/.md`
- `N4-H10-DIFFERENCE.json/.md`
- `N4-RESOURCE-LEDGER.json`
- `N4-DECISION.json/.md`
- `N4-REVIEW-ROUND-1.md`
- `N4-REVIEW-ROUND-2.md`
- `N4-REVIEW-ROUND-3.md`
