# F3 fresh066 corner706 native-to-NVMe source handoff

This sibling handoff covers the four distinct pitch/AY corner cases from the
Root706 native run:

| case | pitch | AY | native evidence |
| --- | ---: | ---: | --- |
| `F3_STAGE1_DP006_P0800_AY0250` | 0.8 | 0.25 | Root706/Root719 completed/0, 836 frames |
| `F3_STAGE1_DP006_P0800_AY0750` | 0.8 | 0.75 | Root706/Root719 completed/0, 836 frames |
| `F3_STAGE1_DP006_P1200_AY0250` | 1.2 | 0.25 | Root706/Root719 completed/0, 836 frames |
| `F3_STAGE1_DP006_P1200_AY0750` | 1.2 | 0.75 | Root706/Root719 completed/0, 836 frames |

The historical `root_followup_066_stage1_first24_typed_nvme_source_v1` package
is a different five-case handoff and remains byte unchanged. This package uses
the collision-safe assignment id `fresh066-corner706`.

Each request is disabled and binds the actual Root704 prepared input, Root706
native request/receipt, Root707 controller result, and Root719 terminal review.
The producer evidence reports genuine 3-D `179208 = 111708 fixed + 67500
fluid` particles, `moving=0`, `tmax=8.35`, `tout=0.01`, and `836` saved frames.
The physical binding is passed through the official converter's pure
`_physical_condition_scope`/`canonical_hash` metadata functions; all four
computed hashes equal the Root706 producer hashes. Source condition templates
remain separate from the actual physical-binding scope, and no visual, Q-N,
precision, or production approval is granted.

The command uses the approved NVMe wrapper contract:

```text
.venv/bin/python ds_data02_nvme_convert_v1.py \
  --staging-root /tmp/ds02-nvme-conversion \
  --staging-limit-bytes 25769803776 -- \
  --data-root .../solver_output/data --generated-xml ... \
  --output {attempt_root}/trajectory.h5 --report {attempt_root}/conversion-report.json \
  ... --owner-metadata <package owner>
```

There is no `ds_data02_direct_convert.py` executable after `--`. The requests
carry the mandatory runtime/policy fields: `worktree_root`, integration `cwd`,
`launch_owner=root`, `kind=cpu`, `cpu_task_kind=conversion`, CPU2,
`max_wall_seconds=10800`, `estimated_storage_bytes=25769803776`, Root142
inventory profile, NVMe cap2, 24 GiB staging, and 100 GiB free-space floor.
The F6 conversion queue/tool1704 remains a scheduling prerequisite owned by
Root; this package does not launch or reserve anything.

XML/BI4/forcing and native log digests are copied only from Root706/Root719
producer attestations. The builder and validator refuse to open or hash BI4,
CSV, H5, VTK, DAT, or numerical arrays. Future typed receipt, conversion
report, H5, PartVTK, XMF, render, and visual-decision hashes are null.

Run the source-only checks with the approved integration virtualenv:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  build_fresh066_corner_typed_requests.py
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  validate_fresh066_corner_contract.py
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  tests/test_fresh066_corner_contract.py
```
