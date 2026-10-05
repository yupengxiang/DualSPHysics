# F3 fresh070 AY0540 Root140 native-to-NVMe source handoff

This separate source-only package binds the completed Root140 native case
`F3_STAGE1_DP006_P1000_AY0540`. Its actual native receipt is
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1000_AY0540/root-stage1-f3-first24-ay0540-full836-visual-production-140/execution-receipt.json`
with SHA256
`06c0dc29d67f36800600129e0a8b030caae5f75ba369a5d631b8fe8144b1ec04`.
The canonical Root123 condition is
`b02eacdeb834e0b65ccb7121e3cd196b6af8f95983e2f0c27060939124745259`.

The binding preserves the actual native recipe (`-mdbc_noslip:1`, `tmax=8.35`,
`tout=0.01`, 836 frames), genuine GenCase056 and QA058, actual 3D counts
179208/67500/111708, native fluid mass, and no mass rescaling. The future typed
worker must preserve `(Zone,Idp)` identity and does not receive any visual,
precision, production, or independent-case grant.

The one CPU conversion request reuses the reviewed NVMe worker with a 24 GiB
staging cap, is disabled, and explicitly sets `launch_owner: "root"`. Typed
receipt, conversion report, H5, PartVTK, and visual hashes remain null. No job,
array, shared registry, ledger, or runtime guard was changed.

Root142’s `root_home_floor_no_legacy_dataset_walk_v1` profile is bound as
future provenance: 14 checks passed, runtime core unchanged, CPU-only source
enabling, Home floor and parent CPU budget preserved. The approved cumulative
window remains 512 GPU-hours / 3840 CPU core-hours, qualification 1024,
production 720, with the existing deadline and conversion cap2. Existing live
P03/AY0270 conversion reservations and Root147 native work remain protected.
AY0590, AY0610, AY0670, and AY0710 are excluded from this handoff.

`recovery/ds02_typed_conversion_recovery_plan_v1.py` is a dry-run shared-runner
reconciliation planner. It consumes only receipt/report/liveness JSON and emits
an explicit hold/finalization-review plan. It never edits receipts, launches or
kills processes, releases leases, hashes payloads, or changes runtime state. A
qualified host-namespace probe is required: a live child preserves its lease;
a missing child with a completed report remains a runner-owned lifecycle
reconciliation, never an inferred failure or direct JSON edit.

The builder and contract test read JSON/source metadata only and never open BI4,
CSV, H5, HDF5, NPY, or NPZ payloads. Run:

```text
python3 -B tests/test_fresh070_contract.py
```
