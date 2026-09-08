# N4 reviewer round 3

Reviewer: external cloud reviewer (`Copernicus`)
Corrected code revision: `a14a5a8`
Corrected report/handoff revision: `6107d2a`

## Verdict

`READY_FOR_OWNER_APPROVAL`.  No P0/P1/P2 blockers remain in the reviewed
stage package.  The round-2 findings are closed in the pushed files:

- exclusive batch lock and active-batch rejection;
- stale latest rejection after newer failed/partial attempts;
- exact structured approval scope with digest binding in batch/attempt records;
- handoff code-revision consistency.

## Minimum evidence after approval and execution

1. Exactly four canonical attempt manifests, including failures, with input
   hashes, GPU UUID/index, approval digest, timeout, elapsed/device-proxy
   seconds, status, process-group termination, and attempt hash.
2. Durable resource accounting with four attempts, no partial attempts,
   completed plus failed equal to four, total device-proxy time ≤1800 seconds,
   and no residual solver processes.
3. Four current normalized outputs with native exclusion reconciliation and
   21-point full-time audits over 0–1.5 s.
4. Both h09 and h11 coarse→medium and medium→fine pairs pass TV≤0.05,
   COM≤0.06 m, and q90≤0.06 m.
5. The H10 coarse→medium blocker remains explicit at TV
   `0.056904761904761875 > 0.05`; CFL=0.2 stays diagnostic-only and G4,
   development, and formal release remain unlaunched.
