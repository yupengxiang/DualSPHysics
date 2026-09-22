# F4 f4_ess32_v2 独立 root review（2026-09-21）

结论：`proposal_only_blocked_by_zero_counterfactual_survivor`。本次只读验证现有合同与 JSON hash closure，没有启动 sidecar。

## 阻断原因

已有 ESS32 合同的 frame 40→41 counterfactual cohort survivor 为 `0`。既有合同本身因此标记 `deferred`，要求先完成新的 candidate implementation review；当前没有足够证据把这个未验证实现授权为 full-source sidecar。该判断不修改任何质量门，也不把失败材料结果升级成 T2。

## 来源窗口与合同核验

T1 source binding 为 1086 个 native frames、217485 particles、0–4.340002980805959 s，exact native rows，无 stride/synthetic cadence。source SHA、candidate/preflight/root-cause/旧 admission JSON 及旧合同实现 SHA 均通过核验；目标 output stem 与全部 planned artifacts 均不存在。此 review 没有打开或重新哈希 HDF5。

## 固定门与授权边界

unknown 上限继续为 `0.01`，right-censor 保持 unknown，event window 必须完整，禁止 partial credit。已有 bounded preflight 为 `511/512 = 0.998046875` unknown 且 right-censored，T2 macro/path 均为 false。

当前 `authorized_one_cpu_only=false`。若未来产生新的、版本化且 hash-bound 的 candidate implementation，并再次通过 root review，届时最多只能授权一次 CPU-only、单进程、512-seed、frame 0–1085 的 material sidecar；禁止 CFD/solver/GPU/queue/ledger/registry/matrix。

本次不生成 sidecar、不写入输出前缀、不改变 denominator、threshold、Core gate 或历史负证据。

新 review receipt：`campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json`；SHA-256 `b6e7e92435179d25cc524e006b53c482259dc22065e30b5297d6ed4975dc7b7a`。
