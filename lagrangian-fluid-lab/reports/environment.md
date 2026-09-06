# Initial environment inventory

- Upstream commit: `ef3721a861fda961f0e2f9ec4cd317b19de99086`
- Isolated repository source snapshot: DualSPHysics 5.4.351
- Official packaged solver: DualSPHysics 5.4.355 (2025-04-08)
- Official packaged GenCase: 5.4.354.01
- Official archive: `DualSPHysics_v5.4.3.zip`, 829,610,102 bytes
- Archive SHA-256: `1abe74724d36cce4e7d22808a59d25f385e67446bc7c3d780eab30fc35770fda`
- Archive integrity: `unzip -tq` passed
- Solver SHA-256: `0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29`
- GenCase SHA-256: `a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226`
- PartVTK SHA-256: `62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00`
- GPUs: 8 x NVIDIA RTX 6000 Ada Generation, 49140 MiB each
- CUDA toolkit: 13.2 (V13.2.86)
- NVIDIA driver: 595.71.05
- Host compiler: GCC/G++ 11.4.0
- RAM: 251 GiB
- Initially available storage under `/home`: about 9.2 TiB

At inventory time GPUs 0-3 were occupied by unrelated Python processes and
GPUs 4-7 were idle. Exploratory jobs must select devices explicitly and must
not assume all eight devices are continuously available.

The upstream checkout contains GenCase and a subset of post-processing tools,
but no solver executable. The user-provided official package was therefore
downloaded into `vendor/downloads/`, verified, and extracted below
`vendor/official/`; all simulations reported here use that packaged solver.

An isolated source build was also explored in `vendor/src`. CUDA 13.2 required
adapting removed device-property fields, and the compile progressed through the
solver sources, but it was stopped once the verified official executable became
available. This experimental build is not the provenance of the generated data.
