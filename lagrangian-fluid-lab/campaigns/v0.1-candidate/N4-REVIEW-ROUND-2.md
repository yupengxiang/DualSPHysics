# N4 reviewer round 2

Reviewer: external cloud reviewer (`Copernicus`)
Review brief: `RESEARCH_REVIEW_REQUEST.md`
Code/report revision reviewed: `af9cfe6`

## Verdict

`NO-GO` until the remaining execution-isolation and handoff-consistency
issues below are corrected.  The persisted audit propagation, completion
gates, canonical launch/hash checks, process-group timeout, and native
exclusion hard gate were confirmed as implemented in the normal path.

## Remaining P1 findings

1. Add an exclusive reservation lock/lease and reject an existing active batch;
   the report reservation alone is not concurrency/crash-atomic.
2. A failed rerun must not allow an older successful `latest.json` to be used
   by normalization/audit.  Bind normalization to the current batch/attempt
   and reject newer failed or partial attempts.
3. Use structured exact-scope approval JSON, reject extra scope, and bind its
   digest into every batch and attempt manifest.
4. Regenerate owner-facing handoff artifacts so the recorded code revision
   matches the corrected code revision.

## Minimum post-run evidence

Exactly four canonical attempt manifests, including failures, with case ID,
record/input hashes, GPU UUID/index, command, timeout, elapsed/device-proxy
seconds, status, and process-group termination state; a durable ledger with no
partial attempts and total device-proxy time ≤1800 seconds; four current
normalized outputs with native exclusion reconciliation and 21-point audits;
both h09/h11 resolution pairs passing TV≤0.05, COM≤0.06 m, and q90≤0.06 m;
and the unchanged H10 blocker (`0.056904761904761875 > 0.05`).
