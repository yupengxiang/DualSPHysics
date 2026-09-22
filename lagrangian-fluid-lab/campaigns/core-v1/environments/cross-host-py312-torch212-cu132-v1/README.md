# Matched cross-host canary environment

This directory defines the isolated follow-up stack for the F3 20-step
cross-host diagnostic. The existing `lagrangian-fluid-lab/.venv` and the
source conda environment are read-only inputs. Host prefixes are created below
`runtime/` by copying the known Python 3.12.13 / Torch 2.12.1+cu132 source
environment, then pinning NumPy and SciPy to the versions used by the Core
bundle metadata.

Run `scripts/core_cross_host_environment_probe.py` with
`CUDA_VISIBLE_DEVICES=` before any GPU launch. The probe records actual imports,
package versions, file hashes, and the command used to create the prefix. The
root scheduler supplies the host GPU UUID and submits the unchanged 20-step
canary only after both host records match.

The target versions are Python 3.12.13, Torch 2.12.1+cu132, CUDA 13.2, NumPy
2.2.6, SciPy 1.15.3, and h5py 3.16.0. Exact wheel or conda package hashes
must be captured in each host record; version strings alone are insufficient
for the comparison.

The prepared interpreters are:

```
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1/runtime/ada/bin/python
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/environments/cross-host-py312-torch212-cu132-v1/runtime/h200/bin/python
```

`records/ada-import.json` is an Ada-host import record. The original
`records/h200-import.json` is retained as local package-parity evidence only;
it is not H200 hardware evidence. The prefix is now also deployed at
`h200-deepdebris`, and `records/h200-import-remote.json` contains the actual
H200 hostname, CPU, driver, and GPU inventory. Use the remote job spec below
for the H200 canary.

The exact preparation and validation receipt is
`environment-record-v1.json`; the two runtime-ready 20-step drafts are under
`specs/`. The preparation copied the read-only source conda environment and
installed only the pinned NumPy/SciPy wheels, leaving the existing lab `.venv`
untouched.

The remote deployment receipt is
`h200-remote-deployment-record-v1.json`; its dedicated job spec is
`specs/h200-f3-cross-host-canary20-matched-stack-remote-v1.json`.

The two pip freezes and conda explicit locks are byte-identical. NumPy's
installed `RECORD` differs only for its generated `f2py` and `numpy-config`
entrypoints, whose shebangs contain the host-specific prefix; imported package
files and metadata hashes match.
