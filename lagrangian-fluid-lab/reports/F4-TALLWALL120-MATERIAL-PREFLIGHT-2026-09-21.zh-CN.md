# F4 tallwall120 材料 CPU-only bounded preflight（2026-09-21）

本次 preflight 复用了 T1 已 qualified 的 `F4_resting_pool_laminar_tallwall120_x_v1` cell-14 原生轨迹，执行固定 baseline24 可见邻居 Shepard 后端的 512-seed 材料 sidecar。它只读取原生 HDF5；轨迹使用注册的相邻 native frame 线性 `x/v` 插值和每个 native interval 两个 RK2 子步，并通过已有 content-addressed checkpoint 从 frame 20 恢复到 frame 70。没有 stride、合成 cadence、保存弦插值或未知路径丢弃。

## 结果

| 项目 | 观测 |
|---|---:|
| 原生源窗口 | 0–4.340002980805959 s，1086 frames，217485 particles |
| bounded committed frame/time | 70 / 0.280007101649063 s |
| 固定 seed 分母 | 512 |
| unknown | 511 / 512 = 0.998046875 |
| unknown 上限 | 0.01，**不通过** |
| reliable path coverage | 0.001953125 |
| mass closure | true |
| event window | `right_censored_or_unresolved`，未完成 |
| 首次 reliability loss | frame 41，0.1640080936314531 s；共 511 seeds 在 bounded trace 内失效 |

该结果是负 canary 证据，不构成材料 T2 qualification。`T2_macro=false`、`T2_path=false`、`qualification_credit=none`；科学分母、registry、ledger 与 Core gate 均未改变。固定 reconstruction gate 仍为 `error <= 0.04698137929009748 m/s`、ESS `>=4`、rank `>=3`、anisotropy `>=0.005`，unknown gate 仍为 `<=0.01`。

完整 transition component attribution 没有作为必要条件重复读取 10 GB 源；diagnosis artifact 是已提交 trace 的 reliability profile，明确保留 right-censor 和未做 component 归因。stage checks 仍记录了 source read、native adjacent interpolation、visible-neighbour search、finite-wall visibility、RK2 integration 和 checkpoint resume。

## 约束与验证

`solver_started=false`、`gpu_started=false`、`new_job_submitted=false`、`queue_mutation=0`、`registry_mutation=0`、`central_ledger_mutation=0`、`thresholds_changed=false`、`scientific_denominator_changed=false`。

针对性测试：`4 passed`。

receipt 与产物 SHA256：

```text
scripts/f4_tallwall120_material_preflight_v1.py
872daf5a8f3a5cf1e5cccc55d599c21396b4da3634d6a0ffdefddb335ddbcbd2
tests/test_f4_tallwall120_material_preflight_v1.py
f9d56e3ce5efaa3678851d0e2395c80439f5129ccbe29b769f47ec34d78f4e0d
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.json
f5e6dc499e19349324799f36a154b5bfc7c6bb9be03b0c0e9df27a4acd7fc9bf
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.trace.h5
66676c11c7ee0c2582439357dbc703af83ddf4fcc24c1b4ba4cf9b917e4d1043
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.trace.json
b12a0e4a26a61e226f386776c54b90b6752a668b642b13e2b4f5a704f2c4973c
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.diagnosis.json
b0c59379eb5cad9363a504fed9ead64d9385d5777aa32206c3649e52e537542a
campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.trace.h5.checkpoint.json
9a6b5e23401f47d51662113458feb04c0ff9398d55a76958aeb34a8164cd4e8a
```

