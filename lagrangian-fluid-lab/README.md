# Lagrangian Fluid Exploration Lab

This directory contains exploratory cases, an isolated official toolchain,
generated data, conversion code, and reports for a Lagrangian fluid benchmark
based on DualSPHysics. It is a **path-finding lab**, not a claim that the current
coarse runs are converged CFD reference data.

The parent DualSPHysics checkout is treated as an immutable upstream snapshot.
Nothing in `src/`, `bin/`, `examples/`, or other upstream-controlled paths is
modified by this lab.

## Exploration scope

The first pass favors broad mechanism coverage over resolution. Cases should
normally contain only a few thousand to a few tens of thousands of fluid
particles and run for a short physical duration.

Planned families:

- `F1`: dam break, obstacle splitting, and re-merging
- `F2`: pouring, receiving, retention, and spilling
- `F3`: sloshing, baffles, and repeated impacts
- `F4`: finite liquid columns/jets, collision, and deflection
- `F5`: wave run-up, overtopping, and return flow
- `F6`: water entry and freely moving rigid bodies
- `C0`: calibration and trajectory-semantics checks

## Directory contract

- `vendor/`: isolated DualSPHysics source/binary snapshot and build products
- `cases/`: declarative case inputs and generated case files
- `runs/`: raw simulation outputs and logs
- `scripts/`: orchestration, inspection, and conversion utilities
- `data/`: normalized exploratory datasets
- `reports/`: machine-readable inventories and human-readable findings

Raw BI4 outputs are retained so normalized data can always be traced back to
the exact solver configuration and executable.

## What has been exercised

- Official DualSPHysics 5.4.3 package downloaded and checksum-recorded.
- 21 custom low-particle 3-D probes generated with shifting disabled.
- 9 probes derived from official examples, including prescribed sloshing,
  solitary-wave propagation, moving-piston run-up, open boundaries, free rigid
  bodies, and variable resolution.
- All 30 probes completed at solver level on GPUs 4--7.
- BI4 output converted through the official `PartVTK` utility and normalized to
  padded HDF5 trajectories with validity masks.
- The R3 F4 O4 impinging-jet observation path was exercised at three resolutions
  with fixed-point pressure/velocity/Kcorr, two-dimensional wall force, open-
  boundary box flux, and solver lifecycle bookkeeping. These are candidate
  diagnostics, not external physical labels.
- The R3 F4 isolated 3-D head-on liquid-column path was exercised at
  `dp=0.04/0.03/0.02 m` through `t=0.55 s`, including fixed-point fields and
  requested/effective `ComputeForces` targets. The generated `Mk=17` versus
  requested `Mk=10` mismatch is retained as a blocker; this is candidate-only.
- R3 contract hardening now rejects non-finite affine translations, invalid
  mass fractions, and W11 bad files (identity resurrection, mass changes, and
  NaN density) before atomic publication. The coverage audit separates legacy
  `status=complete` from execution, acceptance, scope, and blockers; W08's
  204 continuous-axis cards remain planned-only. Four explicitly separate
  topology-extrapolation cards now have independent evidence: F1/F2/F3
  completed GenCase–solver–PartVTK–HDF5 structural paths, while F6 completed
  GenCase plus a micro-horizon solver structural probe without normalized HDF5;
  all remain candidate-only.
- The 12 released F1/F2/F3 fluid cases have finite world-space boundary
  sidecars. Release-linkage and byte-identity checks pass, while destination
  and open-face semantics remain candidate-only. An identity-permutation
  transport control is part of the protocol so set-based point metrics cannot
  substitute for material history.
- The G4 CPU causality audit passes prefix invariance, endpoint independence,
  future-control isolation, and future-free-body isolation. Constant-velocity
  degradation remains a diagnostic, never a scene-admission gate.
- The R3 lineage diagnostic preserves the historical W08/W10 mismatch as a
  regression fixture: the old family-shared lineage labels crossed five split
  classes, while the current exact-physical-case lineage contract passes both
  audits. This is a contract result, not evidence that historical data were
  physically revalidated.
- A CPU-only synthetic tracer-visibility suite confirms that finite triangle
  barriers remove cross-partition contamination (legacy contaminant weight
  `0.875` to wall-aware `0`), while a narrow opening leaves only 23 visible
  neighbours and is conservatively rejected. With no barrier triangles,
  geometry-only visibility cannot distinguish disconnected liquid blobs
  (contaminant weight `0.672`, wrong-direction rate `1.0`); both candidate
  guards remain rejected and production tracer code is unchanged.
