# Q2 — complete official mDBC recipe bridge

## Purpose and gate

Q2 tests one bounded L1 bridge case using the complete official mDBC recipe.
It is a development diagnostic only. The case is not a formal release and was
not authorized for training or a broad parameter grid.

The machine-readable record is
[`Q2-MDBC-BRIDGE-RESULTS.json`](Q2-MDBC-BRIDGE-RESULTS.json). The normalized
HDF5 and full audit are retained under the ignored `data/` and `artifacts/`
subtrees listed in that record.

## Case and recipe

Case: `L1R_Q2_MDBC_BRIDGE_h11_fine_dp0p01_cfl005_t0p6`

- Background: retained L1 W1 space h11/fine configuration; `dp=0.01`,
  `cfl=0.05`, `TimeMax=0.6`, `TimeOut=0.001`.
- Boundary geometry: finite tank `x=[0,1.2]`, `y=[0,0.4]`, `z=[0,0.6]`; the
  five physical faces are closed and the top is open.
- mDBC recipe: five separate `GeometryForNormals` face drawboxes with
  `layers vdp=-0.5`, a main boundary drawbox with `layers vdp=0,1,2`,
  `_shapeout file="parts"`, active normals, `distanceh=2.0`, `svshapes=true`,
  `Boundary=2`, `SlipMode=1`, and `NoPenetration=0`.
- The candidate source is isolated under
  `cases/q2-mdbc-bridge/`; the official reference XML remains unchanged.

GenCase completed with 135,975 total particles: 60,060 fluid and 75,915
boundary particles. The normal-generation log contained the expected
non-zero-normal evidence. The manifest records the source, candidate, and
generated-input SHA-256 values.

## Execution and normalization

The bounded solver run completed on allowlisted GPU 4:

| item | result |
|---|---|
| solver status | completed, return code 0 |
| elapsed time | 131.25813223607838 s (0.03646059228779955 GPU h) |
| guard/timeout/interruption | none |
| required solver text | found |
| raw frames | 601 (`Part_0000.bi4` … `Part_0600.bi4`) |
| raw BI4 evidence | 3,596,915,885 bytes |
| normalized HDF5 | 601 frames, time 0.0–0.60001 s |
| normalized arrays | valid `(601, 60060)`, positions `(601, 60060, 3)` |

The normalized file SHA-256 is
`c754836e6c1357b2ea6e92a45a2ed85937d1eb51b1165cd5d29a15675d422fbb`.

## Audit result

The production R5/R6 audit returns `quality_failed`:

- finite bottom-face endpoint penetration begins at frame 403,
  `t=0.403014 s`, with one particle (`0.001 kg`);
- 198 frames contain finite closed-container penetration, with maximum outside
  mass `0.03200000151991844 kg`;
- no runtime-domain excursions, no swept finite-face crossings, and no solver
  position exclusions were recorded;
- initial fluid mass is `60.060002852696925 kg`, final valid mass is the same,
  and the final valid fraction is `1.0`.

The equal initial/final mass does not cancel the finite-wall failure: the
penetration is a geometric quality issue even though no particles were removed
from the normalized sequence.

## Decision

Q2 demonstrates that the complete official mDBC recipe is executable in the
isolated L1 geometry, but it is not a positive L1 boundary result. Do not
promote this case to formal release, training, or a larger grid. The next
review decision is whether to make one further bounded recipe/geometry repair
and rerun the same diagnostic case, or close the F1 path and use the planned
fallback.
