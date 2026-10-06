# Fresh153 F3 storage residual audit

This package is a read-only F3 audit for the user-authorized cleanup pass. It proposes **no deletion** and reports **0 reclaimable bytes**.

The Root1217 inventory found 61 failed F3 attempts. Only one is at or above the 256 MiB allocated threshold: `F3_DUAL_AXIS_WEAK_006G_004G_HALF_SAVE/direct-half_save-20261002-003`. Its original conversion receipt is failed with return code `-15`, but the retained `trajectory.h5` is explicitly reported as a completed 8,001-frame/108,000-particle conversion, with all three recorded PartVTK checks passing. The later post-audit rebind and full-integrity metadata still reference the same trajectory and the three sampled CSVs. Those records are downstream evidence, so the absence of a live process, open descriptor, or current reservation is insufficient to delete the files.

This package only `stat`-checked the four large files and read JSON/XML/text metadata. It did not open, hash, copy, delete, or launch against H5/CSV/BI4/VTK/DAT payloads. Producer-reported payload SHA values are retained only as attestations from metadata and are explicitly not local hashes.

Root1233's three stale F2/infra converter candidates are outside this F3 package and were independently handled by Root1234; no cross-family files were changed here.

Run the metadata-only validator with:

```text
python3 scripts/validate_storage_residual_audit.py
```
