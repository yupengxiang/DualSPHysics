# ROOT256 F6 persistent primary handoff

This is a source-only invocation recipe for the primary checkout. It selects
the exact `F6-typed-lifecycle-continuation-000` group from
`CURRENT336_TYPED_LIFECYCLE_ROOT253_PENDING_V4.json`, after excluding all
ROOT245 identities, the ROOT253 actual/pending partitions, and the historical
alias. It never submits the lifecycle request and does not open trajectory,
H5, BI4, OBI4, JSONL, PartOut, or RunPARTs payloads.

Run it in the persistent primary checkout with a new output directory. Do not
reuse an agent `/tmp` directory or replace the ROOT253 pending plan with an
unrelated latest plan:

```sh
PRIMARY=/home/jade/Projects/DualSPHysics
LAB="$PRIMARY/lagrangian-fluid-lab"
STAGE2="$LAB/campaigns/ds-data-02/stage2"
PY="$LAB/.venv/bin/python"
SCRIPT="$LAB/scripts/ds_data02_stage2_build_root256_f6_typed_lifecycle_batch.py"

"$PY" "$SCRIPT" prepare \
  --plan "$STAGE2/checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT253_PENDING_V4.json" \
  --current "$STAGE2/CURRENT336.json" \
  --audit "$STAGE2/checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json" \
  --overlay "$STAGE2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT250_ACTUAL_OVERLAY_V6.json" \
  --output-root "$STAGE2/requests/typed-lifecycle-batch-v1-f6-root-prepared-256-001" \
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

The expected selected group has seven F6 cases and 19,553,749,230 declared
source bytes, below the eight-case/20 GiB bound. The generated lifecycle
request must remain `READY_NOTRUN_SOURCE_ONLY` with
`launch_allowed=false`, `execution_allowed=false`, and
`request_submitted=false`. The generated
`root256-f6-native-followup-source.json` is a terminal-proof-dependent
handoff only. A later parent-reserved native audit must bind the actual
ROOT256 terminal proof, official PartVTKOut, and exact `(Zone, Idp)` joins;
it must keep native cause, physical fate, legal flux, continuous event time,
dynamics, and QI/QN/QE unknown until those joins complete.

The immutable plan SHA is
`1be90ac9aed16d4adbddb231f26a170ade40efa953d4914ffe5553c51cb4fb48` and the
cause overlay SHA is
`f088858bb0ec9f6a1f39af08565ba0d4d39365786dfcbe8fd0b7c2c1a8d316f9`.
