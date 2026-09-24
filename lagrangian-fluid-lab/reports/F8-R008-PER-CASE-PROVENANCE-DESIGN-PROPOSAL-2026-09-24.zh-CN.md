# F8 R008 逐案例材料化与结果来源验证器设计提案（2026-09-24）

状态：静态设计提案，待 Terra High 只读审查。本文不实现验证器、不生成运行回执，也不授权或启动任何 native tool、solver、worker、GPU 或 queue。

## 目的与当前缺口

当前 readiness audit v4 只信任已存在的 anchor CPU/native preflight。`scripts/f8_r008_t1_metric_adapter_v1.py::verify_gencase_receipt` 对该 anchor 做固定哈希和结构检查；其他 per-case schema 一律 fail-closed。v4 因此保留 `reviewed_per_case_materialization_verifier_missing`，并明确没有可验证的完整 15-row T1 结果。

静态阅读还发现一个不能被“GenCase receipt 已验证”掩盖的来源缺口：`build_native_fluid_table` 接收内存中的 decoded frames，但没有绑定这些数组来自哪次 solver output 或 native decoder；当前表 provenance 主要绑定 frozen Definition、GenCase receipt、R008 scope/parameter contract 和写出的 HDF5 本身。未来即使有一个 per-case GenCase verifier，也不能仅凭它将 solver 轨迹称为 provenance-verified。

## 建议分离的证据层

1. **Case input materialization receipt**：只证明精确 R008 qualification case 的 frozen Definition/control，经单次受限 GenCase 与 native initial decode 后生成了可核验输入。绑定 case row、Definition/control 哈希、逐阶段 argv/可执行文件/runner、scope 与资源指标、one-shot lock，以及所有要求的 XML、BI4、VTK 和 native initial arrays 文件哈希。其 verifier 只读，绝不调用工具。
2. **Solver attempt receipt**：将一次单案例 solver attempt 绑定到第 1 层的 receipt、完全相同的 Definition/control、solver 可执行文件/参数/二进制和资源封套，记录一次性锁、退出状态、超时/信号/OOM、完整进程树清理、日志及每个原生输出文件的哈希。任何重试必须是新的、独立授权的 attempt，不得覆盖或复用失败输出。
3. **Native decode/table receipt**：绑定第 2 层输出文件、decoder 二进制/代码和 argv、解码出的完整时间轴及 raw ID universe，再绑定 fluid-only HDF5 table、转换代码哈希和 schema。table reader 必须重读原始绑定，逐帧验证 generated-XML 导出的 fluid/nonfluid ID 并集、唯一性、有限坐标/速度、正质量及按 ID 质量恒定；未知、丢失、重复 identity fail-closed；raw frame 行可任意排列，但投影后的 HDF5 ID 轴必须等于冻结的 canonical fluid ID 顺序。
4. **Metric adjudication**：现有 adapter 只消费上述三层都通过的 15 个 frozen qualification rows，重读 table 与 provenance，从原生数据重算全部指标和 8 项比较。只有 15 行和所有预登记硬门都满足后才允许给 T1 结论；preflight、单行通过或 synthetic test 均保持零资格信用。

各层 receipt schema 和 verifier 应各自版本化。输入材料化不是 solver 结果，solver attempt receipt 不是资格结论，native decode/table receipt 不是原始 solver provenance 的替代物。

## 关键 verifier 不变量

- 只接受 `t1-scope-design-v1/receipt.json` 中精确的 15 个 `qualification_only=true` case ID；32 个 production rows、R001/R002/R007 历史产物和其他 scope 均不在此 verifier 的接纳集合。
- 每个 case 必须与 `definition-control-pack-v1/receipt.json` 中同一 row 的 Definition、control、参数值和比较关系逐字节/逐字段一致；不接受调用方覆盖几何、dt、输出 cadence、路径或预登记指标。
- receipt 只能引用同一 case 的一个新鲜且受限的 output namespace；校验解析后的路径在授权 root 下、无 symlink/路径逃逸，并拒绝已存在或已消费的 one-shot 目标。verifier 本身不创建该目录。
- 所有可执行阶段必须绑定精确的官方 binary、审查过的 wrapper/decoder、固定 argv、CPU-only 资源封套和每阶段的 clean process-tree/timeout/OOM 证据。任一阶段缺字段、hash 漂移、非零返回、cap pressure、OOM、超时或残留进程均拒绝整例。
- 所有输入/输出文件必须同时绑定 canonical path、byte count 和 SHA-256；还需校验 receipt 中状态/控制字段与实际阶段证据一致，不能接受自我声称的 `passed`、零信用或粒子数。
- 成功结果只表示该层来源链可复核。所有 receipts 仍保留 `qualification_credit=0`；verifier 不写 registry、ledger、分母、job queue 或运行目录。
- 本地 hash receipt 不能证明签名身份或抵御拥有工作区写权限的恶意伪造者。若威胁模型需要签名/可信执行身份，应单独评审密钥、签名和归档边界，不把 SHA-256 自身描述为签名。

## 静态实施与审查顺序

1. Terra High 只读审查本提案，重点检查三层 provenance 是否完整、one-shot/authority 分离、路径与资源边界、以及现有 adapter 是否必须升级 schema。
2. 按审查意见冻结机器可读合同和 fail-closed verifier 的单元测试；正例只能使用临时合成文件，禁止运行 GenCase/native decoder/solver。
3. 验证 adapter 对无 solver-source binding 的旧式 table 仍拒绝进入矩阵资格 adjudication；必要时提升 adapter/table schema 版本，不回写旧 receipt。
4. 独立复核 verifier、receipt schema、测试与静态哈希闭合后，更新只读 readiness audit。没有任何 runtime 授权随设计或 verifier PASS 自动产生。

本提案不更改 R008 冻结矩阵、阈值、physics、失败分母或既有回执；不修复/覆盖 anchor preflight，也不把 F8 R001/R002 重新打开。
