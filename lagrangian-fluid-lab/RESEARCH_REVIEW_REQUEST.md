# N4 stage review request

Please act as an independent senior reviewer for the N4 same-CFL matrix stage.
This is a read-only review request: do not edit files, do not launch GenCase or
DualSPHysics solver jobs, and do not infer owner budget authorization from the
attached N4 planning document.

## Scope and provenance

- Repository: `/home/jade/Projects/DualSPHysics`
- Laboratory subdirectory: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab`
- Baseline commit: `d721473f524c71bd85ba88064f66026de8306989`
- Branch: `codex/lagrangian-fluid-exploration`
- This stage follows the previous N3 reviewer plan and the attached N4 plan,
  but the attachment is planning context rather than resource authorization.

## Work completed locally

1. Prepared exactly four missing same-recipe cells: h09/h11 × coarse/medium,
   CFL=0.1, `dp=0.035/0.024 m`, `TimeMax=1.5 s`, `TimeOut=0.001 s`.
   GenCase completed for all four on CPU.
2. Kept five N3 CFL=0.1 cells as explicit reuse: h09 fine, h10 coarse/medium/
   fine, and h11 fine. Old CFL=0.2 data are excluded from the primary matrix.
3. Recomputed the H10 difference diagnostics. The registered h10 coarse→medium
   TV peak is `0.056904761904761875` at requested `1.05 s` (21-point grid,
   index 14); COM and q90 remain passing, but the TV gate remains blocking.
4. Added a guarded runner, resource ledger, comparable-matrix report, decision,
   and this handoff packet. The runner refuses new solver work without an exact
   scope JSON supplied through `--owner-approval-evidence`; after approval,
   each attempt has a 441-second timeout and the aggregate device-seconds
   ledger is capped below 0.5 GPU·h.
5. No N4 solver attempt has started. N4 new solver device seconds and attempts
   are both zero. Full local regression is `283 passed`.

## Primary artifacts to inspect

- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-COMPARABLE-MATRIX.json`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-COMPARABLE-MATRIX.md`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-H10-DIFFERENCE.json`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-RESOURCE-LEDGER.json`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-DECISION.json`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-LATEST-HANDOFF.md`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/N4-REVIEW-PACKET.md`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/r6_n4_matrix.py`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_r6_n4_matrix.py`

## Review questions

1. Are the four new definitions and five reused N3 cells correctly identified,
   with no old CFL=0.2 contamination of the primary matrix?
2. Is the H10 TV blocker represented honestly, including the fact that passing
   COM/q90 and a passing medium→fine comparison cannot cancel coarse→medium TV
   failure?
3. Does the guarded execution plan correctly constrain the next stage to exactly
   four h09/h11 coarse/medium attempts, with no scan, F6/G4, development tranche,
   finer resolution, or formal release?
4. Are the evidence requirements after execution sufficient: native exclusion
   evidence, full-time identity/quality audit, both pair gates per h09/h11, and
   explicit resource accounting?
5. Identify any blocking implementation or accounting defect before owner
   approval. If a defect exists, state the smallest corrective change.

## Required response

Return: (a) verdict on whether this stage is ready to request owner approval,
(b) blocking findings ranked P0/P1/P2, (c) exact corrections if needed, and
(d) the minimum evidence required for the next review after the four runs.
