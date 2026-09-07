# R5 F1 material task

This directory freezes the CPU material-transport contract for the F1
single-obstacle case. `source_label` is computed from the initial fluid depth
(`lower` / `middle` / `upper`) and is a measurement stratum only; it is not a
post-mixing material identity.

The evaluator consumes an already normalized solver HDF5 and its finite
boundary sidecar. It does not invoke DualSPHysics, GenCase, CUDA, or a GPU.
The default bounded matrix is four groups: 128/256 seeds by 2/4 tracer
substeps, with an eight-group hard limit.

Run the contract-only check with:

```bash
PYTHONPATH=. .venv/bin/python scripts/r5_f1_material_task.py audit
```

Run after the new F1 medium/fine HDF5 and linked sidecar are available:

```bash
PYTHONUNBUFFERED=1 .venv/bin/python scripts/r5_f1_material_task.py run \
  --hdf5 campaigns/v0.1-candidate/data/R4_F1_center_obstacle_medium.h5 \
  --sidecar campaigns/v0.1-candidate/sidecars/r5-f1/R4_F1_center_obstacle_medium.h5 \
  --case-id R4_F1_center_obstacle_medium \
  --output-dir campaigns/v0.1-candidate/artifacts/r5-f1-material-task
```

Use `--particle-spacing 0.024` or `--particle-spacing 0.014` when a future
HDF5 does not carry a `particle_spacing_m`/`dp` attribute. The report and each
trajectory bundle record input, resolved-spec, and evaluator SHA-256 hashes.

The output keeps target, in-domain non-target, legitimate exit, numerical
loss, and tracer-unknown mass separate. A tracer failure censors first passage
and is never converted into a negative no-event label.

The fixture JSON documents the CPU-only test fixture. The binary HDF5 fixture
is created in pytest temporary storage so no synthetic data is added to the
release tree.
