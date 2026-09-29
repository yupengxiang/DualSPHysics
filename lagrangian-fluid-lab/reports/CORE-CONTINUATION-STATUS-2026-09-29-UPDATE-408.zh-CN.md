# Core continuation status — UPDATE-408

日期：2026-09-29

本轮按“并行、由粗到细、每个可提交单元及时提交”推进。当前所有新 subagent 均按 `gpt-5.6-luna`、`max` 调用；历史记录没有被改写。GPU 策略保持不变：只要独立准入的 VRAM/CPU/I-O 预算充足，可以共享占用 GPU；不停止或重启已有进程。

## 已完成的独立单元

- `5b2a9a14`：F8/R008 v7/v8 readiness RERUN1。为历史 v6 receipt 建立不可变锚点，明确记录三个 source drift，保留旧 receipt；v7/v8 定向测试 `13 passed`，仍为 fail-closed、zero-credit。
- `fe9bbede`：F3 material coarse s2/s4 readiness sidecar。绑定当前 source SHA、s2/s4 spec、argv/cwd 和 scheduler-owned `core_runtime` 入口；新增 RERUN 报告与测试。代理限定回归 `103 passed`，父代理复核子集 `58 passed`。fresh one-shot root receipt 与 scheduler-owned host-I/O reservation 仍缺失，因此没有执行 workload。
- 本轮其他独立回归：Core formal/production `88 passed`、F1/F2 `30 passed`、F3/F4 `73 passed`、F6/F7 `20 passed`；当前显式 tests 路径收集 `5,403` 个 node。未将一次全量测试声明为通过。

## 当前正式状态与下一步

`core_campaign.py status` 仍为 `can_finalize=false`：T1 family 只有 F3/F4，macro T2 为 `0/2`，formal training 为 `0/9`，目标 T1 case-run 缺 `432`，material case-run 缺 `288`，independent reproduction 为 `false`，credit 为 `0`。

下一条粗粒度主线已经收敛到 F3 material coarse：先由受审计的 `core_runtime` 使用 fresh root admission 和 scheduler-owned host-I/O reservation，跑通一个真实 CPU-only s2/s4 侧车，再验证完整时域材料门槛，之后从 `8` 扩展到 `32` 个案例并复制到 F4。当前不允许直接调用 worker 或裸启 batch executor；缺少上述真实外部 receipt 时，入口继续 fail-closed。

本轮没有启动生产 workload/Popen/solver/worker/GPU/queue，没有读取 production data，没有停止或重启已有进程，也没有修改 registry、ledger、denominator、gate 或 completion。核验时 GPU0–7 均约 `48,497 MiB` free，utilization 为 `0%`；显存充足不替代 scheduler trust anchor、terminal receipt、外部 root/host attestation 或正式资格门禁。

详见 [UPDATE-408 JSON](CORE-CONTINUATION-STATUS-2026-09-29-UPDATE-408.json)、[F3 readiness sidecar](../scripts/f3_material_coarse_s2_s4_readiness_v1.py) 与 [PLAN.md](../../../PLAN.md)。
