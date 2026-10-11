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
absolute path attributes, emits geometry/control/label sidecars, writes an L2
reader manifest, and creates a no-model evaluator. `portable_bundle.py
validate` can then be run after copying the bundle to a new NAS directory. It
hash-checks every artifact, rejects absolute paths and the old source/CURRENT
markers in JSON and HDF5 attributes, checks all required native fields and the
complete validity mask, and reads first/middle/final frames through
`l2_reader`. The evaluator performs a zero self-comparison plus identity
permutation and field-perturbation negatives.

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
and symlinks, enforces the 4 GiB archive/10 GiB extraction limits, atomically
publishes the extraction, and writes a path-light JSON inspection report. The
ready request is
`requests/lagrangebench-v2-2d-ldc-download-inspect-001.json`; the parent runner
must substitute `{worktree}` and `{attempt_root}` after NAS preflight.

Dependencies for both paths are Python 3.10+, NumPy, and h5py. JAX, PyTorch,
and the LagrangeBench package are intentionally not required.
