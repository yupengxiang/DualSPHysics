# R3 G4 baseline route sidecar

This directory is an independent, candidate-only audit and small rerun for
the two non-direct routes already implemented by the corrected R3 G4 trainer:

* `local_interaction`: direct next-velocity prediction augmented with a fixed
  eight-neighbour inverse-distance position/velocity summary.
* `physics_residual`: normalized acceleration residual, integrated from the
  current velocity before the same trapezoidal position update.

The audit also checks that Particle MLP, DeepSets, LocalInteraction, and
PhysicsResidual share the same 43-wide semantic input contract: current
centered position, rollout-consistent velocity, initial density/pressure/mass,
gravity, static physics, current prescribed control, current boundary AABB,
family identity, elapsed time, and current `dt`.  Release-linked boundary
sidecars are required to align frame-for-frame and carry
`boundary-sidecar-v1` provenance.  The fluid-less F6 body-only case is
explicitly excluded by the loader rather than silently treated as fluid.

## Reproduce

From the repository root:

```sh
python lagrangian-fluid-lab/experiments/r3-g4-baseline-routes/audit_routes.py \
  --output lagrangian-fluid-lab/experiments/r3-g4-baseline-routes/audit.json

python lagrangian-fluid-lab/experiments/r3-g4-baseline-routes/run_candidate.py

python -m pytest -q \
  lagrangian-fluid-lab/experiments/r3-g4-baseline-routes/test_baseline_routes.py
```

The rerun uses three seeds (`17, 29, 43`), three requested epochs with small
particle/hidden widths, and only physical GPUs 4 and 5.  Each child process
gets one physical GPU through `CUDA_VISIBLE_DEVICES`; inside the child it is
visible as `cuda:0`.  The manifest records the physical index, UUID, driver,
memory snapshot, command, and output status.  The route JSONs are copied from
the shared trainer into this directory's own `results/`; they do not replace
the established matrix.

The artifacts are diagnostics only.  They do not claim a ranking, formal
release readiness, wall-contact validity, material transport, density/pressure
prediction, free-body coupling, or physical-scene acceptance.
