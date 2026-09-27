# F8 R008 native-integrity semantics proposal v6

状态：依据 Terra High 对 v5 的只读审查作 additive 修订，等待 Terra High follow-up 只读复核。用户已指定后续 subagent 统一使用 Terra High；本审查不是原计划列出的 GPT-6 Luna Max 审查。v5 与更早版本、既有 receipt 均保留不变。

v6 只收紧未来证据契约，不实现 gate，不改变冻结 R008 scope、八个 gate ID、阈值/单位、15-case × 8-gate 分母、历史 receipt 或执行权限。不读生产 bundle/frame，不运行 GenCase、native decoder、solver、worker、GPU 或 queue，不产生资格信用。

## 1. Frozen registry outcome 与确定性映射

逐项服从 `scripts/f8_r008_native_integrity_registry_v1.py`：

| Gate | v1 definition | v1 outcomes |
|---|---|---|
| `native_state_finite` | open | `defined_fail` / `open` / `missing` |
| `density_range` | defined | 四种注册状态 |
| `mach_limit` | defined | 四种注册状态 |
| `wall_penetration_limit` | open | `open` / `missing` |
| `excluded_fluid_particles_zero` | open | `defined_fail` / `open` / `missing` |
| `particle_overlap_absent` | open | `open` / `missing` |
| `inclusive_three_period_window_complete` | defined | 四种注册状态 |
| `control_no_extrapolation` | defined | 四种注册状态 |

四种注册状态为 `defined_pass`、`defined_fail`、`open`、`missing`。v1 下四个 open gate 均不得 `defined_pass`。排除粒子 gate 采用以下确定性映射：

- 同一经认证 attempt 中至少一个正排除 PART 的完整身份/计数对账可信成立，则为 `defined_fail`。单个可信正事件已反证“全程零排除”；该 fail 不要求整段运行继续到 `T_end`，但该事件本身必须绑定可信 attempt 和原始输出。
- 全部要求的 PART、终止与写入闭环均可信完整，且所有 `NpOut==0`，则为 `open`，不是 pass。
- 无可信正事件，且 attempt、输出、PART 序列或终止闭环任一缺失/不可信/不完整，则为 `missing`。不得把部分零行归纳成全程零。

若未来需要把零排除 gate 定义并判 pass，必须另提新版本 registry 并独立审查。其他 gate 仍严格遵循其冻结 outcome domain。

## 2. 防止跨 attempt 拼接

“同一 authenticated attempt”不是由调用方自述字符串满足。未来可信 verifier 必须以既有受信 provenance/执行身份链验证一个不可复用的 attempt：唯一 attempt ID/nonce、进程 PID 与 start-time generation、exec epoch、精确 argv/cwd、solver binary/build/features、Definition/control/初始状态摘要，以及新建且独占的输出根目录身份（namespace 内 dev/inode 与 no-follow 打开对象）。目录不得预存、复用、别名指向或包含 restart/append/第二次启动；不能证明 fresh 单次使用则为 `missing`。

`RunPARTs.csv`、每个 PartOut block 和其他必需 native 输出都须绑定至该 attempt、输出根对象、写入进程 generation 与具体文件对象；逐行/逐 item 的原始 bytes、长度、digest、PART 和时间一并绑定。进程退出后须在同一根对象下 no-follow 重开并稳定复核最终文件身份、长度和 digest。来自不同启动、不同 inode/路径别名、不同配置/二进制或不同进程 generation 的记录永不合并补齐同一分母。仅有相同文件名、caller-supplied attempt ID 或自报摘要不构成认证。

## 3. PART 调度和逐 PART 对账

对本提案覆盖的 CPU 单-piece 路径，按锁定配置及源码状态迁移推导实际预期 PART，而非要求每个名义输出网格点必然出现：

1. 从可信初始化的 `PartIni`、`TimeStep`、`TimePartNext`、`SvAllSteps` 与 `OutputTime` 规则开始；CPU `Run()` 的初始 `SaveData()` 也属于预期事件序列。
2. 每个完整应用步更新 binary64 `TimeStep` 后，仅在 `TimeStep >= TimePartNext` 或 minimum-fluid 条件下保存主 PART。保存后以当时实际 `TimeStep` 计算下一阈值：`SvAllSteps ? TimeStep : OutputTime->GetNextTime(TimeStep)`。若单步跨越多个名义 cadence 点，不额外合成缺失 PART；根据该递归迁移生成且只接受精确连续的实际 `RunPARTs` PART 序列。
3. 每行绑定原始 CSV bytes、Part、Steps/TimeStep、保存调用与同一 attempt。任意重复、遗漏、乱序、跨 attempt 拼接或与实际状态迁移不符均拒绝。

每个 `NpOut` 必须精确等于 `NpOutPos + NpOutRho + NpOutMov`。若 `NpOut>0`，必须恰有一个跨所有 block 唯一的匹配 PartOut payload；其文件/block、`Cpart`、`PART_####` 名称和 RunPARTs.Part 相同，`Nout`/唯一 `Idp` 数/`Motive` 数与 `NpOut` 相等。BI4 `TimeStep` 必须 bitwise 等于可信保存事件的 binary64 时间；RunPARTs 时间 token 必须精确符合已 pin 的 `RealStr` 格式化语义，不使用容差。要求 `Idp` 属于已认证 case 的身份域；数组行顺序一致，且各首维恰为 `Nout`。`Pos` 与 `Posd` 按冻结 `SvPosDouble` 恰选其一，并要求 `Vel`、`Rhop`、`Motive`。Motive 只接受 `1=invalid position`、`2=invalid density/rhop`、`3=invalid movement`，重算 histogram 分别精确等于 RunPARTs 三原因计数。重复 payload、unknown code 或任何差异拒绝。

