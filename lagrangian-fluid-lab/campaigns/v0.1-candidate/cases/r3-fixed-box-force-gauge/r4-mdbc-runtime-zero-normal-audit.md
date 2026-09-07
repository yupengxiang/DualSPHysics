# R4 F6 fixed-box mDBC runtime zero-normal audit

> CPU/static evidence only. This audit reads existing artifacts and does not launch CFD, a solver, GPU work, or `nvidia-smi`.

## 判定摘要

The runtime zero criterion is `||FIELD/Normal|| <= 1e-12 m`; exact serialized all-zero vectors are reported separately. `CfgInit_Normals.vtk` POINTS are `x_b`, and the effective interface is reconstructed as `x_gamma = x_b + n_ghost/2`.

| resolution | dp (m) | runtime zero normals | fraction | zero by Mk | Ghost≈2×Normal | construction faces |
|---|---:|---:|---:|---|---|---|
| `canonical-2` | 0.025 | 63 / 22515 | 0.279813% | {'17': 0, '18': 63} | `PASS` | `PASS` |
| `fine-3` | 0.0125 | 240 / 87979 | 0.272792% | {'17': 0, '18': 240} | `PASS` | `PASS` |

## 面级零法向取证

Face rows are incident counts, so edge/corner points appear on each incident face. The exclusive partition is face interior (one plane), edge excluding corners (two planes), and corner (three planes).

### `canonical-2`

| item | total points | zero normals | near-zero normals |
|---|---:|---:|---:|
| face `x_min` (incident) | 179 | 63 | 63 |
| face `x_max` (incident) | 113 | 0 | 0 |
| face `y_min` (incident) | 139 | 7 | 7 |
| face `y_max` (incident) | 140 | 7 | 7 |
| face `z_min` (incident) | 113 | 0 | 0 |
| face `z_max` (incident) | 113 | 0 | 0 |
| edge `x_min__y_min` | 26 | 7 | 7 |
| edge `x_min__y_max` | 27 | 7 | 7 |
| edge `x_max__y_min` | 18 | 0 | 0 |
| edge `x_max__y_max` | 18 | 0 | 0 |
| edge `x_min__z_min` | 9 | 0 | 0 |
| edge `x_min__z_max` | 9 | 0 | 0 |
| edge `x_max__z_min` | 9 | 0 | 0 |
| edge `x_max__z_max` | 9 | 0 | 0 |
| edge `y_min__z_min` | 18 | 0 | 0 |
| edge `y_min__z_max` | 18 | 0 | 0 |
| edge `y_max__z_min` | 18 | 0 | 0 |
| edge `y_max__z_max` | 18 | 0 | 0 |
| corner `x_min__y_min__z_min` | 6 | 0 | 0 |
| corner `x_min__y_min__z_max` | 6 | 0 | 0 |
| corner `x_min__y_max__z_min` | 6 | 0 | 0 |
| corner `x_min__y_max__z_max` | 6 | 0 | 0 |
| corner `x_max__y_min__z_min` | 6 | 0 | 0 |
| corner `x_max__y_min__z_max` | 6 | 0 | 0 |
| corner `x_max__y_max__z_min` | 6 | 0 | 0 |
| corner `x_max__y_max__z_max` | 6 | 0 | 0 |

Exclusive partition:

- `face_interior`: 259 points, 49 zero, 49 near-zero.
- `edge_excluding_corners`: 197 points, 14 zero, 14 near-zero.
- `corner`: 48 points, 0 zero, 0 near-zero.
- `off_surface_or_unexpected_incidence`: 0 points, 0 zero, 0 near-zero.

By Mk: `{"17": 0, "18": 63}`; exact vector zeros: `0`.

### `fine-3`

| item | total points | zero normals | near-zero normals |
|---|---:|---:|---:|
| face `x_min` (incident) | 1000 | 240 | 256 |
| face `x_max` (incident) | 742 | 0 | 0 |
| face `y_min` (incident) | 679 | 0 | 0 |
| face `y_max` (incident) | 936 | 15 | 31 |
| face `z_min` (incident) | 742 | 0 | 0 |
| face `z_max` (incident) | 998 | 0 | 256 |
| edge `x_min__y_min` | 49 | 0 | 0 |
| edge `x_min__y_max` | 115 | 15 | 15 |
| edge `x_max__y_min` | 49 | 0 | 0 |
| edge `x_max__y_max` | 98 | 0 | 0 |
| edge `x_min__z_min` | 49 | 0 | 0 |
| edge `x_min__z_max` | 64 | 0 | 15 |
| edge `x_max__z_min` | 49 | 0 | 0 |
| edge `x_max__z_max` | 49 | 0 | 0 |
| edge `y_min__z_min` | 49 | 0 | 0 |
| edge `y_min__z_max` | 49 | 0 | 0 |
| edge `y_max__z_min` | 98 | 0 | 0 |
| edge `y_max__z_max` | 113 | 0 | 15 |
| corner `x_min__y_min__z_min` | 7 | 0 | 0 |
| corner `x_min__y_min__z_max` | 7 | 0 | 0 |
| corner `x_min__y_max__z_min` | 14 | 0 | 0 |
| corner `x_min__y_max__z_max` | 15 | 0 | 1 |
| corner `x_max__y_min__z_min` | 7 | 0 | 0 |
| corner `x_max__y_min__z_max` | 7 | 0 | 0 |
| corner `x_max__y_max__z_min` | 14 | 0 | 0 |
| corner `x_max__y_max__z_max` | 14 | 0 | 0 |

