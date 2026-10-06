# F5 fresh177: actual bed review and disabled full801 render handoff

This package is source-only and disabled. It contains no BI4/H5/CSV/DAT/VTK payload.
Root owns registration, reservation, launch, and visual acceptance.

## Actual review

- `M086_T095`: Root1016 receipt is `completed`, returncode 0, and its JSON report contains all 801 frame records for 31,658 Type-3 fluid UIDs on particle axis 194,427. The controller's `actual_full801_bed_worker_output0=false` flag is retained as metadata; it is not treated as a physics result. Identity is read from `bound_actual_inputs`, not from flattened observer fields.
- `M090_T085`: Root1055 receipt is `completed`, returncode 0, with the same 801/194,427/31,658 contract. Its report is complete metadata, while the dynamic acceptance string remains “not granted”.
- Both reports keep one-DP and two-DP counts, UID loss/unexpected UID, nonfinite, and outside-footprint counts as separate quantities. The all-frame maxima are zero for the two penetration bins, UID omission, nonfinite state, and outside x/y rows. This is diagnostic evidence only and does not grant dynamic physics acceptance or visual credit.
- `M090_T095` is explicitly not submitted in Root1055 (`not_submitted=1`) and has no bed receipt/report; this package does not create a renderer request for it.

Canonical owner, source definition/plan, and producer H5 legacy scope are carried as separate roles. Native bed marker 50 and source `mkbound=40` are retained. The historical A/B penetration failures and the exact-DP precision negative remain active evidence.

## Disabled renderer handoff

The two requests use the already validated original116 -> original944 -> original023 N3 path. They preserve all 801 states and the 194,427 particle axis, request 35 contact sheets and 9 keyframes (`0,100,200,300,400,500,600,700,800`), and leave all future render hashes null. They are disabled with CPU24/env2, shared render cap 2, Home hard cap 2 GiB, Home floor 500 GiB, NVMe stage cap 24 GiB, and NVMe floor 100 GiB. Root must recheck the actual producer hashes and visual gate before enabling.

Run the metadata-only validator from the F5 worktree:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_177_f5_actual1016_1055_original138_bed_review_original116_023_944_render_disabled_v1/scripts/validate_fresh177.py
```

The validator reads JSON/XML/Python metadata and hashes only source/metadata files. It only stats the producer H5 path and uses the typed report's producer attestation; it never opens or hashes H5/BI4/CSV/DAT/VTK.
