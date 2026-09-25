# UPDATE-165：F8 R008 synthetic PartOut/RunPARTs 诊断解析器

时间：2026-09-26（Asia/Shanghai）

## 实现范围

新增 `scripts/f8_r008_partout_runparts_diagnostic_v1.py` 与对应 synthetic 测试。解析器接收 RunPARTs 原始 CSV bytes 和调用方已持有的 PartOut 文件描述符，不解析路径、不读取生产目录；它复用 SAFE BI4 scanner 的单 item 低层解析器，在新模块内逐个解析 JBinaryData 顶层记录，未修改 source-hash 绑定的 `f8_r008_safe_bi4_decoder_v1.py`。

解析合同覆盖：

- RunPARTs v2 的原始结构与全部数值字段；每个 PART 均核对 `NpOut == NpOutPos + NpOutRho + NpOutMov`。
- PartOut `JPartOutBi4` header、根项、CPU 单 piece 的 `Piece=0/Npiece=1/Block` 与文件名对应、block 从 0 连续，以及追加 PART 项的递增次序和 `Cpart`/项名一致性。
- 当前 R008 CPU 源的 `JSph::SavePartData()` 明确传入 `GetIdpOut(), NULL`，因此只接受 `Idp` uint32；通用 writer 支持但该路径未产生的 `Idpd` uint64 fail-closed。位置数组恰为 `Pos` 或 `Posd`，并严格校验 `Vel`、`Rhop`、`Motive` 五数组、类型、长度与 `Nout`。
- 非零排除记录逐 PART 对齐；ID 数量/唯一性及 Motive 1/2/3 直方图分别对账三类 RunPARTs 原因计数。零计数 PART 不允许多余 payload；PartOut 文件缺失不作零事件证明。
- 每个 BI4 文件最大 64 MiB、所有 PartOut 输入合计最大 256 MiB、最多 128 个连续 block、PART 数受 RunPARTs v2 行数上限约束；读取前后复核 SHA-256 和 FD 身份/稳定性。多 piece 格式不在该版本支持范围。

输出严格只有诊断状态：结构一致时 `excluded_fluid_particles_zero=open`；输入缺失或不一致时为 `missing`。即便合成计数显示非零，也不推导真实 gate `defined_fail`；任何路径均不能给出 `defined_pass`、gate decision eligibility、T1/readiness 或资格信用。原始 RunPARTs SHA 与每个 PartOut 文件 SHA 仅作未认证输入绑定。

## 复核与验证

Terra High（`gpt-5.6-terra`, high）首轮提出 1 项 P2：uint64 `Idpd` 不属于当前 R008 CPU `SavePartData()` 调用路径。实现已收窄到 `Idp` uint32 并增加 Idpd 负测；同时撤回了对旧 SAFE decoder 文件的实验性修改，避免使依赖其固定 source hash 的 verifier 按设计 fail-closed。follow-up 复核 **PASS，无 P0–P3**，并确认没有未认证输入进入 gate pass/fail。

验证结果：新诊断专项 **16 passed**；SAFE BI4 与 RunPARTs 定向回归 **59 passed**；包括 native-fluid/state、bundle verifier、SAFE BI4 metadata/review consumers 在内的相邻联合套件 **146 passed**。`py_compile`、`git diff --check` 通过。所有 PartOut fixture 均由测试现场合成，无生产 bundle/frame 输入。

Core completion status 仍为 `can_finalize=false`：T1 家族 2/3、宏观 T2 0/2、正式训练 0/9、固定目标 T1 case-run 缺 432、材料 case-run 缺 288，异机独立复现未通过；结构/因果证据检查仍通过且 `issues=[]`。本增量未改 registry、ledger、分母或资格状态。

没有运行 GenCase、native decoder binary、solver、worker、GPU 或 queue；没有生产输出模式、执行身份、`T_end` 覆盖或最终 flush 证据。因此 parser 仅实现 UPDATE-164/v4 允许的 synthetic diagnostic 子步骤，不构成 native-integrity gate 实现/判定，也不扩大任何执行授权。
