# H2 support-cap and H1 error-estimate study

This study follows the dev00 diagnosis without using dev00 to choose a parameter. The only H2 support-cap value registered was `k=48`; no support-cap sweep was performed. The fixed reconstruction gate and the fixed 1% unknown gate stayed in force. All runs were CPU-only and wrote no campaign ledger or slot state.

## H2: fixed `k=48`

The independent backend name is `f3_ckdtree_visible_shepard_distance_k48_v1`. It keeps the F3 cKDTree visible-neighbour search and `1/(d²+eps²)` Shepard weights, changing only the retained support cap from 24 to 48.

The qualification nominal canary used:

```text
.venv/bin/python -m scripts.core_material \
  --source campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5 \
  --output /tmp/core-material-h2-nominal-260.h5 \
  --seeds 512 --substeps 2 --stop-after 260 \
  --neighbour-variant h2_k48
```

The input SHA256 is `3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575`; the exact run code binding is `d9b8efd1d4d6eb10ceac768605f5c6ef474362224356d01d37c01b32ebd6255e`. The run committed frame 260, closed mass, and used 709644 KiB maximum RSS under `/usr/bin/time -v` (100.20 user seconds, 1.33 system seconds, 85.44 wall seconds). The HDF5 output is [core-material-h2-nominal-260.h5](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/h2-k48-study-2026-09-19/core-material-h2-nominal-260.h5).

H2 produced 12 first-failed seeds, all source 0: frames 245×2, 247×2, 248×2, 249×2, and 250×4. The source 0 unknown upper bound was 4.6875%, source 1 was 0%, and common reliable path coverage was 97.65625%. Baseline `k=24` on the same nominal 260-frame control had the same unknown bound and common coverage, with 12 first-failed source 0 seeds. H2 increased inspected support to 192 visible and 48 selected neighbours and raised ESS, but did not recover any first-failed seed. H2 is therefore rejected as a repair.

## Manufactured near-wall validation

The CPU manufactured run uses a fixed 6555-point 7.5 mm near-wall cloud and 60 off-grid queries in the closed-wall-adjacent slab. The field is a known quadratic velocity field with wall-normal and cross terms. Its input hashes, exact field definition, code hash, script hash, and resource receipt are in [core-material-h2-manufactured.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/h1-affine-bound-study-2026-09-19/core-material-h2-manufactured.json).

| variant | actual query errors above fixed gate | diagnostic gate failures | actual bad but diagnostic passed | actual good but diagnostic failed |
|---|---:|---:|---:|---:|
| baseline24 residual | 40.0% | 0.0% | 40.0% | 0.0% |
| H2 `k=48` residual | 41.667% | 33.333% | 35.0% | 26.667% |
| H1 affine bound | 40.0% | 80.0% | 0.0% | 40.0% |

The current residual is therefore not a trustworthy query-error estimate by itself. H2 does not repair that mismatch. H1 uses a separate backend version, `f3_ckdtree_visible_shepard_query_error_bound_v1`, and estimates `residual + local_affine_query_bias`. The manufactured test removes false passes at this fixed gate, with an expected conservative false-rejection cost.

## H1 nominal canary

H1 uses `k=24` and retains the original reconstruction residual gate while adding the local affine query-bias term. It ran with current code SHA256 `8d45ee7b1be55b8e01f8b4b978091f527fdb824ab53bec36656ae6bf4977ce68`:

```text
.venv/bin/python -m scripts.core_material \
  --source campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5 \
  --output /tmp/core-material-h1-nominal-260.h5 \
  --seeds 512 --substeps 2 --stop-after 260 \
  --neighbour-variant h1_affine_bound
```

The run committed frame 260 and closed mass. It used 716612 KiB maximum RSS under `/usr/bin/time -v` (69.04 user seconds, 0.73 system seconds, 53.69 wall seconds). The HDF5 output is [core-material-h1-nominal-260.h5](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/h1-affine-bound-study-2026-09-19/core-material-h1-nominal-260.h5).

H1 produced 19 first-failed seeds: 17 source 0 and 2 source 1. The source 0 unknown upper bound was 6.640625%, source 1 was 0.78125%, and common reliable path coverage was 96.2890625%. The fixed 1% gate therefore fails. H1 is a conservative diagnostic repair that removes the manufactured false passes, but it is not a viable qualification repair at the current sampling and gate policy.

The machine-readable execution receipts and direct enqueue arguments are in [material-h2-h1-study-2026-09-19.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/material-h2-h1-study-2026-09-19.json). No production dev00 result was used to select or tune either variant.

The CPU test gate is now `7 passed` in `tests/test_core_material.py`, including explicit H2/H1 backend bindings and the independent-process SIGKILL checkpoint/resume test.
