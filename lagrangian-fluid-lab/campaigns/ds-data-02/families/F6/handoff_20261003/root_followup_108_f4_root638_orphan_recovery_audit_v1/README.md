# F6 fresh108: Root638 orphan-render recovery audit

This is a disabled, metadata-only recovery package for the two F4 Root638
render attempts that lost their launcher while the renderer process trees were
still finishing.  The source observation at
`2026-10-06T03:37:34.370372+00:00Z` found 22 Root638 receipts with
`completed/0` and two old receipts still carrying `status: running` with no
return code.  The two output directories now expose the metadata-only shape
of a complete render (1201 frame names, 51 contact-sheet names, PVSM/GIF and
integrity report present), but that does not rewrite either old receipt into a
terminal result.  The earlier live process snapshot and the later no-process
snapshot are both recorded in `metadata/root638-orphan-recovery-evidence.json`.

No process was signalled, adopted, killed, restarted, or modified by this
package.  It did not read or hash BI4, H5, CSV, DAT, VTK, XDMF payload arrays,
or PNG bytes.  The worker checks only JSON metadata plus PNG filename and
`stat` metadata.

The two requests in `requests/` are intentionally disabled.  Root may enable a
request only after all of these steps have happened:

1. The renderer children have terminated naturally.  Root takes two fresh
   process-census samples under `runtime/resource-ledger.lock` for launcher
   PIDs 3676451/3676452 and renderer PIDs 3676852/3676853/3676854/3676855.
   All recorded PIDs must be absent in both samples.  Missing historical start
   ticks remain unknown.
2. Under that same lock, Root locates only the two exact Root638 reservation
   IDs in the evidence.  It removes those reservations and appends two
   `interrupted_unfinalized` charges, preserving the full 345600 reserved CPU
   core-seconds per case (691200 total).  `child_returncode` stays null and
   `os_exit_zero` stays false.  The old `execution-receipt.json` files remain
   immutable and unknown; no exit143 or launcher disappearance is converted to
   renderer `completed/0`.
3. Root writes the per-case reconciliation sidecars named by the configs.  The
   sidecars must carry the lock proof, two absent-process samples, no-signal/no
   adoption flags, exact reservation IDs, and the full conservative charge.
4. Root creates an enabled successor request from the disabled template.  It
   adds the four external JSON/text metadata inputs listed in
   `required_input_files_after_reconciliation` and recomputes the request's
   ordinary runtime input closure.  The source request's future receipt and
   audit-result hashes remain null until the shared runner produces them.

The enabled worker is a CPU2 `audit` task with a 30-minute wall reservation
and 256 MiB output estimate.  The shared Root142/runtime-v2 runner owns its
execution receipt.  The worker refuses a live old receipt, an unapplied or
weak reconciliation sidecar, incomplete frame/contact names, a report that
does not declare all 1201 producer frames and preserved times/identity, or a
report that tries to close visual review or numerical precision.  Its own
result increments no case count and leaves Q-N and production acceptance
unassessed.

The successor gate is 22 existing Root638 normal `completed/0` cases plus the
two independent fresh108 audit receipts.  Root still owns full visual review;
this package grants no visual acceptance, Q-N, production credit, or precision
claim.  Root637/716/733/749 waiter sources and the historical Root734 exit143
diagnostic are indexed as evidence only; no missing controller result is
treated as a job result.

Run the source validator from this directory after reviewing the package:

```text
python3 workers/validate_fresh108.py
```

The validator hashes only package source/JSON files and runs synthetic
metadata fixtures.  It never touches the DATA render payloads or the shared
ledger.
