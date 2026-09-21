# Core internal benchmark implementation

This campaign implements the user-adopted multi-family plan. It is **not yet a
completed benchmark**. The completion gate requires at least three T1 families,
two macro-T2 families, 32 physical cases per included scope, nine formal runs,
complete evaluation denominators, and independent reproduction. A successful
process, canary, schema test, or report does not establish scientific qualification.

## Source and authorization

`adoption.json` fixes the targets, training matrix, milestone resource policy,
and hashed references to the existing L2 records. Those records and their usage
are retained. Both Ada and H200 are authorized, including multiple processes per
GPU when peak-memory reservations and measured throughput permit. `agent-policy.json`
records the user's explicit Luna Max preference for subagents.

All commands below run from `lagrangian-fluid-lab` using `.venv/bin/python`.
Raw artifacts live in the ignored `runtime/` tree. Run outputs must not be added
to Git wholesale. Existing solver and source trajectory assets are not rewritten.

## Entrypoints

```sh
.venv/bin/python scripts/core_campaign.py adopt
.venv/bin/python scripts/core_campaign.py status
.venv/bin/python scripts/core_runtime.py status
.venv/bin/python scripts/core_runtime.py submit --spec /absolute/job.json
.venv/bin/python scripts/core_runtime.py run
```

The coordinator holds a single-process lock. It polls actual worker identities
and receipts, and can be restarted without restarting live workers. An unreachable
host or a lost worker with no receipt retains its reservation and requires
reconciliation; it is never treated as permission to duplicate the attempt.

Job specifications use an argv array, absolute cwd, explicit CPU/RAM/peak-GPU/I/O
resources, a bounded timeout, hashed input files, and required outputs relative
to the attempt directory. `{attempt_dir}` is expanded by the worker. The worker
receives one GPU UUID through `CUDA_VISIBLE_DEVICES`; the solver uses device zero
inside that visibility scope. Jobs never change legacy ledgers.

Each launch snapshots Python source, records source hashes, and writes a private
attempt receipt. Remote launches transfer the snapshot and asset symlinks rather
than a live repository or `.git`. Registered data transfer uses `core_assets.py`
and verifies destination bytes against the original manifest.

## Dataset and scientific interfaces

`core_contract.py` separates position displacement from the increment of native
saved numerical velocity. Known inputs contain finite geometry and declared
controls, never a reference reader. `core_dataset.py` preserves the registered
F3 split: 16 train, four interpolation validation, 12 extrapolation development
test cases. New scopes use the separately fixed 16/4/6/6 design. Qualification
physical lineages must remain outside all fitting and model-selection sets.

```sh
.venv/bin/python scripts/core_benchmark.py inspect \
  --manifest /absolute/manifest.json --data-root /absolute/data-root
.venv/bin/python scripts/core_benchmark.py verify \
  --manifest /absolute/manifest.json --data-root /absolute/data-root \
  --output /absolute/verification.json
.venv/bin/python scripts/core_benchmark.py reproduce \
  --manifest /absolute/manifest.json --data-root /relocated/data-root \
  --output /absolute/reader-reproduction.json
```

`verify` checks every selected source hash and complete particle axes at initial,
middle and final transitions. `--full-scan` checks every transition. Reader/oracle
reproduction is explicitly separate from final GPU-model product reproduction.

## Current evidence interpretation

- F3 remains the previously registered numerical recipe; importing it does not
  confer material qualification or external physical validation.
- F4 H1 short-window canary passed native identity and finite-wall integrity at
  0.006 m. Its original borrowed coarse resolution failed the initial mass gate.
  The revised 0.01/0.0075/0.005 m design has a separate registration and must pass
  the full spatial, temporal, cadence and event-window study.
- F1's domain-only continuation preserves physical inputs and extends the
  runtime ceiling to 1.8 m. Its 0.6 s canary includes finite obstacle checks;
  passing it does not qualify a longer event window or parameter range.
- Material outputs and model smoke/profile runs remain engineering evidence
  until their complete scientific matrices and evaluation contracts pass.

`core_campaign.py status` verifies hashed typed evidence, not task-label strings.
It reports unregistered denominators as well as missing registered evaluations.
Do not edit a gate or remove a failed case to make that status turn green.

### Execution update: actual time refinement and portable reader

The original F4 CFL-only time control was ineffective: both runs used 250,934
steps because `DtMin` clamped the integration. Its zero observation difference
is retained as a failed control, not accepted as temporal qualification. The
corrected matrix is `cfd/prepared/F4_H1_qualification_actualtime_revision`;
14 unchanged prepared cells are reused by identity, and cell 13 explicitly
halves `DtIni` and `DtMin`. The short corrective canary passed hard integrity
and source-mass gates, using 34,675 steps over 0.3 s. The full-window corrective
job is registered separately. Scientific error thresholds remain unchanged.

The H200 reader reproduction passed for all 32 registered F3 cases at a different
data root. Hash-verified reports are under `evidence/h200-reader-reproduction*`.
This is reader/input/oracle portability only, not full model/scoring reproduction.
The full-field graph inference profiles used all 34,560 particles: one cold step
was 3.08 s on Ada and 2.75 s on H200. These are bounded inference measurements,
not training-memory or steady-state throughput measurements.
