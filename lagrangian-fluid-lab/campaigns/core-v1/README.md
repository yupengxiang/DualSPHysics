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
records the current user instruction that all subsequent subagents use GPT-6 Luna
Max. Earlier Terra High and Luna Max receipts remain historical evidence only.

All commands below run from `lagrangian-fluid-lab` using `.venv/bin/python`.
Raw artifacts live in the ignored `runtime/` tree. Run outputs must not be added
to Git wholesale. Existing solver and source trajectory assets are not rewritten.

## Entrypoints

```sh
.venv/bin/python scripts/core_campaign.py adopt
.venv/bin/python scripts/core_campaign.py status
.venv/bin/python scripts/core_campaign.py status --write-snapshot
.venv/bin/python scripts/core_runtime.py status
.venv/bin/python scripts/core_runtime.py status --compact
.venv/bin/python scripts/core_runtime.py submit --spec /absolute/job.json
.venv/bin/python scripts/core_runtime.py run
```

The default runtime status includes full historical attempt receipts for audit.
Use `status --compact` for routine monitoring: it retains queued/live job
identities and summarizes terminal history by counts and resource usage.

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
- The current completion receipt recognizes one qualified F4 scope,
  `F4_resting_pool_laminar_tallwall120_x_v1`, in addition to F3. Earlier F4
  scopes remain retained negative results; their reports are not silently
  promoted by the later scope.
- The F5 prescribed-piston wave/run-up anchor reached the requested raw solver
  window but failed its zero-tolerance wall-integrity audit. It contributes no
  T1 family or matrix credit; see
  `reports/F5-WAVE-RUNUP-THIRD-T1-ANCHOR-NEGATIVE-2026-09-21.zh-CN.md`.
- The fresh F2 distributed-submerged-slot route also remains zero-credit: its
  native CPU preflight left 124,608 boundary normals unresolved; the permitted
  layer-mirroring repair reduced this to 76,095 but still failed the fixed zero
  gate, so that route is closed with no same-input retry or v3 authorization.
  See `reports/F2-DISTRIBUTED-SLOT-PREFLIGHT-NEGATIVE-2026-09-21.zh-CN.md` and
  `reports/F2-DISTRIBUTED-SLOT-NORMAL-REPAIR-V2-NEGATIVE-2026-09-21.zh-CN.md`.
- A read-only audit found that old F6 floating-box, water-entry, and twin-body
  probes represent a genuinely distinct free-rigid-body/flow-feedback
  mechanism, but they lack body mass/inertia binding, force/torque and
  boundary/contact sidecars, and complete event windows. The new F6 proposal is
  therefore root-review-only and remains unqualified; its old HDF5 files cannot
  enter a T1 denominator. See
  `reports/F6-CORE-THIRD-T1-CANDIDATE-ROOT-REVIEW-2026-09-21.zh-CN.md`.
- A fresh F6 gravity/entry physical anchor reached a protected CPU/GenCase/native
  preflight but failed the body mass/COM/inertia contract. GenCase produced a
  valid `floating mkbound=8` group; the first verifier receipt retained a
  parser infrastructure failure, and a bounded native-decode amendment then
  measured generated mass `4.32432 kg` versus the declared `2.9952 kg` and
  inertia relative error about `84.8%`. No solver, GPU, queue, registry, or T1
  credit was used. See
  `reports/F6-PHYSICAL-ANCHOR-CPU-NATIVE-PREFLIGHT-NEGATIVE-2026-09-21.zh-CN.md`.
- F1 and the F2 receiver, full-cup, and submerged-orifice repair lines retain
  their failed canaries and hard preflight failures. The F2 v2/v3/v4 orifice
  attempts are one family route with three failed definitions, not three
  families or three credits.
- No family currently has a macro-T2 material qualification. Existing material
  readers, tracers, profiles, and smoke runs remain engineering evidence until
  their registered matrices and complete case-run denominators pass.
- The F3 material row-30 R003 attempt completed all 835 native intervals, but
  its terminal scientific audit failed the frozen acceptance gate: per-source
  unknown fractions were 1.0742% and 1.0254% against a 1% maximum, and the
  independent 512-versus-4096 CDF comparison was not bound. It receives no T2
  credit; see
  [`row30 R003 terminal audit`](material/evidence/f3-material-row30-r003-terminal-audit-v1/receipt.json).
  A read-only failure attribution separates late support loss dominated by
  wall-occlusion rejection from the small low-effective-sample-size component:
  [`F3 row30 failure analysis`](../../reports/F3-MATERIAL-ROW30-R003-FAILURE-ANALYSIS-2026-09-24.zh-CN.md).
  The separately requested row-30 resource/scheduler preflight was blocked and
  did not authorize a worker; see
  [`row30 resource preflight v2`](material/evidence/f3-material-row30-resource-preflight-v2/receipt.json).
