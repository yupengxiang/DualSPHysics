# Formal release frontier review

This directory is a read-only admission snapshot for the current F3/F4
candidate. It does not authorize formal training and it contains no registry
or ledger write.

The audit is blocked by these five codes:

- `STALE_SOURCE_CLOSURE`: the v3 diagnostic preprofile was produced under a
  seven-file-different learning closure; the current closure is complete.
- `FORMAL_RELEASE_REQUIRED`: F3 is still `formal_release=false`.
- `THIRD_FAMILY_REQUIRED`: only F3 and F4 currently provide T1 families.
- `VALIDATION_DENOMINATOR`: 8 validation cases are present; 12 are required.
- `RESOURCE_FRONTIER_UNPROVEN`: the real profile reaches 16 updates, while
  Core admission requires real full-field CUDA evidence through 32000 updates.

The preserved production denominator is 64 included cases. All 64 have bound
hard-integrity and structural receipts, all 64 pass the formal audit, and the
failure denominator remains explicit. The split shape is 16 train, 4
validation, and 12 test per family.

The CPU synthetic 32000-update receipt and the four-update full-field graph
probe remain diagnostic only. The latter estimates 122.9002226982 hours for a
single 32000-update full pipeline on the observed RTX 6000 Ada path, with
579.37890625 MiB peak GPU allocation in the probe. This estimate excludes
checkpoint and validation overhead and is not a capacity proof.

The new `core.formal_capacity_evidence.v1` adapter accepts a real completed
`core.training.v1` receipt only when it has CUDA/full-field execution evidence,
the Core dual-increment model adapter, exact 8000/16000/24000/32000 milestone
checkpoints, current source closure, released manifest binding, and positive
wall/memory metrics. A valid adapter record still reports
`formal_training=false`, `formal_job_count=0`, and
`formal_runs_counted=0`.

The current snapshot reports `formal_job_count=0`,
`formal_runs_started=0`, `central_registry_mutation=0`, and
`central_ledger_mutation=0`.
