# F3 fresh068 wall-time extension source handoff

fresh068 is a disabled source-only derivative for the four Root134 cases that
had not started at the source-status observation: AY0590, AY0610, AY0670, and
AY0710. The original Root134 request files remain read-only inputs; this
package does not rewrite or replace them.

Each derived request changes only the attempt identity, raises
`max_wall_seconds` from `7200` to `14400`, disables `launch_allowed` and
`execution_allowed`, and adds explicit lineage. The solver argv, solver cwd,
XML/BI4/forcing bindings and hashes, physical-condition SHA, DP/physics
controls, `tmax=8.35`, `tout=0.01`, `836` saved frames, storage estimate,
CPU/GPU estimates, and Root134 cap-8 UUID-lease policy are copied exactly.
The requests remain `production_approval: none`, `independent_case_count_increment:
0`, and all future execution/native/visual receipt hashes are null.

The inherited Root134 resource policy is recorded in `policy-lineage.json`:
512 GPU-hours, 3840 CPU core-hours, 1024 qualification attempts, 720
production attempts, 1 TiB new storage, 500 GiB Home floor, shared 64-thread
cap, conversion cap 2, and deadline `2026-10-14T07:23:48+00:00`. Root must
select an actually idle UUID at any later launch; fresh068 pins no UUID and
modifies no live lease or active Root134 request.

The source-status observation found no canonical execution receipt for the
four Root134 attempt paths. That records what was observed while building the
package; it does not label any attempt failed or consume budget. No native
receipt, solver output, array, XML, BI4, CSV, H5, or other payload was opened.

Use the metadata-only builder as follows:

```text
python3 -B build_walltime_extension.py --check
```

`--check` verifies that every derived request differs from its Root134 source
only in the five documented top-level fields. `--write` is available only for
regenerating this package and never starts a job. The package does not modify
runtime code, the shared registry/ledger/index, active leases, or any running
solver.
