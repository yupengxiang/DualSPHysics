# Core continuation status — UPDATE-399

日期：2026-09-29

本轮按“粗到细、模块并行、每个可提交单元立即提交”的策略，完成 F4、F3 graph_raw、F3 material coarse、F8/R008、A8 五条支线的独立收口。所有新增 subagent 均按当前策略使用 `gpt-5.6-luna`、reasoning `max`；历史模型记录保持不变。

## 本轮独立提交

- F4 Tallwall120：`91dd7829`、`b7918967`、`7eee3165`、`c7ccf933`。新增 archives-v1/v2 与 reader-manifest SHA reconciliation，并将 root/scheduler admission、source-drift、readiness projection 串接到该合同。F4 专项联合回归 `57 passed`。
- F8/R008：`0a6ada39`。新增 12 项 bounded untrusted blocker inventory：6 项 target kernel/source/build pin、6 项 trusted-runtime/ABI/conformance。专项 `9 passed`，所有声明仍为 untrusted，readiness/T1/credit=`false/0`。
- F3 graph_raw：`2fe7bf7f`。新增 current-manifest hidden16 audited executor/canary contract；3/3 训练 receipt、manifest、checkpoint identity 和 GPU4/5/6 resource admission 绑定成功，但 terminal HDF5 validator/artifact identity capability 尚未安全授予。
- F3 material coarse：`cf632c75`。新增 source-path provenance v2，补上 parent-component symlink、root/realpath containment、single-hardlink 检查。专项 `11 passed`，material 相关合并回归 `40 passed`。
- A8：`9fb65ef5`、`0cac0c11`。独立 reproduction readiness contract/report 保持 blocked：缺 trusted root review、external host attestation 和另一台物理机的 non-diagnostic full-product evidence。

## 当前结果

| 模块 | 当前状态 | 关键结果 | formal/T1/T2/credit |
|---|---|---|---:|
| F4 Tallwall120 | `blocked_fail_closed` | root receipt、scheduler-owned host-I/O reservation、current manifest/reader SHA reconciliation 仍缺；sidecar `0/32` | `false/false/false/0` |
| F3 graph_raw audited executor | `blocked_fail_closed` | GPU4/5/6 admission 通过；terminal capability 未被授予；process proof `0/3` | `false/false/false/0` |
| F3 material coarse v2 | synthetic-only | source-path provenance hardening 完成；不授予 launch | `false/false/false/0` |
| F8/R008 | untrusted inventory | target pin `0/6`、trusted runtime `0/6` 闭合 | `false/false/false/0` |
| A8 | blocked readiness | trusted root/external host/non-diagnostic reproduction 缺失 | `false/false/false/0` |

GPU2–7 本次观察各约 `48,494 MiB` free；已有 GPU0/1 任务未停止、未重启。显存充足只满足资源观察条件，不替代 audited executor、terminal validator、root admission 或 formal gate，因此没有裸启 full835 batch executor。

## 验证与 Core 门禁

跨模块定向回归为 `176 passed`；目标脚本 `py_compile`、report CLI verify、`git diff --check` 全部通过。未启动 solver/worker/native/queue，未读取生产数据，未写 registry、ledger、denominator、gate 或 completion。

Core 仍为 `can_finalize=false`：T1 families 为 `F3/F4`（2/3），macro T2 为 `0/2`，formal training 为 `0/9`；missing training runs 为 9 个，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。

下一步仍是先完成 terminal HDF5/artifact validator 的受审计闭环，再在新 namespace 中运行有限 graph_raw canary；在 capability、fresh root/scheduler receipts 或可信外部 reproduction 缺失时，继续保持 fail-closed，不把 GPU 空闲、PID、progress 或 synthetic receipt 当作完成证据。