Exclusive partition:

- `face_interior`: 3180 points, 225 zero, 450 near-zero.
- `edge_excluding_corners`: 831 points, 15 zero, 45 near-zero.
- `corner`: 85 points, 0 zero, 1 near-zero.
- `off_surface_or_unexpected_incidence`: 0 points, 0 zero, 0 near-zero.

By Mk: `{"17": 0, "18": 240}`; exact vector zeros: `0`.

## Ghost、生成期与运行时

The ghost contract compares both vector and scalar size fields against exactly twice the normal field, while also checking that POINTS and Mk remain identical. The generated `Bound.vtk` is compared directly with runtime `CfgInit_Normals.vtk` when present.

| resolution | max `|n_g-2n_b|` | max `|size_g-2size_b|` | Bound vs runtime | GenCase reported zero | serialized threshold zero |
|---|---:|---:|---|---:|---:|
| `canonical-2` | 0 | 0 | `exact` | 0 | 63 |
| `fine-3` | 0 | 0 | `exact` | 0 | 240 |

Interpretation: both GenCase logs say `Final zero normals: 0/...`, but the serialized normal vectors at the affected locations have norm `1.11e-16 m`. Under the declared `1e-12 m` threshold, runtime counts are 63 (canonical-2) and 240 (fine-3). The `Bound.vtk` and runtime normal/size arrays are exact matches in these artifacts, so this is not a newly introduced runtime mutation.

## 构造面重合关系

For each case, `hdp_Actual.vtk` is read as the construction surface. Its six `Mk=18` quadrilateral cells are matched to the physical box faces, and all reconstructed body `x_gamma` points are tested against those face rectangles using a `1e-5 m` plane tolerance.

| resolution | hdp points | hdp body faces | runtime body interface points | on any hdp face | not on hdp face |
|---|---:|---:|---:|---:|---:|
| `canonical-2` | 16 | 6 | 504 | 504 | 0 |
| `fine-3` | 16 | 6 | 4096 | 4096 | 0 |

### hdp body-face map

| resolution | face | hdp cell | hdp residual (m) | runtime residual (m) | runtime interface points | runtime zero |
|---|---|---:|---:|---:|---:|---:|
| `canonical-2` | `x_min` | 10 | 0 | 2.421e-08 | 179 | 63 |
| `canonical-2` | `x_max` | 9 | 1.192e-08 | 3.427e-08 | 113 | 0 |
| `canonical-2` | `y_min` | 7 | 1.192e-08 | 1.192e-08 | 139 | 7 |
| `canonical-2` | `y_max` | 8 | 0 | 1.49e-08 | 140 | 7 |
| `canonical-2` | `z_min` | 5 | 2.98e-09 | 1.043e-08 | 113 | 0 |
| `canonical-2` | `z_max` | 6 | 5.96e-09 | 8.941e-09 | 113 | 0 |
| `fine-3` | `x_min` | 10 | 0 | 2.421e-08 | 1000 | 240 |
| `fine-3` | `x_max` | 9 | 1.192e-08 | 3.427e-08 | 742 | 0 |
| `fine-3` | `y_min` | 7 | 1.192e-08 | 2.31e-08 | 679 | 0 |
| `fine-3` | `y_max` | 8 | 0 | 1.49e-08 | 936 | 15 |
| `fine-3` | `z_min` | 5 | 2.98e-09 | 1.043e-08 | 742 | 0 |
| `fine-3` | `z_max` | 6 | 5.96e-09 | 1.714e-08 | 998 | 0 |

## 分辨率对照

- `dp(fine)/dp(canonical) = 0.5`.
- Boundary point count ratio fine/canonical: `3.90757`; body point count ratio: `8.12698`.
- Thresholded zero count: canonical `63`, fine `240`; fine/canonical `3.80952`.
- Thresholded zero fraction: canonical `0.279813%`, fine `0.272792%`; change `-0.007021` percentage points.
- Zero-free at both resolutions: `False`.

Refinement increases the absolute thresholded zero-normal count in the existing artifacts while the fraction changes only slightly; neither resolution is zero-free under the stated threshold.

## 未能审计/不可得字段

- No new CPU solver execution or CPU-kernel trace was produced; the existing solver logs are provenance only and identify GPU execution.
- CfgInit_Normals*.vtk are initialization snapshots, not a per-time-step normal history.
- The ghost VTK POINTS are the same x_b boundary coordinates; independent ghost coordinates are not serialized and are inferred as x_b+n_ghost.
- The serialized Bound.vtk Normal field is compared, but no raw in-memory BoundNor pointer/state or CPU reduction trace is available.
- No new CFD/GPU force, pressure, penetration, or physical-acceptance claim is made by this static audit.

## 输入清单

The JSON report records relative paths, byte sizes, and SHA-256 hashes for every input and optional summary file. Re-running the script against unchanged artifacts produces the same JSON/Markdown content.

Machine-readable report: `r4-mdbc-runtime-zero-normal-audit.json`.
