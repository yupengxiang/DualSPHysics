# Native identity finite interface

This internal interface consumes the actual root070 record export and the
root071 `native_motive` task input. It supports finite source metadata checks:
case-qualified identity, native numerical motive/code, source-MK/type
bookkeeping, and saved first-missing brackets. It reports native PartVTKOut
motive as a numerical source label only.

The root070 source product is:

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_NATIVE_SOURCE_IDENTITY_ROWS_V2_ROOT_070/native-source-identity-rows-v2-root-070-001-root-forward-030-001/native-source-identity-stats-correction-v2.json`

Its SHA256 is
`43bd1b7c75df1d709dec308cde0eb34548f84d32a44d8e61218a016b47c979c4` and it
contains 1328 case-qualified rows. The verified family/motive counts are F2
1078 position, F4 51 density, and F6 199 position. Global `Idp` is reused
across physical cases, so `(case_key, Idp)` is mandatory.

The actual root071 native-motive task input is
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_NATIVE_MOTIVE_TASK_INPUT_V1_ROOT_071/native-motive-task-input-v1-root-071-001-root-forward-030-001/native-motive-task-input.json`
with SHA256
`ee1348d2d3af606f6113ad7a027acd6181b191f487591f8aedf8515aa0316592`. Its
completed receipt SHA256 is
`383418ff2e3377ff0f4752ffcb19821c937cbf5b711e10c2a825fa3e68fad3a6`;
the receipt records no model/CFD invocation and fixed-point storage passed.

The loader is
`lagrangian-fluid-lab/scripts/ds_data02_stage2_native_identity_task_loader_v1.py`.
The preserved V2 evaluator is
`lagrangian-fluid-lab/scripts/ds_data02_stage2_native_identity_task_evaluator_v2.py`.
The strict forward evaluator is
`lagrangian-fluid-lab/scripts/ds_data02_stage2_native_identity_task_evaluator_v3.py`;
it joins every task row to the ordered root070 source row, checking the exact
case-qualified key sequence and family/motive/code/cause fields. This rejects
count-preserving case-key swaps that could pass aggregate checks.
The evaluator must receive the expected root070 path and SHA plus the root071
completed execution receipt, including its fixed-point storage and no-model
flags. It rejects
wrong case identity, motive/code mismatches, duplicate case-qualified IDs, and
tasks whose physical fate, legal flux, continuous event time, dynamics, or
scientific split safety remain UNKNOWN. Global Idp collisions are reported and
never used as identity.

The interface computes no ranking, leaderboard, research score, QI/QN/QE, or
physical-fate claim. It does not open H5/BI4/PartOut content, run a decoder or
solver, or treat a self-copy as an independent result.
