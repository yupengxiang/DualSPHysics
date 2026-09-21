# Core formal source-closure v5 admission — proposal only — 2026-09-21

The current eight-file planner closure is materialized at
`campaigns/core-v1/learning/formal-release-candidate-v5/source-closure.json`.
Its closure SHA-256 is `17e06aab45536b9df5f2a00dc347be05231d4f7c6196f07698976b86bea7ede0`,
and the artifact SHA-256 is
`7d59dc277b79c2cd77f226570ced030a3839134ee4f9052abb6f26b0095b677d`.
The verifier recomputes all eight file hashes from the workspace; no stale v4
hash is silently reused.

The hash-bound root-admission receipt is
`campaigns/core-v1/learning/formal-release-candidate-v5/root-admission-receipt.json`
(SHA-256
`c6108d93a29dae0d6b606d0f9d7613bf0df7bc0a7558caf99b63eb2b62a2a628`).
It records `formal_release=false`, `planning_only=true`,
`formal_training_allowed=false`, `formal_job_count=0`,
`launch_allowed=false`, and `root_admission.granted=false`.

The active formal blockers remain:

- third T1 family: `2/3`;
- validation denominator: `8/12`;
- formal runs: `0/9`;
- material case-runs: `0/288`;
- resource frontier: unproven;
- source manifests still require formal release; and
- the fresh v5 closure still requires root admission before it can bind a
  formal planner run.

The phase-plan denominator and evaluator failure-penalty contracts pass. The
receipt and verifier explicitly record no optimizer, GPU, solver, formal job,
registry, or ledger operation. The implementation is
`scripts/core_formal_source_closure_admission.py` (SHA-256
`bf8a59b13009230e605f401ea1a746303db49d76e66b8a16de8a26bd11ae44c4`), with
regression tests in
`tests/test_core_formal_source_closure_admission.py` (SHA-256
`b1d8cfc6de444848824364f39a86c636696bac85539ec25d87ea8d9b486b0dc8`).

Targeted validation passed: **48 tests passed in 6.03 seconds** across the v5
verifier, source-closure audit, launch contract, readiness, planner,
admission, evaluator, campaign, and benchmark tests. The Core registry SHA
remains `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d`.
