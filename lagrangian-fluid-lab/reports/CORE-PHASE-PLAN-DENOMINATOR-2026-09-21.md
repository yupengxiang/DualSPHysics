# Core phase and denominator contract — 2026-09-21

The unified benchmark entrypoint now exposes a read-only `phase-plan` command for the six Core phases: `verify → inspect → train → rollout → evaluate → reproduce`. It records the exact entrypoint delegated to `core_learning` where applicable, states that no optimizer or GPU was started, and binds every registered case to its saved time axis.

The F3 manifest audit passed for all 32 registered cases. Every case has 835 future frames, so the fixed denominator is 835 per case and the trajectory frame count is 836. No denominator was missing. The contract records that a later rollout failure retains the registered denominator and receives the existing evaluator penalty rather than disappearing from aggregation. The audit read time axes only; it read zero trajectory state frames.

The same explicit `data_root` interpretation is now used by benchmark `inspect`, `verify`, reader reproduction setup, delegated `train`/`rollout`/`evaluate`, and the package builder. A caller cwd outside the data root cannot silently select another manifest.

Validation:

- `test_phase_plan_connects_all_entrypoints_and_freezes_denominator`: 1 passed.
- `tests/test_core_benchmark.py`: 4 passed.
- evaluator/campaign contracts: 13 passed.
- package relative-root regression: 1 passed.
- rollout denominator regressions: 3 passed.
- delegated learning relative-root regression: 1 passed.
- `tests/test_core_learning.py`: 30 passed.

Formal training remains 0/9 and blocked. No optimizer, GPU, solver, registry, or ledger action occurred. Receipt: `campaigns/core-v1/learning/core-phase-plan-denominator-receipt-20260921.json`.
