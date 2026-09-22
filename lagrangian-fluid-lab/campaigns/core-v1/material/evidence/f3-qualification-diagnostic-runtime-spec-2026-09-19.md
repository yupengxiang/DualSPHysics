# F3 qualification diagnostic runtime spec

This file registers the six read-only material analyses that root may queue from the existing F3 native reference HDF5 files. It fixes the original Shepard implementation and leaves the 1% unknown gate and reconstruction gate unchanged. The machine-readable spec is [f3-qualification-diagnostic-runtime-spec-2026-09-19.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f3-qualification-diagnostic-runtime-spec-2026-09-19.json).

The backend is `f3_ckdtree_visible_shepard_distance_v1`, with 24 visible neighbours, `1/(d²+0.004²)` weights, 0.03 m maximum support, and reconstruction limit `0.04698137929009748 m/s`. Seeds are the independent 16×8×4 F3 grid with `seed-XXXXXX` identities and continuous `x=0` source labels. The reference provider exposes native current frames and the permitted next frame only. `baseline24` is the only variant in this scope; H2/H1 and the development `dev00` lineage are excluded.

| row | source | native frames | fluid particles | HDF5 SHA256 | substeps |
|---|---|---:|---:|---|---:|
| coarse | `R0081818-NOMINAL` dp=.008181818... | 836 | 26,620 | `3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575` | 2, 4 |
| production | `F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen` dp=.0075 | 836 | 34,560 | `fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4` | 2, 4 |
| fine | `F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen` dp=.006 | 836 | 67,500 | `42f527b645017058de18cbdeb54687b728c9082bdd9513b2e4c577c3475f49f0` | 2, 4 |

The source files cover 0–8.35 s at native 0.01 s output. The coarse file is explicitly a new coarse reference and remains `qualified=false`, `formal_release=false`, and `launch_allowed=false`; reading it for comparison does not launch a CFD solve. The production and fine prepared records are both `F3_native_nopen_qualification`, with `qualified=false` and `formal_release=false`. Existing `scripts.f3_ref0081818_material_production` s2/s4 artifacts are candidate-only records with `qualified_T2_macro=false` and `qualified_T2_path=false`; they are provenance context, not substitutes for these six rows.

Each row uses the following command after root substitutes its attempt directory:

```text
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python -m scripts.core_material --source <source_h5> --output <attempt_dir>/material.h5 --seeds 512 --substeps <2-or-4> --neighbour-variant baseline24
```

The command is CPU-only and does not acquire a ledger slot or start a solver. A completed receipt must bind the exact argv, source and code hashes, output and checkpoint hashes, frame counts, wall/CPU time, peak RSS, and resource allocation. The HDF5 sidecar checkpoint is authoritative after an independent process kill; `--resume` must continue the same attempt and trim any speculative HDF5 tail to the last committed checkpoint.

Root should retain the six per-source summaries and check the initial support mask, per-source unknown mass, reconstruction gate, mass closure, first-passage and return CDFs, residence, and common reliable path coverage. A row with unknown mass above 1% fails. Any failed production or fine row leaves the F3 material scope T2-unqualified; no neighbour sweep, threshold change, or third repair follows.

No CPU attempt was started while preparing this spec. The only local verification was read-only HDF5 structure inspection and source SHA256 recomputation. The bound implementation hashes are recorded in the JSON, including current `core_material.py` SHA256 `1880c02a50168ae3325c39993a55103a1ebba06adcc48a486b7f6f4825d94b7e`.
