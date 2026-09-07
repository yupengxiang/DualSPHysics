# R3-F6 canonical mDBC geometry — E0

**Status:** `candidate` overall; `pass` for canonical geometry/serialization; `blocked` for downstream physical mDBC acceptance. CPU/GenCase only; no GPU was used.

This package keeps the physical wall at the intended location and rebuilds the numerical boundary layer and normal construction independently. It does not modify the formal tracer or schema.

## Geometry contract

`GeometryForNormals` is the normal-construction surface written to `*_hdp_Actual.vtk`; `mainlist` is the actual boundary-particle layer. The solver artifacts are interpreted as:

```text
x_b     = POINTS(CfgInit_Normals.vtk)
n_b     = FIELD/Normal(CfgInit_Normals.vtk)
n_g     = FIELD/Normal(CfgInit_NormalsGhost.vtk) = 2 n_b
x_g     = x_b + n_g
x_gamma = (x_b + x_g)/2 = x_b + n_g/2
```

The ghost-file `POINTS` are checked to be the same `x_b`; they are not silently treated as ghost coordinates.

| case | generated particles (bound/fixed/float/fluid) | zero normals | max `|n_g-2n_b|` | physical-interface residual | geometry | mDBC physics |
|---|---:|---:|---:|---:|---|---|
| `canonical_rectangular` | 1476/1476/0/441 | 0 | 0 | 1.61e-08 m | `pass` | `blocked` |
| `canonical_float1_cylinder` | 1677/1593/84/420 | 0 | 0 | 0.000757 m | `pass` | `blocked` |

## Corrected E0 rationale

- **Rectangular wall:** the XML box is the canonical nominal wall (`x=0..0.4`, `y=0..0.3`, `z=0`, top open). Only `GeometryForNormals` carries `layers vdp="-0.5"`, so its `hdp_Actual` surface is the physical inner wall (`x/y=0.02..0.38/0.28`, `z=0.02`). The actual shell is independently generated with `vdp="0,1,2"`. This is one half-`Dp` reconstruction shift, not two.
- **Float1 cylinder:** the normal-construction cylinder is explicitly `R=0.11 m`, `z=0.14..0.30 m` in the named `GeometryForNormals` list. The actual Float1 boundary cylinder is separately `R=0.08 m`, `z=0.16..0.28 m`, `vdp="0,-1,-2"` in `mainlist`. The parser checks those named lists and proves they are distinct; it never chooses the first global `drawcylinder`.
- **Normals and ghost/interface:** all final boundary normals are non-zero; the solver's ghost array is exactly doubled; `x_gamma` lands on the canonical tank faces and the `R=0.11 m` cylinder within the reported raster tolerance. Corners/edges are included in the audit; the weak corner orientation threshold (`dot >= 0.5`) reports weighted lattice-corner normals without pretending they are analytic face sums.

## Actual-generation evidence

Both cases have checked-in `gencase.log`, `bifileinfo.log`, generated `.bi4/.xml/.vtk`, `solver.log`, `CfgInit_Normals.vtk`, and `CfgInit_NormalsGhost.vtk`. GenCase and one-step `DualSPHysics5.4CPU` both finish with code 0. No GPU was used because the E0 audit is CPU-first.

The one-step solver is an initialization smoke test only. It does not supply a hydrostatic pressure/force gauge or displaced-volume closure. The Float1 log also contains the official warning that floating mDBC collisions should use Chrono (`RigidAlgorithm=3`); therefore the physical mDBC gate stays `blocked` even though the E0 geometry gate is `pass`.

## Machine-readable handoff

- JSON: `diagnostics/r3_f6_canonical_geometry/canonical-geometry.json`
- pytest: `diagnostics/r3_f6_canonical_geometry/test_canonical_geometry.py`
- Official local references: XML mDBC guide, `JPartsLoad4.cpp`, `JSph.cpp`, and `JSphCpu_mdbc.cpp` listed in the JSON.
