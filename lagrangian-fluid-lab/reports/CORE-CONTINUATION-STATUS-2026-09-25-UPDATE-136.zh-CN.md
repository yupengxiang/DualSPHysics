# Core 计划续推状态 UPDATE-136

## 本次推进：复核当前 Core 缺口与 F4 support-cap 边界

使用项目锁定环境只读核对 `core_campaign.py status` 与 F4 support-cap R002 证据。Core 总门仍为 `can_finalize=false`：T1 仅 F3/F4 两族，宏观 T2 为 0 族，正式训练为 0/9；T1 已登记分母缺 288 个 case-run，第三族的 144 个 case-run 尚未登记，固定最低目标为 432；材料目标 288 个 case-run 均未登记。因果谱系与证据结构检查通过，当前 `issues=[]` 不代表 Core 完成。

F4 support-cap 候选的 R002 CPU/native 预检收据为 `preflight_passed_runtime_not_authorized`。六份资源快照均为 `deferred_resource_gate_not_started`；没有启动 canary、tracer、solver、GPU 或 queue。候选仍为零 T2 credit。其实现、静态设计、root review 与 preflight 回归共 **50 passed**（仅定向 synthetic/static tests）。

F3 row30 R003 仍是已终结的失败结果：每来源永久未知比例分别为 1.0742% 与 1.0254%，超过冻结 1% 门槛，且没有绑定同 attempt 的 512/4096 CDF 对照。既有 R003 不重试，阈值、分母与资格信用不变。

F8 R008 readiness v4 的两个关键开放项仍是独立审查过的逐案例 GenCase/native materialization verifier/worker evidence contract，以及完整、来源验证的 15 行 solver 结果。近期 attempt-ledger/receipt/journal readers 都只产出 untrusted、unresolved 诊断；它们不关闭这两项，也不授予执行或资格信用。

本次没有改动数据、配方、阈值、分母、registry 或 ledger；没有执行 GenCase/native decoder、worker、solver、GPU 或 queue。Core 继续按完整计划未完成状态推进。
