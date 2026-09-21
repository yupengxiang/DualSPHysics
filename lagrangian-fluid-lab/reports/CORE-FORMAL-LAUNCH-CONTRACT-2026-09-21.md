# Core formal launch contract — proposal only — 2026-09-21

This artifact is a scheduler-facing proposal contract for the nine Core model/seed runs. It lists the required 3 models × 3 seeds, output/checkpoint lineage, milestone rollout/evaluation dependencies, and resource reservations without emitting a formal job specification or submitting work. The contract remains `proposal_only_blocked` with `formal_job_count=0` and `launch_allowed=false`.

The current gates are:

- T1 families: 2 observed (`F3`, `F4`), 3 required; the third-family gate is open.
- Validation: 8 observed (`4 + 4`), 12 required; the 12-case gate is open.
- Formal training: 0 of 9 model/seed runs; all nine proposal IDs remain missing.
- Material target: 0 of 288 case-runs observed; the 288 case-run target remains missing.
- Source closure: all eight required planner files exist and a current closure hash is computed, but the supplied formal-release-candidate-v4 snapshot is stale and requires a fresh admission snapshot.
- Phase-plan denominator and evaluator failure penalty: pass. Failed execution retains the registered future-frame denominator and receives the unit selection penalty.
- Same-card concurrency: disabled. The existing profile measures one worker at a time and does not prove safe co-location.

The proposal rows use one run directory per model/seed. Each row requires a training receipt, progress sidecar, final checkpoint, four milestone checkpoints at 8k/16k/24k/32k, and four matching validation evaluation sidecars. `select_checkpoint` consumes only the complete validation milestone set. Reproduction requires the selected checkpoint, fresh source/output hashes, and a distinct host. Test cases remain excluded.

Resource estimates are diagnostic extrapolations from the bound 16-update H200 profile, scaled to 32,000 updates with a 1.2 planning margin. Reservations are 10,240 MiB GPU and 8,192 MiB RAM for each graph worker, 1,024 MiB GPU and 8,192 MiB RAM for each MLP worker, and four CPU cores per worker. The summed nine-run estimate is approximately 379.55 GPU-hours. This is a planning estimate and does not prove 32,000-update capacity. Concurrent reservations for one worker of each model type would be 21,504 MiB GPU, 24,576 MiB RAM, and 12 CPU cores; scheduler admission must use live free-memory/PSI/process observations before any co-location decision.

Validation:

- `tests/test_core_formal_launch_contract.py`: 2 passed.
- The proposal CLI emitted the contract and returned success while keeping launch disabled; no optimizer, GPU, solver, formal job, registry, or ledger action occurred.

Artifacts:

- [proposal contract JSON](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-formal-launch-contract-20260921.json), SHA-256 `eb1451fe6bde2ba9a80bf7742b6e2aa7df3ee76806e20edfc05a8f99b806bc5a`.
- [contract implementation](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/core_formal_launch_contract.py), SHA-256 `3a188b937d5c16a5de0bcd08c4a71a5e78099d7add8d1240f68c127ca7ef5dc7`.
- [regression test](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_core_formal_launch_contract.py), SHA-256 `35475305b8ddd78a7ce2b935ebd01d81f9d2638115ab1617c7b36e5d24a2128b`.
- [formal readiness input](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json), SHA-256 `2553c81ea57ded94a9419bd09a2567f4b16203e4d390b80a36d34ee710ff69f6`.
- [phase-plan input](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-phase-plan-denominator-audit-20260921.json), SHA-256 `cd6e1a432d1f8b626d7df41a2a27c3ce02356faa2242236550fa52971f37311c`.
