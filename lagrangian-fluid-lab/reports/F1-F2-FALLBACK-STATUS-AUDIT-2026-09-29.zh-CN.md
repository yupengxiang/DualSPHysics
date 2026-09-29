# F1/F2 fallback 当前状态审计（2026-09-29）

本审计严格只读现有文件和运行态，未启动 solver、GenCase、native decoder、worker、GPU/queue workload，也没有修改 formal gate、registry、ledger、分母或 `PLAN.md`。结论是：当前没有可以合法推进的新 physics Definition、可认证 trusted root，或属于新 Definition 的可执行 15-case 输入。

## 结论

| 路线 | 新 Definition | 15-case 输入 | trusted root | 当前决定 |
|---|---:|---:|---:|---|
| F1 H1 prepared matrix | 否；当前路线已关闭 | 15/15 prepared，但 15/15 runtime 缺失 | 否 | 不可执行；必须先有超出 H1/H2/H3/G1 的新 Definition、外部授权和完整 runtime evidence |
| F2 static full-cup v4 | 否；旧候选/准备产物 | 15/15 prepared；1 个历史硬失败、14 个 runtime 缺失 | 否 | 不可执行；cell-00 失败不可被准备产物覆盖，需新的 root review 和 fresh 15-cell admission |
| F2 receiver ballistic release010 v2 | 只有条件性 proposal | 15 个 planned，0 个 materialized | 否 | 不可执行；literal Definition、事件归属合同、fresh CPU/native preflight 和第二次 root review 均缺失 |

F2 v2 是唯一值得保留为“未来条件性假设”的路线，但它不是当前可执行任务：候选卡明确 `root_review_only`，root-gap audit 明确 `No literal Definition`、`proposal_only/unmaterialized`，且 v1 的 Definition、XML/BI4、trajectory、output stem 都禁止继承。

## 关键证据

- F1 readiness bridge：`execution_authorized=false`、`formal_run_ready=false`；source identity 尚未闭合，15 个 runtime rows 全部缺失。
- F1 prepared audit：15 个 prepared cells、0 个 formal runtime rows、15 个 missing runtime rows；这是 preparation-only，不是 solver evidence。
- F1 admission contract：Definition/Core manifest/known inputs/solver/runtime/per-cell hash 需要 external trusted root，且 launch/gencase/native/solver/worker/GPU/queue 全部为 `false`。
- F2 static full-cup bridge：1 个历史 cell-00 hard failure、14 个 runtime rows 缺失、Core interface `formal_release=false`，当前 `formal_run_ready=false`。
- F2 receiver v2 root-gap audit：没有 literal Definition；receiver contact 与 retained/spill ownership 尚未 root 冻结；现有 v1 CPU/native 证据不可继承；必须第二次 root review。
- 当前 F1/F2 route closure：`route_closed_no_new_hypothesis`，要求新的可证伪 physical Definition、新 scope/case/output namespace 和重新 root review。

报告引用的机器证据及 SHA-256 见同目录下的 [机器收据](F1-F2-FALLBACK-STATUS-AUDIT-2026-09-29.json)。本次没有把“root review JSON”误认成可信执行根；审计范围内 `/var/lib/dual-sph`、`/etc/dual-sph`、`/run/dual-sph` 均不存在外部根文件，且没有 route-specific authenticated authority envelope。

## 运行态与验证

审计时保留了已有 Core runtime/archive 进程，以及一个既有 F3 diagnostic evaluate；没有停止、重启或复用它们。GPU 显存充足不改变 authority/provenance 门槛，也不产生 F1/F2 启动授权。

针对 F1/F2 route closure、prepared-runtime admission、readiness bridge、fallback boundary 和 pour-catch route 的定向回归为 **52 passed in 0.95s**。当前唯一合法下一步是先取得独立认证 root review 和全新的 literal Definition；在此之前保持 fail-closed，不 materialize、提交或启动任何 F1/F2 15-case workload。
