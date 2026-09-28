# F3 graph_raw hidden16 seed17 diagnostic command audit

- status: `blocked_fail_closed`
- source_bound: `True`
- readiness_pass: `False`
- launch_allowed: `False`
- credit: `0`
- contract: `graph_raw`, hidden `16`, seed `17`, updates `500`, test case `F3_DEV_00_a0p903125`, `835 transitions / 836 frames`
- device mapping: physical GPU `4` exposed as logical `cuda:0` through `CUDA_VISIBLE_DEVICES=4`
- boundary: bounded manifest/training JSON plus source hash; checkpoint is stat-only; HDF5/checkpoint/evaluation/progress content is not opened
- side effects: no evaluator/Popen/solver/worker/GPU/queue; no registry/ledger/gate/completion/PLAN writes

## Fail-closed blockers

- this read-only command audit has no evaluator execution authority
- independent production terminal HDF5/artifact validator capability is not admitted
- sealed real Popen/wait process proof is not available before execution
- scheduler-owned one-shot namespace/output reservation is not externally attested
- checkpoint content SHA-256 is receipt-declared only; this audit does not open checkpoint content
- fresh GPU/CPU/I/O resource admission and physical-device reservation are not granted by this static audit

## Exact command

```text
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python -u /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/core_learning.py evaluate --manifest /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json --data-root /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab --checkpoint /tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt --case-id F3_DEV_00_a0p903125 --split test --maximum-steps 835 --chunk-size 34560 --device cuda:0 --progress-every 25 --trajectory-output /tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce4e9e7d3c0b1a2f60718293a4b5c6d7e8-trajectory.h5 --progress-output /tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce4e9e7d3c0b1a2f60718293a4b5c6d7e8-evaluation-progress.json --output /tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce4e9e7d3c0b1a2f60718293a4b5c6d7e8-evaluation.json --diagnostic
```
