# Core continuation status — 2026-09-27 — UPDATE-234

## F3 real 32-case reader inspection

使用仓库 `.venv/bin/python` 从 `lagrangian-fluid-lab` 运行：

```text
PYTHONPATH=. .venv/bin/python scripts/core_benchmark.py inspect \
  --manifest campaigns/core-v1/f3-dataset-v2.json --data-root .
```

只读 inspection 成功打开真实 F3 开发资产 **32/32** 例。绑定 manifest SHA-256 为 `8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；全部案例均为 34,560 粒子、836 帧，时间轴为 `0–8.350012828223477 s`，split 为 train 16、validation 4、test 12，family 全部为 F3。该结果只证明 source reader/基本时间轴和身份轴可读；本次没有执行全量 source hash/transition oracle/full-scan，也没有改变 F3 的历史 split 或资格结论。

## F8 R008 native-integrity v7

GPT-5.6 Luna Max 对 v6 的静态复核为 `REVISE`（无 P0）。新增 [proposal v7](F8-R008-NATIVE-INTEGRITY-SEMANTICS-PROPOSAL-V7-2026-09-27.zh-CN.md)，逐项补齐 fresh `PARTBEGIN`/restart/`NSTEPS`/`SvAllSteps`/`TERMINATE`/有效 binary64 `T_end` 输入边界，展开实际 writer inventory 和每 writer flush/close/退出后交叉校验要求，明确同一 trusted attempt 内合法 append 与跨 attempt/preexisting append 的区别，并规定 bounded attempt/output binder、raw RunPARTs token、`RealStr` 与 stateful OutputTime cadence 的后续接口。

v7 仍不改 registry、gate、15×8 分母、T1/readiness/credit 或执行权限；当前 binder/parser/reducer 仍不得被当作可信 runtime 证据。新增 binder 的 synthetic-only 实现与跨 attempt 反例测试正在独立推进；在 trusted producer/supervisor/runtime identity 和真实 writer evidence 闭合前，F8 仍不能执行 T1。

本轮没有读取 F8 production bundle/frame，没有启动 GenCase/native decoder/solver/worker/GPU/queue。F3 reader inspection 不产生 T1/T2 credit；`core_campaign.py status` 的 Core completion 状态不变。
