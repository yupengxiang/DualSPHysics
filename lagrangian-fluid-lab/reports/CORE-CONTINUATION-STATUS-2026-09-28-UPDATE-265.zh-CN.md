# Core continuation status — 2026-09-28 — UPDATE-265

## F3 native-volume MLS v2 bounded candidate审查

结论：现有 `native_volume_mls_v2_current_frame` 的输入合同清晰、没有未来 native true-value 读取，且在当前 F3 `F3_DEV_00_a0p903125` 上完成了 512-seed、836-frame、835-transition 的 CPU diagnostic。它的 candidate reliable 为 100%、unknown 为 0，但完整 trace 仍有 **441 个原 F3 gate 失败样本**。因此只能保留为 diagnostic-only 候选，**formal=false、T1=false、T2=false、credit=0**，不进入 full rollout。

机器可读回执：[F3 v2 diagnostic receipt](F3-MATERIAL-NATIVE-VOLUME-MLS-V2-REAL-FULL-2026-09-28.json)。

## 候选边界审查

| 候选 | 输入/时间语义 | 本次结论 |
|---|---|---|
| `temporal-v3` | 当前区间使用 `F_i` 与 `F_{i+1}` native endpoint 插值 | 在严格 online-causal 规则下不选；`F_{i+1}` 仍是中间 RK stage 的未来 native true value。本次只做当前源 audit，不运行 full case。旧 full evidence 绑定不同历史 source，不复用。 |
| `native_volume_mls_v2_current_frame` | 当前帧 native mass/density；weighted affine MLS SVD；区间 `i` 的所有 RK stage 只读 frame `i`；无 interpolation、future velocity/density 禁止 | 合同清晰且 diagnostic-safe，运行一次真实完整 836-frame CPU diagnostic。 |

v2 与 `baseline24`、`h2_k48`、`h1_affine_bound` 的正交性来自 native-volume current-frame affine MLS backend；本次没有重复这三个候选，也没有改生产算法或 gate。

## 真实输入与最终 HDF5 核验

- source：`F3_DEV_00_a0p903125.h5`，SHA-256 `8fd78cf3…609ff06f4`；836 frames、34,560 particles、835 transitions，时间 `0 → 8.350012828223477 s`。
- source/PREPARED/XML/wall binding 均与 audit receipt 一致；native frame selection 是 identity、无插值，current-frame contract audit `preflight_passed`。
- trace schema 为 `core.material.f3.native_volume_mls.trace.v2`；`position` shape 为 `(836, 512, 3)`，time 严格递增且终点正确，位置/质量有限，seed mass closure error 最大值为 `0.0 kg`，wall rejected 最大值为 `0`。
- candidate support pass 与 candidate reliable 均为全 trace 通过；candidate support count 最小值 `51`，ESS 最小值 `12.520080758558398`，geometry rank 最小值 `4`，condition number 最大值 `4.244361077363391`。
- 临时 HDF5 SHA-256：`f99e0c101c5c60ee723132e6bbaea34eddbc8f85d02f909123e6d416502310f0`；summary SHA-256：`049ad5434d87defa6a9dcaf8c580502f0e5e8d5022bfb559c8e65a62a063896e`。临时结果不写入仓库。

## 与 prior candidate 和原 F3 gate 对照

| 路径 | source 0 unknown | source 1 unknown | common reliable coverage | 固定 unknown≤1% | 原 F3 gate |
|---|---:|---:|---:|---|---|
| `baseline24`（UPDATE-239） | 0.0390625 | 0.03125 | 0.96484375 | fail | prior receipt仅报告 unknown fail |
| `h2_k48`（UPDATE-253） | 0.0546875 | 0.03125 | 0.95703125 | fail | prior receipt仅报告 unknown fail |
| `h1_affine_bound`（UPDATE-261） | 0.0859375 | 0.09375 | 0.91015625 | fail | prior receipt仅报告 unknown fail |
| `native_volume_mls_v2_current_frame` | 0.0 | 0.0 | 1.0 | pass | **fail：441 个 frame×seed 样本** |

这里有两个不能混淆的 gate：

1. v2 的 candidate gate 只检查当前 native-volume MLS 的 support/ESS/rank/condition，因此它可以得到 reliable=100%、unknown=0。
2. 原 F3 gate 仍作为 comparison-only gate 保留，包含 reconstruction error 上限 `0.04698137929009748 m/s`、anisotropy、ESS、rank 和 support-distance 条件。`old_gate_pass` 在完整 trace 中有 **441 个 false**：source 0 为 259、source 1 为 182，分布在 frame 249–788；这 441 个样本的 reconstruction error 范围为 `0.047007481808694684–0.09312770934160079 m/s`，全部越过原 residual 上限。最终 frame 的 `old_gate_pass` 恰好全部为 true，但不能抹掉中间历史失败。

因此，candidate reliable=100% 不是原 gate 通过，更不是 T2 证明。该候选不满足“固定 gate 全程无失败”的晋级条件。

## Acceptance bridge 与 formal 边界

只读验证现有 bridge v4 receipt 后，状态仍为 `blocked_for_acceptance_zero_credit`，decision 为 `read_only_reconciliation_complete_no_qualification`。既有 bridge 的 T2 macro/path 均为 false、credit=0；其固定阻塞包括既有 per-source unknown/CDF 超限、dense cadence `.01` 与要求 `.002` 不一致、33-row formal receipt 不完整，以及本次单 case 没有 CFD truth/CDF acceptance receipt。

本次 v2 单 case 不回写 bridge matrix，也不制造 formal row；不改变 registry、ledger、denominator、threshold 或 gate。结论固定为：

- `formal = false`
- `T1 = false`
- `T2 = false`
- `credit = 0`
- `qualification_claim = none`

## 验证与写集

- v2/compare/temporal/shared/bridge 定向测试：**48 passed in 7.85s**。
- `py_compile`：passed；`git diff --check`：passed。
- 本次只新增本 status report 与上述 diagnostic receipt；没有新增候选代码，没有启动 solver/worker/GPU/full rollout，临时 HDF5/checkpoint 未提交。
