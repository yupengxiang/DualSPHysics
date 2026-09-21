# Core formal source-closure audit — proposal only — 2026-09-21

The current formal source closure is complete at the filesystem level: all eight planner-required files exist and produce closure SHA-256 `17e06aab45536b9df5f2a00dc347be05231d4f7c6196f07698976b86bea7ede0`. The historical formal-release-candidate-v4 snapshot has closure SHA-256 `76c93c4d4effa6bf7ffa1bb124b5a43efc3c5f31bbb107f570a750fb6e5b9b22` and is stale in exactly two files:

- `scripts/core_contract.py`: current `57ffb15cea1e9a8510a5c66b2ef11fec9214c8416ab574f286cee16ebded3523`; the old snapshot records `99ff892dfe2c1ae1c7d97af00241f736cf3ebcc3c5e018ab74581fbcb079b261`.
- `scripts/core_learning.py`: current `50e50edc003bdc8b7723163e32cb2b6d56fcd0285ac97db96bac30c7751fc6d0`; the old snapshot records `20fee75b02fa9ce5cee6fdc7645bc4970ccbdd5d3a62aed7b9fedeb512c6392f`.

The other six current closure hashes are retained in the JSON artifact. The fresh closure proposal is explicitly `admitted=false`, `formal_release=false`, and `used_for_formal_training=false`. It is a hash-bound candidate for root review, not an input silently accepted by the planner.

The nine-run contract remains closed because the current readiness chain still reports the third T1 family, 12-case validation, 9 formal runs, 288 material case-runs, formal release, and resource frontier blockers. The phase-plan denominator and evaluator unit failure penalty pass. The launch contract observes nine proposal IDs but emits zero formal jobs.

Exact checks still required before reopening the planner:

1. Materialize and root-admit a fresh source-closure JSON containing all eight current hashes and the closure hash.
2. Rebind formal admission/readiness receipts to that fresh closure.
3. Provide a three-family reader manifest with `formal_release=true` and a hash binding.
4. Qualify the third T1 family with 32 production and 4 validation cases.
5. Provide live per-host/card free GPU, RAM, PSI, and active-process observations before any same-card concurrency decision.
6. Re-run the existing formal planner only after all prior checks pass; it must still produce exact checkpoint, rollout, evaluate, and reproduce lineage for the nine runs.

Validation:

- `tests/test_core_formal_source_closure_audit.py`: 2 passed.
- No source snapshot, formal job, optimizer, GPU, solver, registry, or ledger was started or written.

Artifacts:

- [source-closure audit JSON](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-formal-source-closure-audit-20260921.json), SHA-256 `642374180a15e8919f1835852b35ab22f2d0a26f0f138e90f5cd81a0f86478a3`.
- [audit implementation](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/core_formal_source_closure_audit.py), SHA-256 `b26aac8bb494f535832078733f99e09eeff8bae9290a73a14a84503c526b84b7`.
- [regression test](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_core_formal_source_closure_audit.py), SHA-256 `981d7f691ae2467c3b78ea7aab4cb7fcee2b9b6e7a92d9eca0be994bce053845`.
