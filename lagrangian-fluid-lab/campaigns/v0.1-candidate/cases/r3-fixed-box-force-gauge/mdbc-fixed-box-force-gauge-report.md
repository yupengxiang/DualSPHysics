# mDBC fixed immersed box force gauge

> Bounded candidate evidence only. `overall_acceptance_status` is deliberately `candidate_not_accepted`; the analytical 78.48 N value is a preregistered pressure reference, not an acceptance threshold by itself.

## Scope and semantics

- Exactly two bounded mDBC calibrations: `canonical-2` (`dp=0.025 m`) and `fine-3` (`dp=0.0125 m`). No radius scan or extra calibration was run.
- Physical cube: `0.2 x 0.2 x 0.2 m`, void `[0.5, 0.3, 0.2]--[0.7, 0.5, 0.4] m`; floor gap `0.2 m`, water top `0.6 m`.
- Both definitions use source `mkbound=1`, no `<floating>` section, and `Boundary=2` mDBC. The fixed shell is drawn after the void; its normal-only surface has one `+0.5 dp` layer and the shell uses `0,-1,-2` layers.
- The solver files are audited as `x_gamma=x_boundary+n_ghost/2`; ghost vectors/sizes must be exactly twice the normal arrays, and the reconstructed body interface must lie on the physical cube faces with outward normals.
- Gauge output is signed pressure interaction on selected fixed boundary particles only (`forcex`, `forcey`, `forcez`); it excludes gravity, support reaction, and viscosity.
- Analytical preregistered reference: `Fz=rho*g*V=78.48 N` in `+z`; it is never converted to physical acceptance automatically.

## Source and runtime evidence

- Gauge format: `doc/xml_format/_FmtXML_Gauges.xml` (`force/target mkbound`).
- Source mapping: `src/source/JDsGaugeSystem.cpp:472-493` (`AddGaugeForce` resolves `mkbound` through `JSphMk`).
- Force semantics: `src/source/JDsGaugeItem.cpp:1710-1988` and CUDA implementation `src/source/JDsGauge_ker.cu:497-603`.
- Owner authorization covers GPU indices `[0, 1, 2, 3, 4, 5, 6, 7]`. Live preflight prefers idle `[4, 5, 6, 7]`; busy jobs were not interrupted.

## Final calibration runs

| run | execution | GPU / UUID | attempt | zero normals | normal/ghost | fixed body | force windows | late Fz (N) | status |
|---|---|---|---|---:|---|---|---|---:|---|
| `canonical-2` | `completed` | `4 / GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9` | `20260907T123424.875319Z-4dfa3f2f.complete` | `63/22515` | `False` | `True` | `False` | `93.397` | `candidate_not_accepted` |
| `fine-3` | `completed` | `4 / GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9` | `mdbc-probe-fine-root` | `240/87979` | `False` | `True` | `False` | `80.789` | `candidate_not_accepted` |

### `canonical-2`

