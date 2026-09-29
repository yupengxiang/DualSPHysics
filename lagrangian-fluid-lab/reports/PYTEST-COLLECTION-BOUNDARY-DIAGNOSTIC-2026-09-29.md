# Pytest collection boundary diagnostic

Date: 2026-09-29

## Scope and safety boundary

This is a pytest collection-boundary repair only. No scientific script, registry,
ledger, denominator, gate, completion artifact, runtime snapshot, or user data
was changed or removed. No test-collection fixture was needed: the boundary is
fully expressed by pytest configuration.

## Reproduction and cause

Before this change, running `pytest` from the repository root had no root-level
pytest configuration. Pytest therefore reported the repository root as its
`rootdir`, had no `testpaths`, and used its default recursive discovery from
`.`. The existing `lagrangian-fluid-lab/pytest.ini` was not inherited by that
root invocation; it is selected when pytest is rooted in or explicitly given a
path under `lagrangian-fluid-lab`.

The archive boundary is large: `lagrangian-fluid-lab/campaigns/core-v1/runtime/
snapshots` contains 106 snapshot directories, 26,980 files, and 26,571 Python
files. The snapshots do not contain pytest-named test files, but default root
discovery still has to walk and inspect the archive tree. The pre-fix command

```text
lagrangian-fluid-lab/.venv/bin/pytest --collect-only -q --disable-warnings
```

from the repository root did not finish within a 20-second bounded run (exit
124, no collection summary). This reproduces the undesirable recursive walk
without changing the archive.

## Repair

- Added the repository-root `pytest.ini` with `testpaths =
  lagrangian-fluid-lab/tests` and `pythonpath = lagrangian-fluid-lab`.
- Added `snapshots` to `norecursedirs` in both the root and
  `lagrangian-fluid-lab/pytest.ini`, while retaining pytest's default ignored
  directory patterns. This also protects explicit recursive collection of a
  project root.
- No `conftest.py` or other collection fixture was necessary.

## Verification

The root configuration resolved as `rootdir=/home/jade/Projects/DualSPHysics`,
with `testpaths=['lagrangian-fluid-lab/tests']` and `norecursedirs` including
`snapshots`.

The following bounded checks used the repository virtual environment and
disabled the cache provider so verification did not write pytest cache data:

| Check | Result |
| --- | --- |
| Root-level `--collect-only` with no path | 5,324 tests collected in 3.23 s; no collected nodeid under `campaigns/core-v1/runtime/snapshots` |
| Explicit `lagrangian-fluid-lab/tests` `--collect-only` | 5,324 tests collected in 3.52 s |
| Root no-path nodeid set vs explicit tests-path nodeid set | Identical, 5,324/5,324 |
| Bounded collection of `test_boundary_sidecars.py` and `test_campaign_runner.py` | 8 tests collected |
| Same two files executed | 8 passed in 1.63 s |

The explicit tests path therefore remains valid and collects the same tests. It
is no longer required merely to avoid archive recursion when running the safe
root-level `pytest --collect-only` command; the root config supplies that
boundary. It remains a useful way to request the test suite explicitly.

The system-Python attempt to collect one explicit test module was separately
blocked by a pre-existing h5py/NumPy ABI mismatch. The verification above uses
the repository `.venv`, where collection and the bounded regression pass.

## Changed files

- `/home/jade/Projects/DualSPHysics/pytest.ini`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/pytest.ini`
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/PYTEST-COLLECTION-BOUNDARY-DIAGNOSTIC-2026-09-29.md`

The snapshot file and directory counts remained unchanged after verification,
and no diff path is under `lagrangian-fluid-lab/campaigns/core-v1/runtime/`
snapshots.
