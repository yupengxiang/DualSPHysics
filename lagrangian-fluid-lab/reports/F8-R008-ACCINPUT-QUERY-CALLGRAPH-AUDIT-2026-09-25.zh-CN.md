# F8 R008 AccInput CPU/GPU/VRes 调用图静态审计

日期：2026-09-25（Asia/Shanghai）

范围：只读审计当前 tracked `src/source` 标准 CPU/GPU solver source 及可选 VRes branch。独立 `src_mphase/DSPH_v5.0_NNewtonian` 不属于 R008 标准 solver lineage。未修改 DualSPHysics source、未编译、未运行 GenCase/native decoder/solver/worker/GPU/queue，未读 production solver frame。

## 静态调用图

1. `main.cpp` 在 CPU/GPU 间选择 `JSphCpuSingle` 或 `JSphGpuSingle`；在 `_WITHMR` 路径中，VRes 还可由 `VRES` 命令选项或 `CaseName_vres00.bi4` 是否存在决定。CPU/GPU 基类分别以 `JSph(0)`/`JSph(1)` 构造；GPU branch 为一个被选择的 device。VRes 驱动对每个 VRes object 调用各自的 `ComputeStepVRes()`。
2. `JSph::LoadCaseConfig` 在 XML 节点存在时构造 `JDsAccInput`；其 `LoadXml` 再检查该节点是否 active 后才解析子项，因此存在但 inactive 的节点不会生成运行 entries。后续通过 `AccInput->Init(MkInfo)` 将 MK 范围绑定到实际 particle codes。
3. `JDsAccInput::ReadXml` 按 XML 顺序略过 inactive `<accinput>`，`time.start` 默认 0、`time.end` 默认 `DBL_MAX`。每个有效 `mkfluid`/`mkbound` 范围会被展开为连续 MK 段；一个 XML element 可生成多个 `Inputs` entry，重复覆盖被拒绝。entry 对其加速度表构造相应速度表。
4. 标准 CPU 唯一 host 施加点在 `JSphCpu::PreInteraction_Forces` → `AccInput->RunCpu(TimeStep,...)`；GPU 唯一 host 施加点在 `JSphGpu::PreInteraction_Forces` → `AccInput->RunGpu(TimeStep,...)`。两者的 `RunCpu/RunGpu` 都逐 `Inputs` 调 `GetAccValues(c, timestep)`；GPU 值在 host 端读取后传给 CUDA kernel，kernel 不查文件或时间表。
5. `JSphCpuSingle`/`JSphGpuSingle` 的 `ComputeStep_Ver()` 每步调用一次 `PreInteraction_Forces`；`ComputeStep_Sym()` 在 predictor 和 corrector 各调用一次。外层 Run loop 先检查 `TimeStep < TimeMax`，`ComputeStep()` 返回后才递增 `TimeStep`。故同一步 Symplectic 两次查询的时间戳相同；`JDsAccInputMk::GetAccValues` 对相同 `timestep` 命中 `LastTimestepInput` cache，corrector 重用同一采样值。VRes 禁止 Verlet，且 predictor/corrector 也复用同一 host `PreInteraction_Forces` 路径。

## 时间门含义

每个展开后的 entry (i) 只在含端点窗口 `TimeIni_i <= t <= TimeEnd_i` 内启用；窗口外返回 inactive code。启用时，`GetValue3d3d(t,...)` 经 `FindTime` 选择/钳制 `TimeFactor` 到 `[0,1]`，所以表格首末点外不会数学外推，而是保持首/末值。未来真实 no-extrapolation 证明应逐 entry 覆盖所有实际 force-query timestamp，并验证 active query 满足

```text
table_first_time_i <= t_query <= table_last_time_i
```

且同时满足该 entry 的 `TimeIni_i/TimeEnd_i`。只比较 `effective_TimeMax <= table_last_time` 既可能过度约束（若计算在最后一次 active query 后结束），也不能替代 query-source 的完整见证；若某一步 `dt` 跨过末行但 solver 在下一次 loop 检查前已达到/超过 `TimeMax`，末行之后没有 query，本身不构成外推。Symplectic corrector 使用的是该步起始 `TimeStep`，不在 `TimeStep+dt` 重新采样；这属于实际离散输入语义，不应由评估器自行改成连续时间假设。

## 对执行合同的影响与剩余边界

- C-execution payload 需按展开后的 `Inputs` entry，而非仅 XML element 或一个全局 accinput 区间，绑定输入索引、来源 element/range segment、时间窗、实际 table bytes/hash/首末时刻及 query journal。
- 每个时间戳需能归属于 CPU/GPU 与 integrator stage；Symplectic 同一时间戳的 predictor/corrector 两个调用应可区分，且可说明第二次由 per-entry cache 命中。
- 还须以 actual invocation、完整 argv/OPT、feature/build/source-to-binary、case/output/config snapshot、restart 起始 `TimeStep`、动态 `TimeMax`/TERMINATE/早停日志和资源终态证明实际 query 集完整。当前没有这些 R008 execution witnesses；也没有可绑定的 solver binary。
- 此审计仅闭合 tracked-source 的 AccInput 直接调用图和采样时序，不使 C v3 schema、F8 readiness、`T1_numerical` 或任何资格信用通过。

## 主要文件摘要

| Source file | SHA-256 |
|---|---|
| `src/source/main.cpp` | `43ce552b8177dad089148f7f552bc44f9467220eb0da6503964f6bfd6c888b4c` |
| `src/source/JSph.cpp` | `206e4486a3a0d304e02da1a73d2e7c7ed96354d559ce481275d09f5245b8c9e7` |
| `src/source/JSphCpu.cpp` | `7c7c01b3a5e6809b8f6f5129f30c8aac0a4b35f1bff2e1776af4a11e8442a617` |
| `src/source/JSphGpu.cpp` | `768570e7256168632d9d93ec8d4ac70ff751572a6f1b0fc14fb5a372e873309b` |
| `src/source/JSphCpuSingle.cpp` | `a261620354e4970f99e8314ddfede1349acef5de236af32e9921af324c021608` |
| `src/source/JSphGpuSingle.cpp` | `a8652f2422e1c7656f39aaac526c432ed992fc506e48de297410bb36cabe0361` |
| `src/source/JSphCpuSingle_VRes.cpp` | `f8be911d66f74978160c44269b3db76dc1dee5c50e7f38228661b01d86d3f615` |
| `src/source/JSphGpuSingle_VRes.cpp` | `709b516e28f688ee7992914bbdc61096caab732ea941ef6b211e2c4dac7eec71` |
| `src/source/JSphVResDriver.h` | `8c306e8c255b45fe6e1122185de80edb68d1b2c3746b7c0cf844ddee8b32f478` |
| `src/source/JSphCfgRun.cpp` | `51b8dc214181edc0518e4c7de42a71b9248dee891064de3efb74aa8b095a2c96` |
| `src/source/JDsAccInput.cpp` | `ea0f534e89b158fd86e41d9ea2f7a2587b6310b93350d211a3ce6169007e5423` |
| `src/source/JLinearValue.cpp` | `5059ea7113f2b5ae051f9cf37990ee0197927b9648b88e7cd957ef5d637b5f27` |
| `src/source/JDsAccInput_ker.cu` | `5909db626a9fde84e7e0a14bf95010cc39d31ec0d93cd3aa14f4d1c07b5c8bb3` |

Build-script hashes for `Makefile_cpu`, `Makefile` and `CMakeLists.txt` remain recorded in [UPDATE-61](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-61.zh-CN.md); their non-uniqueness and missing binary/build attestation remain open.
