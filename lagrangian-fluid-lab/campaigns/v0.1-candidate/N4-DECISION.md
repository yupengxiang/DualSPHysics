# N4 decision

Generated: 2026-09-08T18:17:35.204301+00:00
Baseline: `d721473f524c71bd85ba88064f66026de8306989`

## Decision

- Execution status: `completed_with_findings`
- New N4 cells: `4/4`
- Same-CFL 3×3 matrix complete: `False`
- Formal release: `false`
- Development tranche: `false`
- G4: `not_launched`

The h10 coarse-to-medium blocker is retained: max TV `0.056904761904761875` against gate `0.05`. Four h09/h11 cells cannot erase or override that failure.

## Authorization

Owner authorization is recorded against reviewed plan `6db8158`. The bounded batch used evidence digest `76a491f4c3810fa342157725165e3eb9dff482e752d3b0ad57c0a3c2f31852a8` and original-text digest `953d6b6a61ed4dc14403ec825926594fb7d6fc8bc719589e46f8f5ee2bfda862`.

## Evidence

- Comparable matrix: `N4-COMPARABLE-MATRIX.md` / `.json`
- h10 difference analysis: `N4-H10-DIFFERENCE.md` / `.json`
- Resource ledger: `N4-RESOURCE-LEDGER.json`
- Owner authorization original: `N4-OWNER-APPROVAL-ORIGINAL.md`
- Structured owner authorization: `N4-OWNER-APPROVAL.json`
- Next action: No additional N4 solver attempt is permitted; review the four completed cells and audits. The h10 coarse-to-medium blocker remains separate.

Product completion alone does not qualify N4: all four new full-time audits, native exclusion reconciliation, and both h09/h11 resolution-pair gates must pass.
The explicit owner authorization is recorded with its SHA-256 digests in the batch and attempt manifests; the four-attempt cap is exhausted and no fifth attempt is permitted.
