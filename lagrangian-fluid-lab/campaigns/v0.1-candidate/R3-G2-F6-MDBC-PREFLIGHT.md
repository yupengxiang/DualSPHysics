# R3 G2 F6 mDBC preflight

This is a diagnostic preflight only. It does not accept mDBC physics and does not replace the existing DBC Test14 route.

## Result

- Case: `R3_F6_mdbc_preflight_neg074_coarse`; Float1 offset `-0.074 m`; dp `0.060 m`; `TimeMax=0.08` s.
- Requested boundary: **mDBC** (`Boundary=2`); effective solver boundary: **mDBC**.
- GenCase return code: `0`; CPU solver return code: `0`.
- GenCase normals: `23543` non-zero / `24335` boundary; zero `792` (`3.3%`).
- Serialized `BoundNor` inspection: zero `792`; fixed zero `792`; floating zero `0`.
- Solver zero normals: fixed/moving `792`; floating `0`.
- Ghost path: `CfgInit_NormalsGhost.vtk` present = `True`; point count = `24335`.
- Normal completeness: **False**.

## XML legality

- Existing F6/Test14 XML: requested `DBC` (`Boundary=1`), normals section present = `False`; direct mDBC switch legal = **False**.
- Isolated candidate: requested `mDBC` (`Boundary=2`), normals list/runlist/hdp geometry = `True`/`True`/`True`; legal structure = **True**.

## Real v5.4 data path

- GenCase emits a `BoundNor` float3 array in the general input `.bi4`; the generated XML references `[CaseName]_hdp_Actual.vtk` as the normal geometry source.
- The solver loads `BoundNor`; for a new run it doubles the boundary-to-limit vector to form the boundary-to-ghost vector and writes both `CfgInit_Normals.vtk` and `CfgInit_NormalsGhost.vtk`.
- A solver `Finished execution (code=0)` is not sufficient: zero-normal warnings remain a blocker for complete mDBC coverage.
- The isolated candidate follows the official v5.4 floating mDBC pattern (`GeometryForNormals` → `shapeout file="hdp"` → `norgeometry` → `Boundary=2`) and uses the CPU solver, so no GPU index or UUID was used.
- Source evidence is pinned to the vendored v5.4 files in the JSON report: `JPartsLoad4.cpp` (BoundNor load), `JSph.cpp` (Boundary/normal initialization), `JSphCpu_mdbc.cpp` (ghost position), and the official FloatingWaves/FloatingDuck XML examples.

## Blockers / non-claims

- This is a short coarse CPU preflight, not a Test14 physical acceptance run.
- No DBC-vs-mDBC trajectory or buoyancy comparison was performed.
- The existing F6/Test14 XML remains DBC (Boundary=1) with no normals section.
- GenCase reported 792 zero boundary normals; normal completeness is not established.
- Solver reported 792 fixed/moving particles without normals.
- Solver warns floating mDBC collisions should use Chrono (RigidAlgorithm=3).

Evidence files:

- Candidate XML: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse_Def.xml`
- GenCase log: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/artifacts/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse/generated/gencase.stdout.log`
- Solver log: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/runs/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse/solver.stdout.log`
- JSON report: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/v0.1-candidate/r3-g2-f6-mdbc-preflight.json`
