# N4 decision

Generated: 2026-09-08T16:43:10.560322+00:00
Baseline: `d721473f524c71bd85ba88064f66026de8306989`

## Decision

- Execution status: `awaiting_owner_budget_approval`
- New N4 cells: `0/4`
- Same-CFL 3×3 matrix complete: `False`
- Formal release: `false`
- Development tranche: `false`
- G4: `not_launched`

The h10 coarse-to-medium blocker is retained: max TV `0.056904761904761875` against gate `0.05`. Four h09/h11 cells cannot erase or override that failure.

## Authorization

The N4 plan proposes a maximum of `0.5 GPU·h` and four solver attempts, but the attached plan is not itself owner authorization. New solver execution remains guarded by explicit `--owner-approval-evidence`.

## Evidence

- Comparable matrix: `N4-COMPARABLE-MATRIX.md` / `.json`
- h10 difference analysis: `N4-H10-DIFFERENCE.md` / `.json`
- Resource ledger: `N4-RESOURCE-LEDGER.json`
- Next action: Obtain explicit owner approval for at most 0.5 GPU-hours and four attempts, then run only h09/h11 coarse/medium.
