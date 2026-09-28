# F3 coarse material fresh root/scheduler receipt intake

- Schema：`core.material.f3.coarse.root_scheduler_intake.v1`
- 状态：`blocked_missing_fresh_root_scheduler_receipts`
- 候选：`CORE-F3-MATERIAL-COARSE-s2`

## 绑定与决策

- proposal contract：`True`
- host-I/O admission contract：`True`
- current hash binding：`True`
- normalized argv/cwd：`True`
- fresh root receipt：present=`False`, valid=`False`
- scheduler host-I/O reservation：present=`False`, valid=`False`
- pair/namespace cross-binding：`False` / `False`

无论 receipt 是否完整，本 intake 都不铸造 launch capability：
`diagnostic_only=True`、`formal=False`、
`T2_macro=False`、`T2_path=False`、
`qualification=False`、`credit=0`。

## 输入边界

- `proposal`：`reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json`，exists=`True`，bytes=`13291`，sha256=`4e56372583d5f46226149bec3e0b2f91f33da8ddea6ca51504db461eff7d534f`
- `host_io_admission`：`reports/F3-MATERIAL-COARSE-HOST-IO-ADMISSION-2026-09-28.json`，exists=`True`，bytes=`14831`，sha256=`449977cd2cc964eefca3a1692887069b443f4f746b3e1a8c054132675d2de057`
- `fresh_root_receipt`：`campaigns/core-v1/material/evidence/f3-material-coarse-root-scheduler-intake-v1/fresh-root-receipt.json`，exists=`False`，bytes=`None`，sha256=`None`
- `scheduler_host_io_reservation`：`campaigns/core-v1/material/evidence/f3-material-coarse-root-scheduler-intake-v1/scheduler-host-io-reservation.json`，exists=`False`，bytes=`None`，sha256=`None`
- `current_core_material`：`scripts/core_material.py`，exists=`True`，bytes=`116805`，sha256=`9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e`
- `source_h5`：`campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5`，exists=`True`，bytes=`692839604`，sha256=`3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575`
- `current_job_spec`：`campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json`，exists=`True`，bytes=`1616`，sha256=`1f1080e497feab414863e3e02dd31dbec91c0d09e4ef9ac855e0cdbbda070628`
- `current_core_runtime`：`scripts/core_runtime.py`，exists=`True`，bytes=`63098`，sha256=`de2f1c353647e8baa0aa427873b8c0689f22d53b3f8ce63aeefe0fd9ea9f2dc0`
- `current_runtime_spec`：`campaigns/core-v1/material/evidence/f3-qualification-diagnostic-runtime-spec-2026-09-19.json`，exists=`True`，bytes=`12533`，sha256=`06c2d549d971d679f48b0d46480a7decc64d1ab58a3e35ece8cb5a61a04a1aa9`

source HDF5 只继承已有 proposal/host-admission 的 hash claim；本 intake 只做 lstat 元数据，
`opened_as_hdf5=false`、`read=false`、`hash_recomputed=false`。

## 阻塞原因

- `root_receipt:future fresh root admission receipt is missing: campaigns/core-v1/material/evidence/f3-material-coarse-root-scheduler-intake-v1/fresh-root-receipt.json`
- `scheduler_receipt:future scheduler-owned host-I/O reservation is missing: campaigns/core-v1/material/evidence/f3-material-coarse-root-scheduler-intake-v1/scheduler-host-io-reservation.json`
- `root_receipt:root_receipt.missing_or_not_object`
- `scheduler_receipt:scheduler_receipt.missing_or_not_object`
- `root_scheduler_pair_cross_binding_invalid`
- `fresh_attempt_namespace_missing_or_cross_receipt_drift`
- `scheduler_owned_host_io_reservation_missing_or_mismatched`

未启动、停止或重启 worker/solver/GPU/queue；未写 registry、ledger、denominator、gate 或 PLAN。
