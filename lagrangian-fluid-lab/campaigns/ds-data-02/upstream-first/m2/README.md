# M2 data-product preparation

This directory contains the small data-product path for the upstream-first
campaign. It does not run DualSPHysics, invoke PartVTK, train a model, or
download the external archive by itself.

## 3-D canonical candidate

Use the completed F1 direct BI4 conversion as the first self-owned 3-D source:

* HDF5: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/F1_REF_ECC_NOMINAL_FINE/ds02-infra-f1-direct-bi4-fine-v3/trajectory.h5`
  (453,427,289 bytes; declared output SHA-256 `533732407605a9c42a7c8fd35f91e988990d42d70b70053ceb0e32ade97bdcf2`)
* Conversion evidence:
  `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/F1_REF_ECC_NOMINAL_FINE/ds02-infra-f1-direct-bi4-fine-v3/direct-conversion-report.json`
  (SHA-256 `ece4c7e7d38d2c4180f80b8175879e2d13c2eb098e008156f04bc62dca3ea379`)
* Owner metadata build input:
  `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/definitions/F1_REF_ECC_NOMINAL_FINE.metadata.json`
  (8,111 bytes; SHA-256 `9a4ed37a8bab7848d3df3a5f743b96e6bb9e43ba1caa431c678c8df163812c7e`)
* Generated XML build input:
  `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_REF_ECC_NOMINAL_FINE/gencase-reference-002/F1_REF_ECC_NOMINAL_FINE.xml`
  (5,477 bytes; SHA-256 `20da0a14fd2307ba5c90eef3763efd2ec744bee3f3c6c111ab0a188be3c6c054`)
* Existing converter: `lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py`
  using the checked-in `bi4_dump` decoder one frame at a time.
* Existing read-only utility reused by the portable bundle: `lagrangian-fluid-lab/scripts/l2_reader.py`.

The report records 161 strictly increasing frames, 110,468 particles, solver
dimension 3 (`data2d=false` plus the Run.out 3-D banner), a fixed `(Zone,Idp)`
identity axis, and zero initial exclusions. PartVTK checks on first, middle,
and final frames passed for identity/type/mk and the stated numeric tolerances.
The report explicitly remains conversion evidence (`q_i_status` not granted,
Q-N and production not assessed). F6 was rejected as the primary candidate
because its direct output has frame-level fluid omissions.

`portable_bundle.py build` copies this existing HDF5 through h5py, redacts
absolute path attributes, reads and hash-checks the owner metadata and
generated XML named by `source_provenance`, and emits actual geometry/control
evidence. The HDF5 `labels.h5` sidecar carries native `(Zone,Idp)` IDs, source
and final positions, displacement, source/final type and mk, validity, and
destination regions. `portable_bundle.py validate` can then be run after
copying the bundle to a new NAS directory. It hash-checks every artifact,
rejects absolute paths and the old source/CURRENT markers in JSON and HDF5
attributes, checks all required native fields and the complete validity mask,
recomputes every transport label from the relocated trajectory, and reads
first/middle/final frames through `l2_reader`. The evaluator reports actual
transport summaries and compares them with recomputed labels; its negatives
permute destination identity and perturb a published position field.

The build also copies `portable_bundle.py` and the existing `l2_reader.py`
into `runtime/` and binds both files through the package manifest. This makes
the package replayable with the runtime Python environment after the original
worktree is gone. `portable_relocate_worker.py` copies the completed package
into a fresh attempt using bounded regular-file I/O, rejects symlinks, and
then invokes `portable_isolated_validate.py`. That wrapper runs bubblewrap
with only the relocated bundle and Python runtime mounted read-only; it masks
the old source roots and probes the denied paths inside the namespace. A
different working directory or a hash check alone is not accepted as the
relocation proof.

The portable bundle intentionally does not publish `data_root`, decoder,
generated XML, PartVTK, or worktree paths. Their hashes remain represented by
the source report hash and the geometry/control evidence sidecars; the raw
source report itself stays outside the bundle.

## External LagrangeBench v2 source

The pinned archive is Zenodo record [10491868](https://zenodo.org/records/10491868),
file `2D_LDC_2708_10kevery100.zip`:

* Download URL:
  `https://zenodo.org/records/10491868/files/2D_LDC_2708_10kevery100.zip?download=1`
* API content URL:
  `https://zenodo.org/api/records/10491868/files/2D_LDC_2708_10kevery100.zip/content`
* Exact size: `358811551` bytes
* Exact checksum: `md5:f527ab73f69afc0d176a229f4b812cd5`
* Members: `metadata.json`, `train.h5`, `valid.h5`, `test.h5` below
  `2D_LDC_2708_10kevery100/`.

`lagrangebench_v2_loader.py` is a bounded, training-framework-free reader. It
preserves the raw `train`/`valid`/`test` split names and exposes only the raw
`position` and `particle_type` fields. Time, particle IDs, velocity, density,
mass, pressure, validity, geometry, controls, and labels are explicitly marked
unavailable; no velocity or time array is invented from metadata. Inspection
scans positions in small frame slices, and `read_window` has a byte bound.

`lagrangebench_v2_worker.py` is opt-in and safe to schedule on NAS. It streams
the download to a partial file, verifies size and MD5, rejects unsafe zip paths
and symlinks, atomically publishes the extraction, and writes a path-light JSON
inspection report. The ready request reserves a 6 GiB NAS envelope with a 400
MiB archive bound and 5 GiB extraction bound; it is
`requests/lagrangebench-v2-2d-ldc-download-inspect-001.json`; the parent runner
must substitute `{worktree}` and `{attempt_root}` after NAS preflight.

Dependencies for both paths are Python 3.10+, NumPy, and h5py. JAX, PyTorch,
and the LagrangeBench package are intentionally not required.
