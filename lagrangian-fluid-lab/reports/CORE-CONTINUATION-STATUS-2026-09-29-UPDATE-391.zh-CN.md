# Core continuation status — UPDATE-391

日期：2026-09-29

本条是独立文档交付，范围严格限定为本条 PLAN 追加项、对应机器 JSON 和本中文报告。所有结果继续保持 fail-closed；后续 subagent 策略为 `gpt-5.6-luna`、reasoning `max`。

## 本轮已提交

- `b6460bed`：补充 denominator consistency 语义，明确 `missing_target = minimum - observed`、`missing_registered = required - observed`、`unregistered = minimum - required`；专项 `42 passed`，既有 completion snapshot 数值不变。
- `6e56259e`：新增 current-manifest MLP training-evidence intake；专项及原 V1 matrix 回归 `36 passed`。旧 receipt 因 manifest SHA drift 被正确判为 `blocked_fail_closed`，`source_bound=false`，不计入 formal training。

## Current-manifest MLP 诊断训练只读快照

观测时间：`2026-09-29T03:51:07+08:00`。GPU2/4/5 的 seed17/29/43 三条训练均使用独立 current-manifest run namespace；截至该次只读检查，三条均自然运行中，均为 `update=200/500`，loss finite，neighbor truncation 为 `0`。

| GPU | seed | run namespace | update | status | loss MSE | neighbor truncation |
|---:|---:|---|---:|---|---:|---:|
| 2 | 17 | `f3-mlp500-hidden16-currentmanifest-seed17-20260929` | 200/500 | running | 1.002898097038269 | 0.0 |
| 4 | 29 | `f3-mlp500-hidden16-currentmanifest-seed29-20260929` | 200/500 | running | 0.7490900754928589 | 0.0 |
| 5 | 43 | `f3-mlp500-hidden16-currentmanifest-seed43-20260929` | 200/500 | running | 1.6212282180786133 | 0.0 |

这只是 diagnostic-only 的运行健康快照。`update`、progress 文件和进程存活状态都不是 terminal evidence；三条训练尚未宣称完成，也没有增加 formal training、T1、T2 或 credit。当前该诊断命名空间的计数固定为 formal training `0`、T1 `false`、T2 `false`、credit `0`。

## V7、材料粗粒度方向与 Core 门禁

Core formal source closure V7 仍为 planning-only：13-file closure 的只读验证保持成功，但 `formal_release=false`、`formal_training_allowed=false`、`formal_job_count=0`、`launch_allowed=false`、`root_admission_granted=false`。

F3 material `CORE-F3-MATERIAL-COARSE-s2` 仍为 `blocked_missing_fresh_root_scheduler_receipts`。当前源码/hash、normalized argv/cwd 与 host-I/O admission contract 有效，但 fresh root receipt 和 scheduler-owned host-I/O reservation 仍缺失，因此未授权启动。

Core formal gates 与 UPDATE-390 相同：`can_finalize=false`；formal training `0/9`；已闭合的 T1 family 仍为 F3/F4，第三个 family 未闭合；macro T2 `0/2`；material case-run `0/288`；independent reproduction、launch/root admission 均未闭合；credit `0`。本轮没有任何 gate 或分母晋级。

## 执行边界

本条只修改 PLAN 末尾、UPDATE-391 JSON 和本报告；没有代码、registry、ledger、completion 或 matrix 变更，没有读取或改写训练大文件/旧历史记录，也没有重启 live job。诊断结果没有被提升为 formal 或 qualification evidence。

机器回执：[UPDATE-391 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-391.json)。
