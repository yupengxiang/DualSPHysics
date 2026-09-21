# Core 第三个 T1 候选路线审计（2026-09-20）

本轮的结论是：唯一值得进入 root review 的新路线是 `F1_suspended_obstacle_gap_v1`。它把障碍物从贴底 `[z=0.00,0.34] m` 移到 `[z=0.06,0.40] m`，保留 0.06 m 底部流体间隙，重新生成 `setmkvoid` 和 mDBC 壳层。该变化是连续体物理几何变化，属于新的 F1 机制范围；它不是 H1–H4 的边界配置重试，也不是静态 hold、重复输入或阈值放宽。

root review **尚未完成**。已写入受保护 anchor job spec，状态为 `protected_not_submitted`；本轮没有启动 solver/GPU，没有 queue、registry 或 ledger mutation。

## 证据判断

F1 的既有贴底边界类已经终止。H1 全窗出现 1,426 个 native ID 丢失和 166 个 wall endpoint frame；H2 出现 6,689 个 ID 丢失、53,742 个 wall violation frame，末态质量比例 0.94456；H3 出现 302,558 个 obstacle penetration frame、302,559 个 saved chord crossing 和 774 个 ID 丢失；H4 虽到达 2.2 s，但仅剩 89,956/120,658 个有效粒子，wall endpoint frame 为 265,270，obstacle penetration frame 为 1,358，hard integrity 为 false。因此没有可合法的同输入边界修复重试。

F2 的动态 DBC duration scope 仍是 15 行固定分母、0 行资格 credit。q=.75 的 5 s 锚点 hard integrity pass，但 motion 在 1.525 s 结束后没有 settled，event 为 false；terminal speed p95 为 0.399684 m/s。q=1.0 的 5 s 和一次 10 s 延长仍是 event-censored。静态 full-cup CPU closure 不作为第三机制。

F3 baffle v2 是科学上不同的动态交换机制，但不能增加唯一 family 数（当前 completion family 为 F3/F4）。8.35 s runtime 首次挡板穿透发生在 0.0100356 s，26,732/131,403 fixed particles 缺 normal，saved chord crossing 为 20,990，forward exchange 为 0，event 和 hard integrity 都失败；没有新的几何/normal 证据时不重跑。

## G1 CPU/native 预检与固定矩阵

G1 anchor 使用 `q=0.5, dp=0.0075`，仅运行 CPU GenCase 和 native `.bi4` decode。结果为 120,658 fluid、142,446 boundary、0 zero normal、0 exact fluid/boundary overlap，六个障碍物面均有粒子且 normal sign contract 通过，native mass relative error 为 0.01707548，preflight pass。它不构成 solver/event/T1 credit。

固定矩阵为 15 行：13 个 spatial cells（q=`0,0.5,1` 使用 3 个 dp，q=`0.25,0.75` 使用 2 个 dp）和 2 个 temporal cells（internal-time/native-output）。当前 `planned=15, executed=0, passed=0, failed=0, unattempted=15, credit=0`。每一行都保留在分母；禁止同输入重试、阈值放宽、提前延长 horizon、静态替代和 survivor renormalization。

观察算子沿用 F1 的动态障碍事件：2.2 s 初始窗；approach 为障碍 footprint 上方 2dp 内至少 1% active mass，downstream 为超过 obstacle xmax+2dp 至少 5% mass，return 为 downstream 后间隔 0.1 s 且 COM x 至少回退 `max(0.02 m,2dp)`；资格需要 hard integrity pass、event complete 和完整矩阵。若 hard-pass 后只是右删失，最多按固定规则一次扩展到 4.4 s。

## 受保护运行与资源

`protected-anchor-job-spec-v1.json` 指向独立 adapter `scripts/f1_suspended_obstacle_gap_runtime_v1.py`，明确 `queue_mutation=false`、`ledger_write=false`、`registry_write=false`、`solver_launch=forbidden_until_root_review_approval`。H4 作为同分辨率参考为 305.30 s solver、378.11 s total；G1 anchor 保护估算为 0.12 GPU-hours、4,096 MiB GPU、16,384 MiB RAM、3,600 s timeout。15-cell 全矩阵仅给出约 3.0 GPU-hours 的保守上界，不提交。

## 产物与哈希

| 产物 | SHA-256 |
|---|---|
| [candidate-card-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/candidate-card-v1.json) | `e419ab8acc78861e17e8ea8f672358c1819f918bb997813ce7edf4b23f098978` |
| [fixed-matrix-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/fixed-matrix-v1.json) | `136151eafbec649f4361e5a8416efa70adbced9cf58221e2d025c2f8673d9f4d` |
| [failure-denominator-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/failure-denominator-v1.json) | `7aa6afe3659133a2478172873159266f9cb69b2d51b0df6fddfd6a793eeb0d8e` |
| [lineage-clarification-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/lineage-clarification-v1.json) | `680f97c22a31a662461995a30f99148a0b05530298f3656d176eb9beccfd069b` |
| [cpu-native-preflight.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/cpu-native-preflight.json) | `7b1076a38c1d2121d0527079c493efe8474e555ea6e6cc1b8631c1846c248007` |
| [prepared.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/prepared.json) | `661b42a02873918bc4a753250a1775da6bb83260ce3154a76a5ae73b3f1c3f26` |
| [protected-anchor-job-spec-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1/protected-anchor-job-spec-v1.json) | `7cf6d8028aba1862adef3201847484d09f663c69b57536262a3feb98e0aee469` |
| [third-t1-route-audit-2026-09-20.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/evidence/third-t1-route-audit-2026-09-20.json) | `18556d777077c5e2509cc0caf00f91f83e149200f34f51a0b03ddf86aa789c93` |

## 测试

已通过：

- `.venv/bin/python scripts/f1_suspended_obstacle_gap_preflight_v1.py`：`preflight_pass=true`。
- `python -m py_compile scripts/f1_suspended_obstacle_gap_preflight_v1.py scripts/f1_suspended_obstacle_gap_runtime_v1.py`。
- runtime adapter `--help` 正常；prepared 输入、solver/decoder hash 和 native mass gate 均复核通过。

没有执行 solver、GPU、queue submit、registry write 或 ledger write。
