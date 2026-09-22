# Core material A5 diagnosis

This is a diagnosis-only evidence bundle. The fixed unknown gate remains 1%, and no science implementation, threshold, ledger, slot, or GPU state was changed.

## Inputs and lineage

The full-window run is `F3_DEV_00_a0p903125`, whose registered role is `development_extrapolation` and whose source SHA256 is `8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`. It is retained as a production-side engineering/performance sidecar. Its failure locations were not used to tune the recipe, support gate, threshold, training data, or qualification decision.

The pre-change control canaries use the three existing reference roles from the preserved F3 reference protocol. They are the registered qualification cells, while the prepared records still say `qualified=false`, `formal_release=false`, and `launch_allowed=false`; this report makes no qualification claim and starts no new solver attempt:

| role | input | SHA256 | initial reliable | first bad frame(s) by source | unknown upper bound at frame 260 |
|---|---|---|---:|---|---:|
| reference nominal | `R0081818-NOMINAL.h5` | `3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575` | 512/512 | source 0: 245, 247, 248, 250 | 4.6875% |
| reference low amplitude | `R0081818-ENDPOINT-LOW.h5` | `d69f831a4e88fc9f1762a45082a65a1c26916577506dbc8b91e09084828a160f` | 512/512 | source 0: 248, 250, 253 | 3.90625% |
| reference high amplitude | `R0081818-ENDPOINT-HIGH.h5` | `6c623e651598d082951c8023cc8168da1ec0a4f58ef99b4747deb1836eb0ca41` | 512/512 | source 0: 242, 245, 247, 248 | 4.6875% |

Each canary used 512 independent geometric seeds, two RK2 substeps, native saved frames through frame 260 (`t=2.60001472138253 s`), and the current `f3_ckdtree_visible_shepard_distance_v1` backend. All three retained mass closure. Their HDF5 and summary files are in [qualification-canary-260](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/qualification-canary-260).

## Full-window result

The complete 836-frame dev00 result is [f3dev00-512.h5](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/core-material-final.LZjV4E/f3dev00-512.h5), with its machine summary [f3dev00-512.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/core-material-final.LZjV4E/f3dev00-512.json). The output SHA256 is `5eed59adc1d22a6a652abed078f09290b7e978b08c8c7e9547100fd442c6b895`. It ran on CPU with 512 seeds and two substeps, took 168.35 s, and reached 588108 KiB RSS. The exact run binding records code SHA256 `d619ba26fc624775e1bd587e40f1dcf96d8e89ce0e38545f5d18827356e2f5ec`; current control canaries bind to `e06546883e9ab3280545547fb6f92c64f0ce56381e075203db2cae7a49d0a958` after the explicit matrix-subset correction.

The full run completed with mass closure, but the weighted unknown fraction was 3.515625% (source 0: 3.90625%, source 1: 3.125%), so the fixed 1% gate failed. Common reliable path coverage was 96.484375%. No T2 qualification claim is made.

| source group | seed count with a first failure | first failure frame(s) | approximate first-failure position |
|---|---:|---|---|
| source 0 (`x<0`) | 10 | 248×2, 251×2, 252×4, 253×2 (`2.48002–2.53002 s`) | left wall band, `x≈-0.430…-0.385 m`, `|y|≈0.01…0.079 m`, `z≈0.092…0.112 m` |
| source 1 (`x≥0`) | 8 | 339×3, 340×3, 341×2 (`3.39002–3.41001 s`) | mirrored right wall band, `x≈0.426…0.432 m`, `|y|≈0.01…0.079 m`, `z≈0.103…0.112 m` |

The first-failure audit found the same mechanism in every inspected row: the second RK2 field sample (`g1`) failed the reconstruction-error gate. Velocity values were finite, swept wall collision was false, support distances were below 0.03 m, and the cKDTree visibility search found 96 visible candidates. The selected 24 neighbours had ESS about 12–19, geometry rank 3, and anisotropy about 0.46–0.82. Reconstruction error was about 0.047–0.059 m/s against the fixed 0.04698137929009748 m/s limit. This supports a local support/reconstruction issue rather than a missing-visible-neighbour or wall-segment collision event.

The qualification canaries reproduce the same left-wall onset across nominal and both amplitude endpoints before frame 260. Their initial frame is fully reliable, which rules out the earlier frame-zero support accounting error for these runs. These are control observations; no repair variant has been enabled.

## At most two repair hypotheses

1. **H1: the reconstruction gate is rejecting a usable near-wall interpolation.** The repeated `g1=false` result with valid finite fields, 96 visible candidates, adequate ESS/rank/anisotropy, and no wall crossing is evidence for this. A future canary can evaluate a wall-aware local reconstruction diagnostic while retaining the same visible cKDTree candidate set, Shepard distance weights, and 1% unknown gate. It must compare first-failure count, mass closure, and common-path coverage before any production change.

2. **H2: visibility is valid, but the retained neighbourhood is genuinely one-sided/truncated near the wall.** The failures cluster in the same wall-adjacent height band across all three qualification roles; the search sees 96 candidates but the backend retains 24. A separately bound support-cap or boundary-completion canary can test this against the current backend control. It must preserve mass closure and improve the unknown bound; a threshold relaxation is not an acceptable fix.

Both hypotheses remain unimplemented. The qualification canaries above are the required pre-change control canary for each hypothesis. The dev00 sidecar is excluded from deciding between them.

## Runnable job spec

Run from `lagrangian-fluid-lab` with CPU-only `.venv/bin/python`; do not acquire a campaign slot, touch a ledger, or start a GPU job. For each reference, use:

```text
.venv/bin/python -m scripts.core_material \
  --source <REFERENCE_H5> \
  --output campaigns/core-v1/material/evidence/<variant>-<role>-260.h5 \
  --seeds 512 --substeps 2 --stop-after 260
```

Use the three reference paths in the table above. A candidate advances only if `initial_reliable == 512/512`, mass closure is true, and the worst-case unknown fraction is at most 1%. The full machine-readable record, hashes, resource limits, and exact output paths are in [material-diagnosis-2026-09-19.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/material-diagnosis-2026-09-19.json).

The CPU test gate passed: `.venv/bin/python -m pytest -q tests/test_core_material.py` → `7 passed in 2.86s`, including the explicit 15-row matrix subset, provider future-frame refusal, source/CDF semantics, explicit H2/H1 backend bindings, and independent-process SIGKILL checkpoint/resume equivalence.

The follow-up fixed H2 `k=48` study and conservative H1 query-error estimate are recorded in [material-h2-h1-study-2026-09-19.md](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/material-h2-h1-study-2026-09-19.md). H2 did not change the nominal unknown bound or recover first failures. H1 removed manufactured false passes but raised nominal unknown above 1%, so neither variant is a qualification repair.