`NpOut==0` 时 PartOut item 可缺席，但该行只能作为已认证 PART 证据，不能单独建立全程零排除。当前 bounded parser 只接受 `PartOut_<block>.obi4` 与 root `Piece=0,Npiece=1`，且自身不认证执行 backend；未来只有经可信身份链证明 CPU 单-piece 的输入才可采用该诊断路径。GPU（即使单-piece）及所有 multi-piece 都保持 `open`/`missing`，直至新增 parser 与 backend 绑定逻辑通过独立审查。

## 4. `T_end`、早停、writer 成功和最终闭环

不为运行终点添加浮点容差；以实际 binary64 值证明最后应用步 `t_before < T_end` 且 `t_after >= T_end`。还须由可信轨迹排除 `TERMINATE` 改写 `TimeMax`、minimum-fluid stop、`NstepsBreak`、restart/append 及其他提前终止路径。若需要判定全程零，最后应用步还必须对应最后一次成功 `SaveData()`，并有匹配的末 PART/计数；没有终端 PART 的零计数不通过。

仅证明 `SaveData()` 进入/返回或 `PartsOut->Clear()` 执行不够：源码先写 RunPARTs 行，再写 BI4/native output，写入并非跨 writer 原子事务；后续 BI4 失败仍可能留下孤立 CSV。未来闭环必须对每个 SaveData attempt 记录并验证所有必需 writer 的成功写入、flush/close 返回与错误状态，证明 `PartsOut->Clear()` 在完整 writer 成功后完成且无 pending event；还须覆盖 `FinishRun()` 在启用 `SDAT_Info` 时追加的 RunPARTs footer。进程退出后再对完整输出集合做 no-follow 稳定重开、长度/SHA-256 复核。任何 writer 错误、异常、关闭状态不可观测、文件集合不完整或 hash/identity 不符，均为 `missing`，不从零计数推断。该证据表示应用层成功闭合，不声称超出已观测文件系统语义的断电耐久性。

若最后一个应用步未触发主 PART 保存，`FinishRun()` 不会补写 `SaveData()`；在没有更晚可信正排除事件时，零排除判定为 `missing`。已认证的正排除事件仍可按 §1 判 `defined_fail`。

## 5. 本地源码锚点和边界

本轮核对的是仓库快照 `c814847dc32926260fb9c7d53340d3b61a5ec6f6`。下列 SHA-256 是当前工作树中对应文件的字节摘要；它们用于可复核绑定，不宣称上游 tag/签名认证：

| Source | Relevant locations | SHA-256 |
|---|---|---|
| `src/source/JSphCpuSingle.cpp` | `Run` 1144-1230（初始/主 SaveData、TimePartNext、早停）；`FinishRun` 1328-1339 | `a261620354e4970f99e8314ddfede1349acef5de236af32e9921af324c021608` |
| `src/source/JSphGpuSingle.cpp` | conditional `SaveFluidOut` 492-520；PART loop 950-1031；`FinishRun` 1144-1155 | `a8652f2422e1c7656f39aaac526c432ed992fc506e48de297410bb36cabe0361` |
| `src/source/JSph.cpp` | RunPARTs 2978-3059；SaveData/SavePartData 3062-3225；`CheckTermination` 3301-3326 | `206e4486a3a0d304e02da1a73d2e7c7ed96354d559ce481275d09f5245b8c9e7` |
| `src/source/JPartOutBi4Save.cpp` | PartOut arrays 191-216；block append/zero-item omission 219-236 | `1712e4c2f08c1be9b0f039beff00b32c1e34fb17dd48c159441c2be28d9856d8` |
| `src/source/JDsPartsOut.cpp` | exclusion motive enum and counts 95-110 | `10bcc9e55c7c5d2cc73688070fdae228dadb1891ba59ca1e77064a7e29aed37f` |

CPU 与 GPU `SaveFluidOut()` 均仅在 `GetNpfOut()!=0` 时调用；GPU source is pinned above only to support that narrow control-flow statement, not to expand this parser's backend domain. `CheckTermination()` 可在保存路径改写 CPU `TimeMax`；源码静态描述不证明任何实际 attempt 已排除该路径。

v6 不改 gate 语义、阈值/单位、15×8 分母、失败分母、观测窗口、mass/`BoundNor` 排除或 full-T1 聚合。`native_state_finite` 仍未定义全 native state/control inventory；wall penetration 与 overlap 仍缺审查过的判据。没有可信 runtime、attempt 或 native-integrity 结果：`native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、qualification credit `0`；不授权 solver、worker、GPU 或 queue。

## 6. Terra High 对 v5 的复核记录

Terra High（`gpt-5.6-terra` / high）只读复核结论为 **REVISE**，未指出直接 false-pass。要求收紧：不可拼接的 attempt/output identity；逐 writer 成功、关闭与错误传播证据；按源码递归迁移推导 PART 调度；可信全零与缺失的确定性状态映射；GPU/`TERMINATE` 的版本化源码锚；PartOut 的 `Cpart`、时间及重复项约束。v6 已逐项纳入。reviewer identity 未 attested；复核只基于提供的提案/源码摘录，未读取文件、调用工具或运行测试。后续复核仍待完成。
