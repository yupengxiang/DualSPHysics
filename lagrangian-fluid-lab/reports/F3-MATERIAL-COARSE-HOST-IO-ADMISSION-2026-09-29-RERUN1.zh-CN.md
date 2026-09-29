# F3 coarse material host-I/O diagnostic admission

- Schema: `core.material.f3.coarse.host_io_admission.v1`
- 状态：`diagnostic_admission_blocked`
- 候选：`CORE-F3-MATERIAL-COARSE-s2`

## 决策

- `probe_pass`: `True`
- `measurement_complete`: `True`
- `proposal_contract_valid`: `True`
- `fresh_namespace_valid`: `True`
- `argv_valid/cwd_valid`: `True` / `True`
- `resource_projection_valid`: `True`
- `launch_admitted`: `False`
- `worker_launch_authorized`: `False`
- `formal`: `False`, `credit`: `0`

即使 bounded host-I/O probe 通过，它也不是 root/scheduler authorization；本适配器因此保持 launch、worker、formal 和 credit 全部关闭。

## Source-bound 输入

- `proposal`: `reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-29-RERUN1.json`, SHA256 `1da4b0d9016b6036e8179c4e20f97e2067e7f9eb90fdaca56a5c42acf66ada4c`, match=`True`
- `host_io_receipt`: `reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-29-RERUN1.json`, SHA256 `042cd0b51305e1899a185a300da5f20a8b15116fe784df1147e03e1d5b1cf6bc`, match=`True`
- `core_material`: `scripts/core_material.py`, SHA256 `9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e`, match=`True`
- `core_runtime`: `scripts/core_runtime.py`, SHA256 `a4c6e03a13cb1ff80c0da7f7f9bd442e5e2de4d64e23551bf92a0220c6afa8c4`, match=`True`
- `source_h5`: `campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5`, SHA256 `3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575`, match=`True`
- `job_spec`: `campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json`, SHA256 `1f1080e497feab414863e3e02dd31dbec91c0d09e4ef9ac855e0cdbbda070628`, match=`True`

## 资源投影

- CPU-only: `True`；GPU forbidden: `True`
- projected owned I/O: `2097152` bytes
- projected total I/O: `2228224` bytes
- scheduler-owned I/O verified: `False`

## 阻塞原因

- `fresh_root_or_scheduler_authorization_missing`
- `measured_host_io_admission_missing`
- `source_preparation_manifest_launch_forbidden`
- `historical_job_spec_uses_forbidden_raw_script_path; use normalized module argv`
- `runtime_spec_core_material_binding_stale_against_current_code`
- `fresh_root_authorization_missing`
- `scheduler_authorization_missing`

## 执行边界

本适配器只读取 JSON/源码并对 source HDF5 做字节哈希；未打开 HDF5 结构，未启动 material worker、solver、GPU、queue，未改写 registry/completion/ledger/denominator/gate/PLAN 或历史 receipt。
