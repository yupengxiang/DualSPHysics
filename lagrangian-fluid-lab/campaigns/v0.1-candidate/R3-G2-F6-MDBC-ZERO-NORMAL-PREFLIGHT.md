# R3 G2 F6 mDBC zero-normal preflight

Candidate-only, rejected diagnostic experiment. It does not modify or replace the existing DBC Test14 route, and it makes no physical mDBC acceptance claim.

## Baseline and location

- Existing isolated mDBC preflight baseline: `792` fixed/moving zero normals at `dp=0.060 m`.
- The serialized baseline zeros are tank-side particles: `44` circumferential lattice columns × `18` z layers, with fixed-particle radius approximately `1.953146 m`; floating zero count is `0`.
- This is the cylinder normal polygon's inscribed-edge midpoint radius, so the normal surface and those boundary particles are coincident. A zero-length boundary-to-limit vector is therefore plausible; this is a geometry-path diagnosis, not a physics conclusion.

## Variant matrix

| Variant | Normal geometry | mask | tank radius [m] | distanceh | invert tank/Float1 | BoundNor nonzero/zero (fixed/float) | CPU init |
|---|---|---:|---:|---:|---|---:|---|
| `baseline_combined_mask2_d2_invert` | tank+float1_outer | 2 | 2.00 | 2.0 | true/false | 23543/792 (792/0) | True (`0`) |
| `tank_only_mask2` | tank_only | 2 | 2.00 | 2.0 | true/false | 23403/932 (792/140) | True (`0`) |
| `float1_outer_only` | float1_outer_only | 2 | 2.00 | 2.0 | true/false | 140/24195 (24195/0) | True (`0`) |
| `combined_mask1` | tank+float1_outer | 1 | 2.00 | 2.0 | true/false | 13540/10795 (10795/0) | True (`0`) |
| `combined_mask3` | tank+float1_outer | 3 | 2.00 | 2.0 | true/false | 13496/10839 (10839/0) | True (`0`) |
| `combined_distanceh4` | tank+float1_outer | 2 | 2.00 | 4.0 | true/false | 23543/792 (792/0) | True (`0`) |
| `combined_tank_invert_false` | tank+float1_outer | 2 | 2.00 | 2.0 | false/false | 5968/18367 (18367/0) | True (`0`) |
| `combined_float_invert_true` | tank+float1_outer | 2 | 2.00 | 2.0 | true/true | 23466/869 (792/77) | True (`0`) |
| `combined_tank_radius_plus003` | tank+float1_outer | 2 | 2.03 | 2.0 | true/false | 21599/2736 (2736/0) | True (`0`) |
| `combined_tank_radius_plus006` | tank+float1_outer | 2 | 2.06 | 2.0 | true/false | 19871/4464 (4464/0) | True (`0`) |
| `combined_tank_radius_plus010` | tank+float1_outer | 2 | 2.01 | 2.0 | true/false | 22895/1440 (1440/0) | True (`0`) |
| `combined_tank_radius_plus015` | tank+float1_outer | 2 | 2.02 | 2.0 | true/false | 22751/1584 (1584/0) | True (`0`) |
| `combined_tank_radius_plus020` | tank+float1_outer | 2 | 2.02 | 2.0 | true/false | 22319/2016 (2016/0) | True (`0`) |
| `combined_tank_radius_plus025` | tank+float1_outer | 2 | 2.02 | 2.0 | true/false | 22175/2160 (2160/0) | True (`0`) |
| `combined_tank_radius_plus035` | tank+float1_outer | 2 | 2.04 | 2.0 | true/false | 21311/3024 (3024/0) | True (`0`) |
| `combined_tank_radius_plus040` | tank+float1_outer | 2 | 2.04 | 2.0 | true/false | 21167/3168 (3168/0) | True (`0`) |
| `combined_tank_radius_plus045` | tank+float1_outer | 2 | 2.04 | 2.0 | true/false | 20735/3600 (3600/0) | True (`0`) |
| `combined_tank_radius_plus050` | tank+float1_outer | 2 | 2.05 | 2.0 | true/false | 20447/3888 (3888/0) | True (`0`) |
| `combined_tank_radius_minus030` | tank+float1_outer | 2 | 1.97 | 2.0 | true/false | 24335/0 (0/0) | True (`0`) |
| `combined_tank_radius_minus020` | tank+float1_outer | 2 | 1.98 | 2.0 | true/false | 24335/0 (0/0) | True (`0`) |

## Findings

- Composition: The baseline zero block is tank-side: removing Float1 leaves the fixed zero pattern, while removing the tank transfers missing coverage to fixed tank particles and leaves the floating Float1 boundary covered.
- Tank mask/caps: Changing the tank cylinder mask/cap selection does not remove the side-wall zero block when the side mesh remains coincident with a boundary layer.
- `distanceh`: Increasing the search distance does not repair vectors whose nearest normal surface is coincident with the boundary particle; it changes the search radius, not the zero-length boundary-to-limit vector.
- `setnormalinvert`: inversion is not the baseline source: tank=false worsens the zero count to 18,367 and Float1=true gives 869 total zeros (including 77 floating); neither tested inversion repairs the baseline tank-side zero block.
- Radius offset: The -0.030 m tank-normal radius candidate removed serialized zero BoundNor vectors in this coarse preflight. It remains candidate-only and is not physically accepted.

## Vendored v5.4 evidence

- `JPartsLoad4.cpp`: v5.4 stores `BoundNor` in the general BI4 and checks its boundary-sized array.
- `JSph.cpp`: `Boundary=2` enables mDBC normal use; initialization counts fixed/moving and floating zero normals and writes `CfgInit_NormalsGhost.vtk`.
- `JSphCpu_mdbc.cpp`: CPU mDBC skips zero `BoundNor` entries and forms the ghost point from the boundary position plus `BoundNor`.
- Official v5.4 `examples/mdbc/08_FloatingWaves` and `09_FloatingDuck`: `GeometryForNormals` → `shapeout file="hdp"` → `norgeometry` → `Boundary=2`.

## Rejection / non-claims

- All matrix results are candidate-only diagnostics; no mDBC physical acceptance is claimed.
- A zero-normal repair must be revalidated at intended resolution and with controlled geometry semantics before any physical run.
- The short CPU runs only establish that the initialization path reaches a return-code-0 endpoint; they do not validate forces, trajectories, or buoyancy.

Evidence paths:

- Candidate XML directory: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-mdbc-zero-normal-preflight`
- GenCase artifacts: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/artifacts/r3-g2-f6-mdbc-zero-normal-preflight`
- CPU run artifacts: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/runs/r3-g2-f6-mdbc-zero-normal-preflight`
- JSON report: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/r3-g2-f6-mdbc-zero-normal-preflight.json`