- The F4 support-cap R002 CPU-native canary preflight passed its environment
  and input checks, but explicitly did not start the canary, tracer, solver,
  GPU, or queue. Runtime remains unauthorized and no T2 credit was issued; see
  [`F4 support-cap preflight`](material/candidates/f4-supportcap-affine-query-bound-v3/cpu-native-canary-preflight-r002-v1/preflight-receipt.json).

`core_campaign.py status` verifies hashed typed evidence, not task-label strings.
The status command is read-only by default; use `--write-snapshot` only when an
intentional completion snapshot refresh is being reviewed and its dependent
hash-bound receipts will be re-bound as a separate change.
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

### Completion snapshot (2026-09-23)

The authoritative `completion.json` currently reports `can_finalize=false`:

- T1 families: F3 and F4 (2 of the required 3);
- third-family route: F8's fully filled, body-force-driven oscillatory channel is accepted as the selected mechanism, but is **not yet T1-qualified**;
- macro-T2 families: 0 of 2;
- formal training runs: 0 of 9;
- missing registered T1 case-runs: 288 for the currently qualified F3/F4 denominator; the remaining 144 of the 432 target runs depend on a third qualified family;
- missing registered material case-runs: 288 of 288;
- independent reader reproduction and causal-lineage checks: passed.

These counts are completion denominators, not a request to pad the dataset with
unqualified or duplicate cases. F8 R007 remains a geometry-only native preflight
with zero qualification credit. The R008 scope design passed Terra High static
review, also with zero credit and no execution authority. Fresh Definition and
control files for all 15 qualification configurations and 32 planned production
cases are now hash-closed in
[`definition-control-pack-v1`](cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json).
The static pack itself did not invoke GenCase. On 2026-09-23, the exact-input
R008 v3 request and its one-shot authorization were used for one representative
CPU GenCase plus native BI4 decode. Both passed geometry/native integrity checks
under the bounded CPU preflight; the immutable result is
[`cpu-native-preflight-v3/receipt.json`](cfd/f8-oscillatory-pressure-channel-r008/cpu-native-preflight-v3/receipt.json),
and its read-only postrun audit is
[`cpu-native-postrun-audit-v1/receipt.json`](cfd/f8-oscillatory-pressure-channel-r008/cpu-native-postrun-audit-v1/receipt.json).
The one-shot is consumed. It invoked no solver, GPU, worker, training, queue,
registry, or ledger, and earns zero T1 credit. The older request-only v1 packet
and review are historical; R007 outputs were not reused. The separate resource
snapshot recorded a transient CPU scheduling block. Passing the single-case
preflight does not qualify or resource-admit the 15-row T1 matrix. The next
gates are fresh matrix-level resource/scheduling admission and separate
explicit solver/T1 execution authority. The previously explored F6 Definition
failure remains immutable and cannot be retried or relabeled to satisfy the
third-family gate.

The hash-bound R008 request/authorization builder tests assume the one-shot
output namespace is still absent, so they are pre-execution checks and must not
be replayed after this completed run. Current post-consumption behavior is
covered by
[`test_f8_r008_cpu_native_preflight_consumed_state_v1.py`](../../tests/test_f8_r008_cpu_native_preflight_consumed_state_v1.py):
it verifies the immutable zero-credit receipt and that request/authorization
builders fail closed instead of issuing a second one-shot.

The historical F8 R002 static-review PASS was later found insufficient: its
Definition omitted GenCase's required `hswl` element, and the review's test-file
hash binding had drifted. Its single CPU preflight is terminal-failed and must
not be retried. The immutable postmortem is
[`static-design-review-postmortem-v1/receipt.json`](cfd/f8-oscillatory-pressure-channel-r002/static-design-review-postmortem-v1/receipt.json).
The fresh 2026-09-24 read-only static review v3 rechecked the closed R002 inputs
and retained log, confirmed the `hswl` blocker and other template-compatibility
gaps, and granted no retry or execution authority. The log's current hash
matches its historical v2 binding; a transcription error in the new review
request was corrected and recorded in
[`static-design-review-v3/receipt.json`](cfd/f8-oscillatory-pressure-channel-r002/static-design-review-v3/receipt.json).
The active R008 renderer now has a separate regression test for the frozen
constant set across all 47 rendered Definitions:
[`test_f8_r008_definition_genesis_contract_v1.py`](../../tests/test_f8_r008_definition_genesis_contract_v1.py).
