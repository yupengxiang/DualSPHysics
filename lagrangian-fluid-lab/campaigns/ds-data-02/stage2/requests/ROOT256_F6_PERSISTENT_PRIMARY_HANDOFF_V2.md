# ROOT256 F6 persistent handoff V2: worktree and runtime paths

The earlier ROOT256 handoff used the ORIGINAL checkout as `PRIMARY`.  That is
incorrect for the stage2 source tree.  Keep these namespaces separate:

```sh
STAGE2_PRIMARY=/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics
ORIGINAL_PRIMARY=/home/jade/Projects/DualSPHysics
STAGE2_LAB="$STAGE2_PRIMARY/lagrangian-fluid-lab"
ORIGINAL_LAB="$ORIGINAL_PRIMARY/lagrangian-fluid-lab"
PY="$ORIGINAL_LAB/.venv/bin/python"
CONFIG="$ORIGINAL_LAB/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
```

`STAGE2_PRIMARY` owns the stage2 scripts, CURRENT/plan/audit/overlay JSON,
request output, `--cwd`, and `--worktree-root`.  `ORIGINAL_PRIMARY` owns the
validated Python environment and the official `DsphConfig.xml`/PartVTKOut
runtime sources.  The two paths are not aliases and must not be silently
rebased to each other.

Use a fresh persistent output directory in the stage2 tree:

```sh
STAGE2="$STAGE2_LAB/campaigns/ds-data-02/stage2"
"$PY" "$STAGE2_LAB/scripts/ds_data02_stage2_build_root256_f6_typed_lifecycle_batch.py" prepare \
  --plan "$STAGE2/checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT253_PENDING_V4.json" \
  --current "$STAGE2/CURRENT336.json" \
  --audit "$STAGE2/checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json" \
  --overlay "$STAGE2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT250_ACTUAL_OVERLAY_V6.json" \
  --output-root "$STAGE2/requests/typed-lifecycle-batch-v1-f6-root-prepared-256-001" \
  --python "$PY" \
  --runtime-config "$CONFIG" \
  --runtime-v2 "$STAGE2_LAB/scripts/ds_data02_runtime_v2.py" \
  --runtime-v6 "$STAGE2_LAB/scripts/ds_data02_runtime_v6.py" \
  --runtime-v8 "$STAGE2_LAB/scripts/ds_data02_runtime_v8.py" \
  --dispatch-v8 "$STAGE2_LAB/scripts/ds_data02_stage2_dispatch_v8.py" \
  --strict-v8 "$STAGE2_LAB/scripts/ds_data02_strict_dispatch_v8.py" \
  --v4-worker "$STAGE2_LAB/scripts/ds_data02_stage2_typed_lifecycle_sidecar_v4.py" \
  --batch-worker "$STAGE2_LAB/scripts/ds_data02_stage2_typed_lifecycle_batch_worker_v1.py" \
  --cwd "$STAGE2_LAB/scripts" \
  --worktree-root "$STAGE2_PRIMARY"
```

This is source preparation only.  It selects the exact seven-case F6 group,
19,553,749,230 declared source bytes, and writes both the helper-gated
lifecycle request and a terminal-proof-dependent native follow-up.  It must
leave `launch_allowed=false`, `execution_allowed=false`, and
`request_submitted=false`.

For later ROOT257/ROOT258 native extraction, use
`ds_data02_stage2_build_generic_native_extract_v1.py` with a fresh namespace.
Its `--lifecycle-request` must be the immutable stage2 request, its
`--current`/`--inventory` are stage2 metadata, and its official tool/config
inputs remain under `ORIGINAL_LAB`.  A terminal proof is required before the
native audit becomes launchable.  Case IDs are checked against the request,
CURRENT, consumed evidence, and proof without a frozen ROOT245 list.
