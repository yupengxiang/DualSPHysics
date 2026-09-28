# Core continuation status — UPDATE-392

日期：2026-09-29

本条是独立文档交付，范围严格限定为 PLAN.md 末尾追加项、对应机器 JSON 和本中文报告。后续 subagent 策略为 GPT-5.6 Luna、reasoning max，并继续允许独立任务并行推进。

## 已核验提交

- 569928c4：修复 current-manifest intake 的 canonical manifest hash 与 evidence.status 契约；专项及旧 matrix 回归共 37 passed。
- 63316780：绑定三份 fresh current-manifest MLP hidden16 training receipt，seed 为 17、29、43，每路 500/500 updates；source_bound=true，diagnostic-only，formal training counted=0，credit=0。
- 6fa94fb4：完成参数化 current-manifest rollout adapter，使 manifest、checkpoint、training receipt、run ID、nonce 和 output namespace 显式绑定。
- bdd84a4a：完成 F3 material coarse canonical dry-run launch spec；该 spec 不等同于实际授权。

## 三路 current-manifest rollout 只读状态

观测时间：2026-09-29T04:06:34+08:00。三路均针对 case F3_DEV_00_a0p903125、test split、目标 835 transitions，在 GPU2/4/5 启动，使用独立 nonce 和 output namespace：

| GPU | seed | nonce | progress | status | terminal evidence |
|---:|---:|---|---:|---|---|
| 2 | 17 | f17a9c4e2d6b8f1035c7e1a9d4b6c802 | 25/835 | running | 未生成 |
| 4 | 29 | a29d6f3c8e1b5a7042c9f6d1b8e3a507 | 25/835 | running | 未生成 |
| 5 | 43 | c43e7a1d9b6f2c8054a8e3d7b1f9062c | 25/835 | running | 未生成 |

三路 progress 均报告 execution_complete=false、finite_rollout_complete=false、scientific_status=not_assessed；只读检查时 launchers/evaluator 仍存活，namespace 中尚无 evaluation output、terminal validator 或 artifact identity。PID 和 progress 都不是 terminal evidence，不能据此宣称 rollout 完成；须等待自然退出，并取得 terminal validator receipt 与 artifact identity 后再进行终态 intake。

## F3 material 粗粒度方向

bdd84a4a 的 dry-run launch spec 已完成，但当前仍为 blocked_missing_fresh_root_scheduler_receipts：fresh root receipt 不存在，scheduler-owned host-I/O reservation 不存在，launch_authorized=false，credit=0。

## Core formal gates

Core formal gates 与上一条记录不变：can_finalize=false；formal training 为 0/9；已完成 T1 family 为 2/3；macro T2 为 0/2；material case-run 为 0/288；independent reproduction、T1、T2 和 formal 均未闭合；credit=0。

## 执行边界

本条只修改 PLAN.md 末尾、UPDATE-392 JSON 和本报告；没有修改代码、registry、ledger、matrix 或 completion，没有重启 live job，也没有把诊断结果提升为 formal 或 qualification evidence。

机器回执：CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-392.json。
