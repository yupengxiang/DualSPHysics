# F3/F4 宏观 T2 admission contract（root-review-only，2026-09-21）

本产物只做 JSON/hash closure。没有重跑旧 CFD，没有启动 solver/GPU/queue，没有写 matrix、registry 或 ledger。

## 当前资格状态

F3 与 F4 的 T1 qualification receipt 都为 `T1_numerical=true`、`matrix_complete=true`，但两者都明确 `T2_macro=false`、`T2_path=false`。本合同不把既有 CPU/native、sidecar 或旧材料结果升级为 T2 credit。

F3 的两条完整 source/window 记录结构与质量闭合通过，但 fixed unknown 上限 `0.01` 和 CDF sup 上限 `0.02` 失败；最大 source unknown 为 `0.015625`。F4 保留的 6 个材料 case 全部 event-window 不完整，unknown gate 全部失败，虽 mass closed=true。

## 选择的最小候选

选择 `f4_ess32_v2`（F4 tallwall120 cell-14）作为唯一 deferred candidate。它绑定 T1-qualified 原生 source：1086 帧、217485 粒子、0–4.340002980805959 s，exact native rows，无 stride 或 synthetic cadence；已有固定 reconstruction/ESS/rank/anisotropy、unknown 和 event-window 合同。

该候选不是已通过的材料结果：frame 40→41 的 128-seed counterfactual survivor 为 0，既有 bounded preflight 在 frame 41 后为 511/512 unknown、right-censored。它只能作为一次新的、独立 output stem 的诊断性 material sidecar proposal。

## 唯一授权边界

当前 `authorized_now=false`。若 root 明确授权，唯一允许的下一步是：在同一已绑定 T1 source 上执行一次 CPU-only、单进程、cKDTree workers=1 的 `f4_ess32_v2` full-source material sidecar，使用既有合同的新 output stem，覆盖 frame 0–1085 和完整 4.34 s 窗口，并从 frame 40 的 content-addressed checkpoint 恢复。

该动作不重跑 CFD，不启动 solver/GPU/queue，不扩展 F3/F4 矩阵；旧负 trace 只能作为 binding input。所有 512 seeds 保留在分母中，unknown/right-censor 保持 unknown，任何失败都写 immutable negative receipt 并给 zero credit。即使 sidecar 完成，也不会单独把 `T2_macro` 或 `T2_path` 置为 true。

禁止改变 unknown、CDF、reconstruction、event-window 或 denominator 门；禁止丢弃未知样本、插值伪造 cadence、重用旧 trace 状态或写入 matrix/registry/ledger。

合同：`campaigns/core-v1/material/evidence/f3-f4-t2-admission-root-review-contract-20260921.json`；SHA-256 `04e02868af86d65758fb739ff4630fec658e384b7325bbdf66abd55d60edafac`。

## 绑定证据

- F3/F4 CPU source-window audit：完整来源窗口与 reader/reconstruction integrity 通过，但科学门失败；qualification claim=none。
- F4 macro sidecar preflight：sidecar provenance 通过，但不是独立 CFD；unknown/event/matrix gates 失败。
- F4 ESS32 candidate/full-source contracts：固定门、完整来源窗口、资源预算、checkpoint/resume 和新 output stem 已 hash-bound；candidate 仍 proposal-only。
- F3/F4 T1 qualification receipts：只证明 T1，不授予 T2。

本合同的 T2 credit、registry mutation、ledger mutation 和 Core gate effect 均为 0/false。
