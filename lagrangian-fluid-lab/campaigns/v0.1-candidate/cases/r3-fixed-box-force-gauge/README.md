# R3 fixed immersed box force gauge

This is an isolated, candidate-only DualSPHysics case for checking a force
gauge on a genuinely fixed immersed body.  The body is a `0.2 m` cube made
with `setmkbound mk="1"` and is deliberately not listed under `<floatings>`:
GenCase and the solver must report it as a fixed-boundary block with zero
moving/floating particles.

Two bounded controls are materialised and run:

* `fixed-box-dbc-gravity`: DBC with the hydrostatic density/pressure initial
  gradient (`rhopgradient=2`) and `g=-9.81 m/s²`.
* `fixed-box-dbc-zero-pressure`: DBC with a uniform `rhop0` initial state
  (`rhopgradient=1`) and `g=0`; this is a reinitialised zero-pressure control,
  not a gravity-only edit.

The bounded mDBC follow-up is kept separate from those DBC controls:

* `fixed_box_mdbc_canonical_Def.xml`: the same physical tank and fixed cube at
  `dp=0.025 m` (`canonical-2`).
* `fixed_box_mdbc_fine_Def.xml`: the same physical geometry at `dp=0.0125 m`
  (`fine-3`).

Both mDBC cases use `GeometryForNormals` only for normal construction, keep the
physical cube void at `[0.50,0.70] x [0.30,0.50] x [0.20,0.40] m`, and map source
`mkbound=1` to fixed particles.  Their bounded report is
[`mdbc-fixed-box-force-gauge-report.md`](mdbc-fixed-box-force-gauge-report.md);
the dedicated runner is
[`run_mdbc_fixed_box_force_gauge.py`](run_mdbc_fixed_box_force_gauge.py).

The nominal analytical pressure resultant for a fully submerged `0.2 m` cube
is `rho*g*V = 1000*9.81*0.2^3 = 78.48 N` in `+z`.  It is a pre-registered
reference only; no run is accepted from that number alone.  The gauge reports
pressure interaction on the selected boundary particles only.  It excludes
body weight, any support reaction, and viscosity.

## Reproduction

From the repository root:

```bash
python3 lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-fixed-box-force-gauge/run_fixed_box_force_gauge.py
```

The runner performs a live `nvidia-smi` check, selects one idle GPU from the
allowed 4--7 range, records its UUID before each launch, runs GenCase and the
GPU solver for both controls, and leaves immutable attempt directories.  It
also copies the signed `forcex/forcey/forcez` gauge samples into each result
directory and writes a machine-readable report.

## Status rule

The generated and run artifacts are evidence, not an automatic physical
acceptance.  The report keeps execution, data-integrity gates, and acceptance
separate.  In particular, a finite force trace can still be rejected if the
fixed/mk mapping, pressure fields, mass, penetration, or stable-window checks
fail.

The mDBC follow-up is deliberately still `candidate_not_accepted`: the
canonical run has 63 runtime zero normals and 27 final fluid penetrations; the
fine run has 240 runtime zero normals, 20 excluded particles, and 197 final
penetrations.  Their late force means are respectively 93.397 N and 80.789 N,
but both fail the stability gate.  These negative results block a development
tranche; they do not justify a radius scan or a formal v0.1 physical freeze.
