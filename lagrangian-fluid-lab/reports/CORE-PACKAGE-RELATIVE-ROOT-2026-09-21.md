# Core package portability repair — 2026-09-21

The package builder had a path interpretation mismatch in the unified Core entrypoint. `inspect_reader_manifests()` and `open_dataset()` resolve a relative manifest under the explicit `data_root`, while `build_bundle()` passed the relative path through to the current working directory. A worker invoked from another directory could therefore fail before producing the portable bundle.

`build_bundle()` now resolves a relative manifest as `data_root/<manifest>` before opening the dataset. The new regression changes the caller working directory, builds from `manifest.json`, verifies the bundle, relocates it, and verifies the relocated dataset. This is a packaging interface repair only; it does not alter evaluator scoring, model rollout, checkpoint selection, or qualification claims.

Validation:

- `tests/test_core_package.py::test_bundle_builder_resolves_relative_manifest_against_data_root`: 1 passed.
- `tests/test_core_package.py`: 13 passed.
- `tests/test_core_evaluation.py`: 5 passed; the fixed evaluator denominator remains intact.
- The two rollout failure/denominator regression tests in `tests/test_core_learning.py`: 2 passed.
- Formal training: 0/9; no optimizer, GPU, solver, registry, or ledger action.

Receipt: `campaigns/core-v1/learning/core-package-relative-root-repair-20260921.json`.
