# ROOT253 F4 persistent handoff

This file is an invocation recipe for the primary checkout. It is source-only
documentation; it does not submit a request or read a trajectory, H5, BI4,
OBI4, JSONL, PartOut, or RunPARTs payload. The exact case boundary and the
remaining unlocated priority list are recorded in
`../checkpoints/ROOT253_AND_REMAINING_UNLOCATED_NATIVE_PRIORITY_V1.json`.

The ROOT253 typed-lifecycle builder must be run from the persistent primary
checkout, with a fresh output directory. Do not reuse the agent `/tmp` output
or a path from another worktree. The builder's pending-boundary input is the
immutable pre-ROOT245 plan; the newer `AFTER_ROOT245` plan is an accounting
index and must not be silently substituted for the builder input.

```sh
PRIMARY=/home/jade/Projects/DualSPHysics
LAB="$PRIMARY/lagrangian-fluid-lab"
STAGE2="$LAB/campaigns/ds-data-02/stage2"
PY="$LAB/.venv/bin/python"
SCRIPT="$LAB/scripts/ds_data02_stage2_build_root253_f4_typed_lifecycle_batch.py"

"$PY" "$SCRIPT" prepare \
  --plan "$STAGE2/checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT245_PENDING_V4.json" \
  --current "$STAGE2/CURRENT336.json" \
  --audit "$STAGE2/checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json" \
  --root245-request "$STAGE2/requests/typed-lifecycle-batch-v1-f6-root-forward-245-002.json" \
  --group-id F4-typed-lifecycle-continuation-000 \
  --output-dir "$STAGE2/requests/typed-lifecycle-batch-v1-f4-root-prepared-253-001" \
  --python "$PY" \
  --runtime-config "$LAB/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml" \
  --runtime-v2 "$LAB/scripts/ds_data02_runtime_v2.py" \
  --runtime-v6 "$LAB/scripts/ds_data02_runtime_v6.py" \
  --runtime-v8 "$LAB/scripts/ds_data02_runtime_v8.py" \
  --dispatch-v8 "$LAB/scripts/ds_data02_stage2_dispatch_v8.py" \
  --strict-v8 "$LAB/scripts/ds_data02_strict_dispatch_v8.py" \
  --v4-worker "$LAB/scripts/ds_data02_stage2_typed_lifecycle_sidecar_v4.py" \
  --batch-worker "$LAB/scripts/ds_data02_stage2_typed_lifecycle_batch_worker_v1.py" \
  --cwd "$LAB/scripts" \
  --worktree-root "$PRIMARY"
```

The builder is expected to produce `launch_allowed=false` and
`request_submitted=false`. It binds eight F4 cases, 20,369,358,349 declared
source bytes, the exact CURRENT/audit inputs, the ROOT245 boundary, the
interpreter and `pyvenv.cfg`, and the runtime closure. Three of the eight are
members of the historical 118-case set; the other five are diagnostic-only
CURRENT cases. A later native extraction must not count those five toward the
118 case coverage.

After the ROOT253 lifecycle attempt has a completed terminal proof, the
native extractor v2 can be prepared in a separate fresh directory. Its
immutable plan is the post-ROOT232 plan with SHA
`960725604c7978c67516ff38d60718d9eb732f18d3b8cb8cde3049ace67fb295`; the
ROOT245 terminal proof is a separate input and is not a replacement for that
plan. A primary rebind can use:

```sh
PRIMARY=/home/jade/Projects/DualSPHysics
LAB="$PRIMARY/lagrangian-fluid-lab"
STAGE2="$LAB/campaigns/ds-data-02/stage2"
PY="$LAB/.venv/bin/python"
SCRIPT="$LAB/scripts/ds_data02_stage2_f6_root245_native_extract_v2.py"

"$PY" "$SCRIPT" prepare \
  --root245-request "$STAGE2/requests/typed-lifecycle-batch-v1-f6-root-forward-245-002.json" \
  --inventory "$STAGE2/checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json" \
  --plan "$STAGE2/checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT232_V4.json" \
  --terminal-proof "$STAGE2/checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_245.json" \
  --output-root "$STAGE2/requests/root245-f6-native-extract-v2-prepared-251-001" \
  --request-output "$STAGE2/requests/f6-root245-native-extract-v2-root-forward-251-001.json"
```

The actual ROOT245 proof is
`TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_245.json`, SHA
`74b18cddf282f4a47fd098bf02623c4406cc2feae3a17663528d5f14aee72768`. Its
batch-level `batch_summary` and `report` are string paths with sibling SHA
fields. Each case has a string `summary` plus `summary_sha256` and a
`records_stat_only` dictionary. The v2 preparer binds these fields, stats the
large records path without opening it, and defers the JSONL/native reads to a
parent-reserved audit. It grants only exact typed/native saved-frame and
official Motive diagnostics; physical fate, legal flux, continuous event time,
dynamics, and QI/QN/QE remain `UNKNOWN`.

The native audit must be a new parent attempt. It must pre/post guard the
official PartOut input and use the exact `(Zone, Idp)` join, preserving a
separate failed-case record. It must not infer cause from an empty target list,
global RunPARTs counts, or lifecycle completion alone.
