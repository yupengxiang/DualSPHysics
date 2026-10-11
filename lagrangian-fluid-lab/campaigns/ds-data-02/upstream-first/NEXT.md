# Continuation at the second checkpoint

First read ADOPTION.json, STATUS.json, the shared ledger, live processes and leases. Deadline remains 2026-10-25T03:11:02Z. The goal is active and M1-M4 are not all delivered.

## Active tasks

- F1 original official 3D mDBC solver: exec session 52009; request `requests/f1-solver-001.json`; NAS `runs/F1/UF_F1_MDBC_DAMBREAK3D/solver-001`. Initial 1,015,809 particles saved. Observe this existing process; do not duplicate it.
- External download-only resume: exec session 70685; request `m2/requests/lagrangebench-v2-download-resume-002.json`; NAS `runs/infra/UF_LAGRANGEBENCH_2D_LDC/m2-external-lagrangebench-v2-download-resume-002`. It is a light audit allowed alongside the solver, with strict HTTP 206/Content-Range and final MD5 checks. Original combined import was deliberately interrupted through its owned runner, charged and closed; its ~100 MB partial is immutable. See external-import-scheduling-transition.json.

## Next ready actions

1. On successful F1 solver receipt, run the committed m1/f1/scripts/extract_reference_observations.sh through a new shared-runner conversion request, with output `{attempt_root}/observations`. It uses MeasureTool with native `-threads:1`, elevation and pressure CSV only. Bind every native input hash and point-file hash. Do not duplicate all-particle VTK products. Then run compare_spheric_reference.py as a small audit.
2. Run m2/requests/portable-f1-build-001.json after the heavy queue is free; then the relocation request. These now use valid UF_ namespace, runtime bindings, contained scratch, bundled reader/evaluator and bubblewrap without the original worktree. Real-data execution has not yet happened.
3. Run requests/f1-dp015-base-solver-001.json after the heavy queue is free. Actual GenCase is 357,192 total / 192,456 fluid. The same physical mother at dp=.015 is a numerical bridge, not a new physical condition. Gate against original fine run using frozen m3/numerical-bridge-acceptance.json, all four H probes and integrity checks. No H050/H060 launches before acceptance.
4. Once external download succeeds, run the separate extraction/inspection conversion request with actual archive and receipt bindings. Inspect its prepared request paths before launch. Do not extract concurrently with a heavy solver or conversion.

## Completed evidence

F5_REFERENCE_PACK.json binds original input, GenCase, 601-frame 30 s solver, official postprocess, ODS comparison and full-window supplementary analytical comparison. ODS populated theory ends at 15 s; the official WavePaddle order-2 curve matches that overlap exactly and extends to 40 s. Full-window 2-30 s eta RMSE is about .0158907 m, above the frozen .015 m threshold. Preserve diagnostic status; no 3D or production credit. Original comparison and consumed scripts/receipts remain immutable.

The 336-case scope catalog and seven-family official mapping are committed. There is no matching compact 3D sloshing mother in the inspected official package. A bridge plus two depth derivatives is estimated to fit the first50GiB only with CSV-only postprocessing and controlled portable products; actual charges/reservations remain authoritative. Never reset the tranche to bypass a failure.
