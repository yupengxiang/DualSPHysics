# UPDATE-205：F8 R008 最后 PART 与 terminal flush 证据格式提案

时间：2026-09-26（Asia/Shanghai）

## P3 的只读源码探索

为具体化 UPDATE-204 的 P3，核对 DualSPHysics v5.4 CPU 输出源码。发现无需假设额外 solver instrumentation 的候选证明：初始化 `SaveData()` 后 `PartNstep=0`；主循环每次成功保存后将 `PartNstep=Nstep`；每条 RunPARTs `Steps` 因而是连续保存间的步数增量。正常结束日志给出最终 `Steps of simulation`，同一 PART 的主 BI4 `PART_####` metadata 存精确 `Step=Nstep` 与 binary64 `TimeStep`。若所有 RunPARTs 增量总和、末主 BI4 Step 和终端 Nstep 精确相等，且无 restart/append、`NSTEPS` debug break、minimum-fluid stop 或动态 `TERMINATE` horizon 修改，就能由来源代码推出最终保存发生在末个已应用步。官方 `SaveData` 源码在此保存返回后清空 `PartsOut`；若 writer 报错则正常成功退出/完整 footer 条件不成立。

据此新增只读 [terminal completion/flush evidence contract v1](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V1-2026-09-26.zh-CN.md)，等待独立复核。合同固定 CPU 单-piece、新鲜从零运行；定义 `RunPARTs.Steps` 累加、terminal log Nstep、PartInfo `Step`/binary64 `TimeStep`、正常退出与 output manifest 的交叉等式，并要求未来可信 supervisor 绑定进程状态、OPT、唯一写入者、TERMINATE 监视及原始 artifacts。现有日志/产物的普通 caller-supplied 值不认证来源；当前缺可信 supervisor 与任何生产执行 evidence，因此仍无 gate 判定或资格 credit。

## 边界

本轮只读静态源码和合同，没有生产数据、测试或 workload；未改 solver 源码/二进制、R008 frozen scope、registry、ledger、分母、receipt 或权限。此提案只补充 v5 的 runtime-trace format P3；须经审阅且未来实现可信 supervisor/artifact bindings 后方可进入诊断 verifier，仍不能改变 exclusion gate v1 的 `open/missing` 全零 outcome 限制。
