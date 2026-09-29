# DS-DATA-01：典型拉格朗日流体数据集

This namespace is the active dataset-only continuation. It supersedes the
learning, model-inference, checkpoint-replay, hyperparameter-search, ranking,
and model-qualification work in the older L1/L2/L2-R records for this
activity. Those records remain immutable historical evidence; they are not
deleted, rewritten, or used as completion gates here.

The authoritative inputs are the current worktree, the local full
DualSPHysics v5.4 package under `../../vendor/official/DualSPHysics_v5.4`, and
the attached DS-DATA-01 benchmark specification. Generated data stay outside
Git unless a small manifest or receipt is intentionally added.

## D00–D08 artifacts

- `SCOPE_OVERRIDE.md` — dataset-only scope and legacy-task treatment.
- `DATASET_STATUS.json` — read-only local/remote/process/resource snapshot.
- `CAPABILITY_MATRIX.csv` — evidence-backed capabilities and limitations.
- `ACTIVE_TASKS.json` — resumable task queue and superseded legacy work.
- `TASK_GRAPH.md` — dependency graph and per-scope continuation rules.
- `OFFICIAL_EXAMPLES_INVENTORY.json` — D01 full-package inventory.

The snapshot and inventory are reproducible with the scripts in
`../../scripts/`. They must never launch a solver, a learner, or a model
inference process merely to inspect state.
