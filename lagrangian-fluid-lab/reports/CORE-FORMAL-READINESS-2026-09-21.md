# Core formal readiness audit — 2026-09-21

This read-only audit joins the phase-plan denominator contract, the existing F3/F4 formal admission observation, and the current `core_campaign` completion status. It does not launch training, emit formal job specifications, open trajectory state frames, or write the registry/ledger.

The formal gate remains blocked. The current admission observation has two T1 families (`F3`, `F4`) where three are required, and eight validation cases (`4 + 4`) where twelve are required. The current completion status contains zero of the nine required model/seed training runs. The material target is retained as a separate 288 case-run denominator: zero are observed and all 288 remain missing. An empty registered material set is not interpreted as a completed denominator.

The evaluator contract is consistent with the phase-plan contract. The phase plan retains `expected_frames = len(registered time axis) - 1` and declares that failed execution cannot shrink the denominator. The live scoring function uses all registered future frames, excluding the initial state; a setup failure with three registered future frames produces `selection_score=1.0`, `finite_prefix_frames=0`, `raw_error_coverage=0.0`, and `first_failure_frame=1`.

Observed blockers:

- `THIRD_T1_FAMILY`: 2/3 T1 families.
- `VALIDATION_DENOMINATOR`: 8/12 validation cases.
- `FORMAL_RUN_DENOMINATOR`: 0/9 formal runs.
- `MATERIAL_CASE_RUN_DENOMINATOR`: 0/288 material case-runs.

Upstream admission evidence also preserves `STALE_SOURCE_CLOSURE`, `FORMAL_RELEASE_REQUIRED`, and `RESOURCE_FRONTIER_UNPROVEN`. These remain evidence blockers and are not cleared by this audit.

Validation:

- `tests/test_core_formal_readiness.py`: 3 passed.
- The real artifact was emitted through `scripts/core_formal_readiness.py`; its blocked CLI exit code is intentional (`2`).
- No optimizer, GPU, solver, formal run, registry mutation, or ledger mutation occurred.

Artifacts:

- [formal readiness JSON](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json), SHA-256 `2553c81ea57ded94a9419bd09a2567f4b16203e4d390b80a36d34ee710ff69f6`.
- Implementation SHA-256: `scripts/core_formal_readiness.py` `b396eb2a049e797e0c419652fde8e5031bb879c0c2c4f18eb32002c57b2f938b`; regression test `tests/test_core_formal_readiness.py` `dbfa6d0fc2da72cb8d403a8f0bc4f85914cdaa70eb1bdc0cbbaae6dddf3c17d3`.
- [phase-plan input](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-phase-plan-denominator-audit-20260921.json), SHA-256 `cd6e1a432d1f8b626d7df41a2a27c3ce02356faa2242236550fa52971f37311c`.
- [formal admission input](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/formal-admission-audit-f3-f4-20260920.json), SHA-256 `da81ef0ce9533a6ded3a965e1e987a5dd927819c40b654f550889ef14af5b684`.
