# M4 solver and native-audit queue

`run_solver_native_audit_queue.py` is the root-review handoff for the two
additional physical-depth cases `H052` and `H058`. It is prepare-only unless
the caller supplies the explicit root confirmation. A normal invocation only
validates the existing root solver request/grant and writes an immutable plan
under this directory; it does not launch a solver, native decoder, or helper.

The explicit sequence for one case is:

1. Reuse `requests/<case>-solver-001.json` and its immutable batch-2 grant
   unchanged. The queue checks the fixed 9 GiB reservation, `dp=.01`,
   `TimeMax=6`, `TimeOut=.025`, and 241 expected frames.
2. Submit a one-thread `cpu_task_kind=conversion` preparation request through
   `ds_data02_runtime_v6_batch2.py`. It has a 3600 second wall bound and a
   64 MiB output reservation, and carries no GPU reservation. The frozen
   `m4-additional-definitions/prepare_m4_additional_audits.py` worker hashes
   every regular solver file and writes only below its existing `prepared/`
   directory.
3. Promote the actual native-integrity candidate into the root request and
   grant directories, changing authorization fields and adding the required
   runtime/launcher/worker provenance inputs only. Run the small native
   exclusion audit through the same batch-2 runner.
4. Repeat charged preparation after the exclusion receipt is verified, then
   promote and run the native frame candidate. The 241 `Part_*.bi4` files are
   kept out of `input_files`; the request uses the solver `data/` directory as
   `deferred_source_root` and carries its measured
   `estimated_deferred_read_bytes`. The scanner itself emits the source and
   frame hash bindings.
5. Require verified native exclusion evidence, all 241 frames, finite
   position/velocity/density fields, closed `Idp` identity, and an empty fatal
   finding list. A running or failed receipt stops the queue, and existing
   requests, grants, summaries, candidates, and reports are never overwritten.

The queue delegates parent budgets, the single-heavy-task rule, NAS checks,
and GPU leases to the shared runtime. It writes no ledger rows directly. The
root launch form is:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m4-native-prepared/run_solver_native_audit_queue.py \
  --case H052 \
  --launch \
  --root-launch-confirmation ROOT_APPROVED_M4_NATIVE_SOLVER_AUDIT
```

Run without `--launch` first and review the generated plan. The helper and
native-audit candidates remain candidate-only until the explicit launch path
promotes them.