- Definition: `fixed_box_mdbc_canonical_Def.xml`; SHA-256 `7fbf0b443d17c9cd3e50636859fea525bda2f88cc9397484e768bbf16c6f068f`.
- GenCase log: `generated/fixed_box_mdbc_canonical/gencase.stdout.log`; generated final zero-normal audit: `{'count': 0, 'total': 22515, 'percentage': 0.0}`.
- Source `mkbound=1` -> generated fixed `Mk=18`, `504` particles. Generated XML: `results/fixed_box_mdbc_canonical/canonical-2-ingested/generated_particles.xml`.
- GPU preflight: `runs/gpu-preflight-mdbc-canonical-final.txt`; selected `4` / `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9`; busy authorized indices left untouched: `[0, 1, 2, 3]`.
- Normal/ghost arrays: `runs/mdbc-probe-canonical-final/attempts/20260907T123424.875319Z-4dfa3f2f.complete/CfgInit_Normals.vtk`, `runs/mdbc-probe-canonical-final/attempts/20260907T123424.875319Z-4dfa3f2f.complete/CfgInit_NormalsGhost.vtk`; counts `22515/22515`, zero total `63/63` (body `63/63`), max doubling errors `0.000e+00` and `0.000e+00`.
- Reconstructed body interface bbox `[[0.49999997578561306, 0.30000000074505806, 0.1999999973922968], [0.6999999992549419, 0.5000000149011612, 0.4000000059604645]]`, max face residual `3.427e-08 m`, min outward-normal dot `0.000`; gate `False`.
- Fixed-body field audit matches by `(Zone,Idp)` after filtering generated `Mk=18`: count `504/504`, max motion `0.000e+00 m`; fluid penetration `0/27`.
- Signed trace: `results/fixed_box_mdbc_canonical/canonical-2-ingested/force_timeseries.csv` (`forcex/forcey/forcez`, 160 samples). `Fz` means last 0.20/0.40/0.60 s: `[93.39743175000001, 92.65696899999999, 94.666453]`, standard-deviation limit `3.924 N`, stable gate `False`.
- Solver log/config gate: `True`; excluded particles `0`. Overall candidate acceptance remains `candidate_not_accepted`.

### `fine-3`

- Definition: `fixed_box_mdbc_fine_Def.xml`; SHA-256 `9ecbb65513361899a9d03fa1927f5eff99719fdefbf11259b050379e62ea69ba`.
- GenCase log: `generated/fixed_box_mdbc_fine/gencase.stdout.log`; generated final zero-normal audit: `{'count': 0, 'total': 87979, 'percentage': 0.0}`.
- Source `mkbound=1` -> generated fixed `Mk=18`, `4096` particles. Generated XML: `results/fixed_box_mdbc_fine/fine-3-ingested/generated_particles.xml`.
- GPU preflight: `runs/mdbc-probe-fine-root/gpu-preflight.txt`; selected `4` / `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9`; busy authorized indices left untouched: `[0, 1, 2, 3]`.
- Normal/ghost arrays: `runs/mdbc-probe-fine-root/CfgInit_Normals.vtk`, `runs/mdbc-probe-fine-root/CfgInit_NormalsGhost.vtk`; counts `87979/87979`, zero total `240/240` (body `240/240`), max doubling errors `0.000e+00` and `0.000e+00`.
- Reconstructed body interface bbox `[[0.49999997578561306, 0.29999999701976776, 0.19999999180436134], [0.7000000104308128, 0.5000000149011612, 0.4000000171363354]]`, max face residual `3.427e-08 m`, min outward-normal dot `0.000`; gate `False`.
- Fixed-body field audit matches by `(Zone,Idp)` after filtering generated `Mk=18`: count `4096/4096`, max motion `0.000e+00 m`; fluid penetration `0/197`.
- Signed trace: `results/fixed_box_mdbc_fine/fine-3-ingested/force_timeseries.csv` (`forcex/forcey/forcez`, 320 samples). `Fz` means last 0.20/0.40/0.60 s: `[80.78922624999998, 84.895485, 84.15577844166674]`, standard-deviation limit `3.924 N`, stable gate `False`.
- Solver log/config gate: `False`; excluded particles `20`. Overall candidate acceptance remains `candidate_not_accepted`.

## Historical probe provenance

The old `mdbc-probe-canonical-2` trace is retained as superseded canonical evidence. The old `mdbc-probe-canonical-3` and `mdbc-probe-canonical-4` directories were checked: both are `dp=0.025 m` canonical runs, not fine evidence. They are listed only to prevent a filename-based fine-run claim; the final `fine-3` row above has its own generated prefix and attempt directory.

## Acceptance decision

All execution results, traces, normal/ghost files, generated mappings, and failed/blocked outcomes are evidence. A force window that is unstable or a failed structural gate remains a diagnostic failure. No mDBC result in this report is physically accepted.
