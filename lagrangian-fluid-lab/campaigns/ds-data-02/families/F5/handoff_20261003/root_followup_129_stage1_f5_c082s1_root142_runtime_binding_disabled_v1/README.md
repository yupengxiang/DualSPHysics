# F5 fresh129 Root142 runtime binding (disabled)

This package completes the shared Root142/runtime/strict input contract for the two existing Root753 typed producers:

- M085_T080: `root-stage1-f5-c082s1-M085_T080-full801-native-xmf-root142-129`
- M115_T100: `root-stage1-f5-c082s1-M115_T100-full801-native-xmf-root142-129`

Both requests are `kind=cpu`, `cpu_task_kind=audit`, `cpu_threads=2`, use the integration project interpreter at `/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python`, and remain `disabled=true`, `execution_allowed=false`, `launch=false`, `launch_allowed=false`. This source package must not be launched. Root registration is the only enablement point. The contract requires Root142 policy profile `root_home_floor_no_legacy_dataset_walk_v1`, Root ownership, strict `input_sha256` closure, live Home-floor/resource approval 064, and no conversion-cap reservation.

The XMF contract is N3 temporal XMF/XDMF, 801 frames, particle axis 194427, 3D, 0.02 s output spacing over 0..16 s. The upstream native and typed receipts/reports are checked as JSON metadata. The typed H5 digest is carried only as the Root753 producer attestation; this package does not open or hash H5/BI4/CSV/DAT/VTK payloads.
The additive ready-binding exposes the exact exporter keys `typed_receipt`, `native_receipt`, and `conversion_report`, mapped to immutable Root753/Root738 paths; it also records `root_inventory_policy_sha256` and the Root142 registration block. This fixes the existing exporter entry contract without changing fresh128 bytes.

For each endpoint the canonical fresh125 physical owner and actual converter `legacy-owner-scope.v0` remain separate. The bed path is an explicit WAIT gate: its XMF manifest/receipt and all bed/render outputs remain null until Root runs this XMF request and reviews the real output. No bed acceptance, Q-N, or case credit is granted here. Historical A/B penetration failures and the exact-DP 5e-6-versus-1e-6 numerical negative remain retained.

Validate source metadata only with:

```text
python3 scripts/validate_fresh129.py
```