- An independent R3 G4 sidecar re-ran LocalInteraction and PhysicsResidual at
  seeds `17/29/43` on physical GPUs 4/5 (6/6 completed) and audited all four
  routes at 43-wide inputs with current boundary sidecars. The tiny-budget
  results are stability/input-contract diagnostics only, not a ranking.
- The F6 R3 evidence includes a CPU-only mDBC initialization preflight.
  `Boundary=2` and the official normals path execute, but 792/24,335 boundary
  normals are zero and a floating-body Chrono warning remains; this is not
  physical mDBC acceptance. A follow-up CPU-only 20-variant sweep found
  inward normal-geometry offsets of `-0.030 m` and `-0.020 m` with zero
  serialized zero normals at `dp=0.060 m`; they alter the geometry contract and
  remain candidate-only/rejected pending physical revalidation. A separate
  static-buoyancy calculation likewise remains diagnostic-only.
- Structural and semantic quality gates passed 29 probes and rejected one
  deliberately retained coarse-resolution failure.
- W00--W12 then exercised protected provenance, identity/reference-frame
  semantics, independent material tracing, calibration, three external
  validation anchors, a real 12-case rotating-cup matrix, causal design cards,
  open/multiresolution lifecycle extensions, a release schema, a 13-case
  development package, and six real learned-baseline runs.

See [campaigns/v0.1-candidate/W12-CONCLUSION.md](campaigns/v0.1-candidate/W12-CONCLUSION.md)
for the current freeze decision and `campaigns/v0.1-candidate/work-packages.json`
for package status. The original broad-pass findings remain in
[reports/findings.md](reports/findings.md).

## Reproduce the exploration

The official package is expected at
`vendor/official/DualSPHysics_v5.4`. Create the Python environment once:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then run the custom probes:

```bash
python scripts/generate_cases.py
python scripts/prepare_cases.py
python scripts/run_cases.py --gpus 4,5,6,7
python scripts/postprocess_cases.py
```

Run the official-example probes and final audits:

```bash
python scripts/prepare_official_probes.py
python scripts/run_official_probes.py
python scripts/postprocess_official_probes.py
python scripts/audit_quality.py
python scripts/plot_probe_montage.py
```

Both GPU runners maintain one sequential queue per physical GPU. Use `--cases`
to rerun selected probes without discarding the other report entries.

## Normalized HDF5 contract

Each file contains `time[T]`, identity axes `particle_id[N]` and
`particle_zone[N]`, a lifecycle mask `valid[T,N]`, and particle fields
`position[T,N,3]`, `velocity[T,N,3]`, `density[T,N]`, `mass[T,N]`,
`pressure[T,N]`, `type[T,N]`, and `mk[T,N]`.

Identity has three distinct meanings:

- Fixed-resolution closed cases use stable `Idp` as numerical SPH-particle identity.
- Open-boundary cases use `valid` to represent particle birth and departure.
- Variable-resolution output uses `(particle_zone, particle_id)` as a numerical-node
  key. It is not yet a material-lineage guarantee across split/merge operations.

For that reason, this pilot supports a **numerical particle dynamics** track.
A future **material trajectory** track still needs validated tracers or material
lineage independent of node shifting, injection, and adaptive resolution.

## Current storage footprint

At the time of the pilot, normalized HDF5 is about 31 MiB, raw run output about
306 MiB, copied/generated cases about 46 MiB, and the extracted official package
about 1.7 GiB. These values are exploration-scale measurements, not production
capacity estimates.

## Next decision gate

The engineering, identity, causal-split and metric contracts are ready to freeze
as development interfaces, but the material-tracer implementation is still a
candidate reference (its wall visibility, convergence and destination closure
are not accepted physical truth) and the formal dataset is not. R3 has now
executed the F6 Test 14 three-dimensional route, but its current DBC proxy is
scientifically rejected; the isolated mDBC preflight reaches the intended
initialization path without establishing complete normals or physical
acceptance. Likewise, both F4 observation paths are diagnostic only and have
no external anchor. Close the remaining family-specific gaps first: F1 impact
pressure, F2 pouring resolution and external observation, F3 impact
timing/cadence, compatible external F4/F5 anchors, and a validated
mDBC/Chrono/larger-domain F6 route. Only passing families should enter a
20--30 case development tranche before formal production scale is chosen.
