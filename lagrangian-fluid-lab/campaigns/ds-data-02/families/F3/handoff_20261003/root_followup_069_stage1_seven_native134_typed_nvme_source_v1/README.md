# F3 fresh069 seven native-to-NVMe source handoff

This source-only package binds the seven completed Root134 native full836 cases:

- `F3_STAGE1_DP006_P1000_AY0360`
- `F3_STAGE1_DP006_P1000_AY0370`
- `F3_STAGE1_DP006_P1000_AY0410`
- `F3_STAGE1_DP006_P1000_AY0430`
- `F3_STAGE1_DP006_P1000_AY0440`
- `F3_STAGE1_DP006_P1000_AY0480`
- `F3_STAGE1_DP006_P1000_AY0520`

Each owner and request records the actual Root134 receipt path and SHA, Root123
canonical physical condition, GenCase056 receipt, parent initial QA058, prepared
XML/BI4/forcing metadata, and exact native command metadata. The native receipts
are all `completed`/returncode `0`, actual 3D, 179208 total particles, 67500
fluid particles, 111708 fixed particles, and native mass normalization `none`.
The native recipe is preserved exactly as recorded: `-mdbc_noslip:1`,
`tmax=8.35`, `tout=0.01`, and 836 saved frames. No native payload is opened or
rehash-computed by this package.

The disabled CPU requests reuse the reviewed
`ds_data02_nvme_convert_v1.py` worker with `/tmp/ds02-nvme-conversion` and a
25769803776-byte (24 GiB) staging cap. They have no launch or execution
permission, no production/Q-N/precision grant, and independent-case increment
zero. Typed receipt, conversion report, trajectory H5, PartVTK, and visual
hashes are deliberately null until Root authorizes the strict worker. The
worker must preserve and validate the native `(Zone,Idp)` identity (`Zone` from
BI4 Piece and `Idp` from decoder/GenCase ranges); it must not relabel zones or
rescale native fluid mass.

The package carries the approved resource provenance: Home free floor 500 GiB,
NVMe worker floor 100 GiB, shared CPU cap 64 threads, native concurrency cap 8,
conversion concurrency cap 2, cumulative window 512 GPU-hours and 3840 CPU
core-hours, qualification 1024, production 720, and deadline
`2026-10-14T07:23:48+00:00`. Existing P01/P03 conversions and Root147 AY0590/
AY0610 native launches are protected. AY0540, AY0590, AY0610, AY0670, and
AY0710 are excluded from this handoff.

The builder and test consume JSON/XML/source metadata only. They refuse to hash
BI4, CSV, H5, HDF5, NPY, or NPZ payloads and never launch a solver, converter,
GPU job, or shared-state update. Run:

```text
python3 -B tests/test_fresh069_contract.py
```
