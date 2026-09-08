# N4 execution handoff — final

This is the final execution handoff for the cloud reviewer. It records the
owner-authorized N4 evidence-completion batch after execution and post-
processing. It does not authorize a release, a development tranche, F6, G4,
or another solver attempt.

## Provenance and authorization

- Reviewed plan reference: `6db8158`
- Solver/input baseline: `d721473f524c71bd85ba88064f66026de8306989`
- Recipe: `N4_F1_plain_dam_break_cfl010_v1`
- Locked scope: h09=`0.414 m`, h11=`0.506 m`; coarse=`0.035 m`, medium=`0.024 m`; CFL=`0.1`; physical time=`1.5 s`; target output interval=`0.001 s`
- Authorized GPUs: `4,5,6,7`; protected GPUs: `0,1,2,3`
- Owner approval evidence SHA-256: `76a491f4c3810fa342157725165e3eb9dff482e752d3b0ad57c0a3c2f31852a8`
- Original authorization SHA-256: `953d6b6a61ed4dc14403ec825926594fb7d6fc8bc719589e46f8f5ee2bfda862`

The exact authorization text is in `N4-OWNER-APPROVAL-ORIGINAL.md`; the
structured input and canonical recorded authorization are in
`N4-OWNER-APPROVAL-INPUT.json` and `N4-OWNER-APPROVAL.json`.

## Solver execution

All four and only four authorized attempts launched. Each used the recorded
441-second timeout. All completed; there were no failures, interruptions,
timeouts, or partial attempt directories.

| case | GPU / UUID | attempt | status | elapsed/device seconds |
|---|---|---|---|---:|
| h09 coarse | 4 / `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9` | `20260908T175918.575183Z-31040699` | completed | 11.799175859894603 |
| h09 medium | 5 / `GPU-b5e3f067-fe26-4c00-5805-00a4f5acde32` | `20260908T175918.579099Z-a2cb7d58` | completed | 14.843629529932514 |
| h11 coarse | 6 / `GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec` | `20260908T175918.579182Z-69bddaeb` | completed | 12.72631859802641 |
| h11 medium | 7 / `GPU-88bfe7db-87fb-d458-719b-eb9a098f8f51` | `20260908T175918.581975Z-c100cb9d` | completed | 15.686601073015481 |

N4 solver accounting is `55.05572506086901 / 1800.0 GPU device seconds`;
GenCase CPU time is `0.10998452687636018 s`. The five reused N3 solver times
are provenance only and are not charged to N4. The attempt cap is exhausted:
no fifth attempt is permitted.

## Conversion and audit

All four new products converted successfully. Each has 21 registered-time
frames, zero final missing initial identities, no hard audit failures, and
native exclusion evidence with zero solver-log exclusions reconciled to zero
PartOut rows.

| case | conversion | 21-time grid | identity audit | native exclusion reconciliation |
|---|---|---|---|---|
| h09 coarse | completed | pass | pass; missing `0` | pass; rows `0` = log `0` |
| h09 medium | completed | pass | pass; missing `0` | pass; rows `0` = log `0` |
| h11 coarse | completed | pass | pass; missing `0` | pass; rows `0` = log `0` |
| h11 medium | completed | pass | pass; missing `0` | pass; rows `0` = log `0` |

## Registered 21-time resolution comparisons

The gates remain TV≤`0.05`, COM≤`0.06 m`, and q90≤`0.06 m`.

| height | pair | status | max TV | max COM (m) | max q90 (m) |
|---|---|---|---:|---:|---:|
| h09 | coarse→medium | pass | 0.04851851851851853 | 0.043666691032282816 | 0.046656250953674316 |
| h09 | medium→fine | pass | 0.03580832250187088 | 0.027081984715268157 | 0.02564370632171631 |
| h11 | coarse→medium | fail | 0.05818181818181817 | 0.04374348223045799 | 0.037831008434295654 |
| h11 | medium→fine | fail | 0.05483858247016146 | 0.03855000805966378 | 0.027028441429138184 |

Thus the h09 pair gates pass, while both h11 TV pair gates fail. These are
reported findings under the unchanged registered criteria; they are not
relabelled or repaired by endpoint completion.

## Decision and reviewer checks

- New N4 cells: `4/4` completed.
- New full-time audits: `4/4` pass.
- Same-CFL matrix complete: `false`, because the h11 pair gates fail.
- H10 coarse→medium remains `TV=0.056904761904761875 > 0.05`,
  `fail_diagnostic`, and `blocking`.
- Formal release: `false`.
- Development tranche: `false`.
- G4: `not_launched`.
- Do not launch a fifth N4 attempt. Do not start F6, G4 training, a
  development tranche, or formal release from this handoff.

Please review this document together with `N4-COMPARABLE-MATRIX.json`,
`N4-RESOURCE-LEDGER.json`, `N4-DECISION.json`, and the four attempt manifests
under the ignored/local run root. The compact sidecars under
`sidecars/n4-f1-same-cfl/` are the committed normalized review artifacts.
