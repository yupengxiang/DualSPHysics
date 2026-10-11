# Actual M4 relocation validation

`m4_actual_validation.py` prepares a root-reviewed CPU audit request only after
it can read a completed M4 enrichment receipt and validate the actual portable
bundle with the production `m4_portable_adapter.py`. It does not build a
bundle, run the direct converter, submit a shared-runner request, or launch a
solver.

The worker first copies the complete source bundle into a fresh
`{attempt_root}` NAS destination. It invokes the existing
`m4_isolated_validate.py` wrapper in-process with the source bundle and source
receipt directory added to the wrapper's bubblewrap masks and denied probes.
The validator loaded inside the namespace is the adapter copied under the
relocated bundle's `runtime/` directory.

After the positive replay, it creates one full private copy at a time. The
first copy changes one `/transport/particle_zone` endpoint label, and the
second changes one valid `/transport/destination_position` coordinate while
leaving displacement unchanged. Each copy refreshes the normalized HDF5,
interface, reader-manifest, and bundle-manifest hashes before invoking the
bundled production validator. The expected failures therefore demonstrate
semantic rejection after digest re-binding. Each private copy is removed
before the next one, and the original source bundle is hashed before and
after the audit.

The source completion receipt must be a completed
`ds-data-02.m4.direct-enrichment-receipt.v1` (or the equivalent actual source
bundle receipt schema) with `outputs.interface` and `outputs.enriched_hdf5`
bindings. The helper verifies those files and their hashes, the source bundle
manifest, and the full production bundle validator before writing a request.

Prepare a request after the root has completed enrichment and built the actual
portable bundle:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_actual_validation.py prepare-request \
  --source-receipt /data/nas/.../m4-enriched/enrichment-receipt.json \
  --source-bundle /data/nas/.../m4-portable/UF_F1_MDBC_DP010_H050 \
  --output-request /path/to/root-reviewed-request.json \
  --isolation-wrapper ../m4_isolated_validate.py \
  --python /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
```

The generated runner command contains `{attempt_root}` placeholders. Root must
submit it through the shared runner so both the relocation destination and
reports are under a fresh absolute NAS attempt root. Direct execution of the
`run` subcommand is reserved for that runner.
