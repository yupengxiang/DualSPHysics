# F3 evaluator artifact readiness contract

- status: `blocked_fail_closed`
- source static inventory: `True`
- readiness / launch / credit: `False` / `False` / `0`
- envelopes: `6` (graph_raw/residual × seeds 17/29/43)
- natural-exit proofs: `0/6`

This report only reads bounded Python source text. It does not open real checkpoints, HDF5, evaluation JSON, or progress sidecars, and it starts no evaluator/solver/worker/GPU/queue.

## Boundaries

- no evaluator was started and no real evaluator JSON/HDF5/progress receipt was opened
- installed HDF5 validator is synthetic-only and cannot authenticate production artifacts
- no independent artifact-identity sidecar receipt was produced
- no real subprocess.Popen/wait natural-exit proof was observed
- fresh namespaces are planned identities only; no one-shot creation/freshness attestation exists

The installed validator CLI is recorded for audit but remains synthetic-only; it cannot mint production terminal evidence.
