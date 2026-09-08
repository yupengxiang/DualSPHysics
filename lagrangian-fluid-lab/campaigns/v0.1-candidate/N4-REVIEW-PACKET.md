# N4 reviewer packet

This is the post-execution handoff for the cloud reviewer. It is based on baseline `d721473f524c71bd85ba88064f66026de8306989` and reviewed plan `6db8158`. The bounded batch launched 4 attempts (4 completed, 0 failed).

## Requested review

1. Confirm the four exact N4 input definitions and their recorded input hashes.
2. Confirm the four attempt manifests use GPUs 4–7, the two authorization digests, the 441 s timeout, and no
   protected GPU 0–3 was terminated or used.
3. Review per-case native exclusion reconciliation, full-time identity/quality audit, and the 21 registered times.
4. Review the h09 and h11 pair results against TV≤0.05, COM≤0.06 m, and q90≤0.06 m.  The h11 pair failures
   remain findings and are not to be relabelled as passes.
5. Confirm that no fifth attempt, F6/G4 run, development tranche, or formal release is authorized.  Do not let
   successful endpoints override the h10 coarse→medium blocker.

## Current disposition

- `owner_budget_status=approved_for_bounded_n4`
- `new_solver_authorized=True`
- `new_n4_cells=4/4`
- `solver_attempts=4/4`
- `solver_attempts_failed=0`
- `formal_release=false`
- `development_authorized=false`
- `G4=not_launched`

## Evidence files

- `N4-COMPARABLE-MATRIX.json/.md`
- `N4-H10-DIFFERENCE.json/.md`
- `N4-RESOURCE-LEDGER.json`
- `N4-DECISION.json/.md`
- `N4-OWNER-APPROVAL-ORIGINAL.md`
- `N4-OWNER-APPROVAL.json`
- `N4-REVIEW-ROUND-1.md`
- `N4-REVIEW-ROUND-2.md`
- `N4-REVIEW-ROUND-3.md`
