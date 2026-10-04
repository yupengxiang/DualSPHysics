# F2 Stage1 offset endpoints: source-only handoff

This fresh scope prepares two prospective offset-spill physical endpoints from the existing F2 batch generator. It is source evidence only. The accepted Root061 mother, its bounded initial audit051, and typed003 receipt are read-only provenance; the mother is not rerun and is not counted again.

The recommended first pair is:

- `F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010`: open rim, receiver `(x,y)=(0.45,0.14)` m, batch fill ratio `0.8`, native rotation duration `0.65` s.
- `F2_STAGE1_OFFSET_P03_DP010_SPATIAL_REFERENCE_SAVE010`: open rim, receiver `(x,y)=(0.65,0.14)` m, same source fill and forcing, with the receiver-x endpoint varied.

Both retain the F2 finite cup, receiver, tray, gravity/DBC controls, and official `mvrotfile` forcing. The source recipe is `dp=0.01`, `TimeMax=4`, `TimeOut=0.01`, and expected full-window output is 401 saved frames. No `-mdbc_noslip` or other extra solver forcing option is added; the XML motion file is authoritative.

`source/` contains only definitions, native motion text, and metadata. `requests/` contains disabled GenCase, actual initial-QA, and full native solver request bindings. `workers/f2_stage1_initial_qa_worker.py` is a direct bounded CPU worker Root may enable after actual GenCase. `workers/f2_stage1_endpoint_worker.py` verifies source identity and terminal receipts without launching anything or reading particle arrays; each endpoint also has a disabled lifecycle-audit request that invokes it after Root supplies fresh receipts.

The package deliberately contains no actual GenCase, QA, solver, BI4, CSV, H5, rendering, precision, Q-N, or production receipt. Native particle counts and mass must be taken from Root's actual outputs; this source package makes no fabricated count or mass claim.

Build/review commands:

```text
/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python build_f2_stage1_endpoints.py
python -m py_compile workers/f2_stage1_initial_qa_worker.py workers/f2_stage1_endpoint_worker.py
```

The builder only materializes source fixtures and disabled JSON. It does not invoke GenCase, PartVTK, DualSPHysics, a runner, or an array reader.
