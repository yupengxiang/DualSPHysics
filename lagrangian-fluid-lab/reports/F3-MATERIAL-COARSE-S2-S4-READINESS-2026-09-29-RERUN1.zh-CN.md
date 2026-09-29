# F3 material coarse s2/s4 readiness

- Schema：`core.material.f3.coarse.s2_s4.readiness.v1`
- 状态：`blocked_fail_closed`
- 首选顺序：`CORE-F3-MATERIAL-COARSE-s2`

## 当前绑定

- s2 spec：`campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json`，sha256=`1f1080e497feab414863e3e02dd31dbec91c0d09e4ef9ac855e0cdbbda070628`，substeps=`2`
- s4 spec：`campaigns/core-v1/material/jobs/core-f3-material-coarse-s4.json`，sha256=`89a376b36c3d8c31c8b050b6bbd5a3aa6014d1877c7d7d918ed7cb4eeb889c1b`，substeps=`4`
- shared source SHA：`3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575`；source content opened/read/rehash=`False/False/False`
- argv/cwd binding：`True`
- scheduler-owned core_runtime entry：`True`

## 未满足的外部条件

- fresh one-shot namespace：present=`False`，verified=`False`
- scheduler host-I/O reservation：present=`False`，verified=`False`

本 sidecar 只做 bounded metadata/preflight；不铸造 launch capability，不增加 T1/T2 或 formal credit。
未启动、停止或重启 worker/solver/GPU/queue；未写 registry、ledger、denominator、gate、completion 或 PLAN。

## 阻塞原因

- `base_intake:root_receipt:future fresh root admission receipt is missing: campaigns/core-v1/material/evidence/f3-material-coarse-root-scheduler-intake-v1/fresh-root-receipt.json`
- `base_intake:scheduler_receipt:future scheduler-owned host-I/O reservation is missing: campaigns/core-v1/material/evidence/f3-material-coarse-root-scheduler-intake-v1/scheduler-host-io-reservation.json`
- `base_intake:root_receipt:root_receipt.missing_or_not_object`
- `base_intake:scheduler_receipt:scheduler_receipt.missing_or_not_object`
- `base_intake:root_scheduler_pair_cross_binding_invalid`
- `base_intake:fresh_attempt_namespace_missing_or_cross_receipt_drift`
- `base_intake:scheduler_owned_host_io_reservation_missing_or_mismatched`
- `fresh_one_shot_namespace_missing_or_unverified`
- `scheduler_owned_host_io_reservation_missing_or_unverified`
- `base_root_scheduler_intake_not_bound`
