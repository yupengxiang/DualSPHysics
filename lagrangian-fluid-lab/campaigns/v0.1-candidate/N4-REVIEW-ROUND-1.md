# N4 reviewer round 1

Reviewer: external cloud reviewer (`Copernicus`)
Review brief: `RESEARCH_REVIEW_REQUEST.md`
Baseline: `d721473f524c71bd85ba88064f66026de8306989`
Stage commit reviewed: `27f72f7`

## Verdict

`NO-GO as written` for owner approval.  The zero-run data package is sound,
but the bounded runner and post-run gates need correction first.

## Findings

### P1

1. `analyze()` rebuilds the matrix without passing the persisted prepared cases
   and audits.  After execution this can discard full-time audits and leave
   pair comparisons unknown while the decision counts completed products.
2. `run_solver()` checks only that four records are supplied.  It must bind the
   exact four canonical case IDs, record hashes, candidate definitions, and
   generated XML/BI4 hashes before launch.
3. The timeout is a useful normal-path bound, but a launch exception or a
   post-run cap exception can leave the ledger stale; a durable reservation,
   per-result accounting, and existing complete/failed-attempt count are
   required.  Timeout should terminate the complete solver process group.
4. Native exclusion evidence is documented but not a hard requirement or
   reconciliation against the solver log count.
5. Any non-empty `--owner-approval-evidence` string is currently accepted.  The
   approval record must bind the 0.5 GPU-hour / four-attempt scope and carry an
   immutable digest.

### P2

- Failed attempts must not replace `latest.json` or be normalized as current.
- The timeout change must be included in the execution revision and hashes.
- Add tests for exact-case binding, audit propagation, native evidence, and
  failure-atomic accounting.
- Represent the H10 blocker as an explicit immutable blocking status.

## Checks confirmed by reviewer

- Four new h09/h11 coarse/medium definitions and five N3 CFL=0.1 reuse cells
  are correctly identified.
- CFL=0.2/R4 data appear only in the diagnostic difference report.
- H10 coarse→medium TV remains `0.056904761904761875 > 0.05`; passing COM/q90
  and medium→fine do not cancel it.
- F6/G4, scans, development tranche, finer resolution, and formal release are
  disabled.

## Required next-stage evidence

After any approved runs: exactly four attempt manifests (including failures),
durable accounting under 1800 device-proxy seconds, no residual solver
processes, native exclusion/zero-exclusion evidence reconciled to the log,
full-time 0–1.5 s identity audits, both h09/h11 pair gates on the 21-point
grid, and the unchanged H10 blocker.
