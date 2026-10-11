# M4 solver and native-audit queue v2

`run_solver_native_audit_queue_v2.py` is the fresh root-review handoff for
the H052/H058 additional-depth native audits. It is prepare-only by default;
it never launches work without the explicit root confirmation and it does not
write shared ledger or status state.

The v2 queue accepts the actual output shape of the frozen
`m4-additional-definitions/prepare_m4_additional_audits.py` worker. Native
audit candidates do not need flat `time_max_s`, `time_out_s`, or `dp_m`
fields. The queue derives the recipe from the actual generated XML, the
immutable child case manifest, and the immutable root solver request, then
requires those three sources to agree on `dp=.01`, `TimeMax=6`,
`TimeOut=.025`, and 241 frames. Any optional recipe copies in a candidate
are checked when present.

The sequence for a case is:

1. Reuse the immutable `solver-001` request/grant unchanged and require its
   completed receipt to bind the exact request hash.
2. Run or reuse the one-thread, 3600-second, 64 MiB native-preparation stage
   through `ds_data02_runtime_v6_batch2.py`, with no GPU reservation. A
   completed preparation request from the consumed v1 queue is reused
   byte-for-byte; it is never regenerated with this v2 launcher path.
3. Promote the frozen-worker native-integrity candidate and run the small
   exclusion audit through the same batch-2 runner.
4. After verified exclusions, run the second charged preparation and promote
   the frame candidate. `Part_*.bi4` files remain deferred through the solver
   `data/` root and the scanner emits the source and frame hash bindings.
5. Require verified exclusions, exactly 241 frames, finite valid numerical
   fields, closed typed identity, and an empty fatal-finding set. Running or
   failed receipts stop the queue; existing requests, grants, summaries,
   candidates, and reports are never overwritten or duplicated.

The root review command is:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m4-native-prepared/run_solver_native_audit_queue_v2.py \
  --case H052
```

Review the immutable `plan-v3.json` before any root-controlled launch. The
explicit launch form is:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m4-native-prepared/run_solver_native_audit_queue_v2.py \
  --case H052 --launch \
  --root-launch-confirmation ROOT_APPROVED_M4_NATIVE_SOLVER_AUDIT
```

Tests in `test_run_solver_native_audit_queue_v2.py` cover the actual H052
frozen-worker candidate, metadata-only frozen-worker-shaped exclusion/frame
candidates, recipe tamper rejection, strict source bindings, and byte-stable
reuse of the completed preparation. They do not open or hash frame/HDF
payloads.
