# F8 R008 逐案例来源验证设计提案 v2（2026-09-24）

状态：v1 经 Terra High 只读审查为 `REVISE`；本稿逐项回应其五条发现，待 follow-up review。本文只冻结后续静态设计边界，不实现验证器、不生成运行回执，也不授权或启动 GenCase、native decoder、solver、worker、GPU 或 queue。

## 1. 当前实现能证明什么、不能证明什么

readiness audit v4 只信任已固定哈希的 anchor CPU/native preflight。`verify_gencase_receipt()` 拒绝其他 per-case schema。当前 `NativeFluidTable` 只保存 Definition、GenCase receipt、scope/parameter 和写出 HDF5 的绑定；`build_native_fluid_table()` 接收内存 frames 时，没有证明它们来自哪次 solver attempt 或 native decode。`evaluate_metric_matrix()` 会重读 HDF5 并复核现有 provenance，但不能从中恢复 raw solver 输出的来源。因此 v1 table 和当前 matrix result 均不得升级为未来 qualification 数据。

静态代码可见 `core_cfd.native_frame()` 将 `.bi4` 交给 `bi4_dump`，并读取 decoder 输出的 metadata、`Idp.bin`、`Posd.bin`（若缺失则退至 `Pos.bin`）、`Vel.bin`、`Rhop.bin`；metadata 中含 `TimeStep`，当前 converter 再按 ID 排序。此处只说明当前代码路径，不等于已经冻结 vendor decoder 的文件布局、端序、完整输出清单或语义。reviewer 未运行/反向工程 decoder；这些格式细节在下一阶段静态核验前必须标为未决，不能猜测。

## 2. 分层证据合同

### A. 启动前 admission 与授权

启动前检查独立于事后 receipt verifier。admission 必须核对 exact case、独立的 per-case authority、资源门及新鲜目标；尚未存在的输出目录/lock 必须保持空，随后由固定 executor 以 exclusive create 建立 one-shot lock，再允许授权范围内的阶段开始。admission 被阻塞时不能创建 lock 或触碰 native tool。

R008 当前只有已消费的单-anchor CPU/native preflight authorization；它不能扩展到另外 14 行，更不含 solver/T1 authorization。每个未来 attempt 都要新的、明确授权的 scope/resource gate；本设计和 verifier PASS 均不产生该授权。

### B. 事后 input-materialization receipt

成功的事后 verifier 应要求目标目录**存在且已消费**，而不是把成功输出当作冲突。它只读校验：

- receipt、同一 case 的 prelaunch one-shot lock 和独立授权绑定同一 `attempt_id` / nonce、scope、case、受限 output root；lock 创建早于两个 native stage，且 invocation budget 恰为 1。目标目录在 admission 阶段为空的证明来自 executor 的 prelaunch record，不由事后路径“不存在”检查代替。
- 输出目录在授权 root 下，路径解析不逃逸；路径各级不得为 symlink，receipt 所列对象必须为普通文件。逐文件通过 no-follow open、`fstat` 和内容哈希核验；读前后重新核对 inode/size 等元数据以检测并发替换。manifest 与允许的输出集合精确相等，拒绝未登记额外文件、缺失文件或覆盖 lock。SHA-256 是完整性绑定，不是签名或可信身份认证。
- case 输入不仅匹配 `case_id`。从 frozen 15-row scope 和 definition-control pack 读取唯一 row；Definition/control 的 canonical path、byte count、SHA-256 均相等。解析 Definition 中 `./execution/special/accinputs/accinput/acctimesfile`，它必须引用同目录、receipt 绑定的 control CSV。调用已 hash-bound 的 `f8_r008_definition_control_pack_v1.validate_case(row, definition_bytes, control_bytes, control_name)`，或经独立等价实现核验：`cflnumber`、`dp`、`TimeMax`、`TimeOut`、physics/boundary 常数、CSV 七列 header、控制 T/64 网格、行数、正弦幅值/相位、零侧向/角加速度及精确终点均与冻结 row 相符。这样显式区分普通 64 点输出、CFL 0.1 控制、128 点 cadence 控制，不能用同名 case 替代控制合同。
- 每个 CPU native 阶段固定 executable 与 wrapper 哈希和精确 argv；receipt 绑定子进程 argv/return code、cgroup cap/peak/events、超时/信号、clean process-tree 及 logs。任一 hash/资源/返回码/清理门失败，整例 provenance verification 失败；不得把回执的 `passed`、粒子数或零信用自述作为证据。
- `generated XML`、BI4、Bound/Fluid/hdp VTK、native-initial 文件及 XML/metadata 必须按其冻结格式逐项清单化，分别记录路径、bytes、SHA、类型、shape/dtype（适用时）。重算 particle cohort/count、fluid/nonfluid 完整互斥 ID 集、几何/边界/法向硬门；不得仅信任 executor 的布尔摘要。

此层只证明 frozen 输入的一次 CPU/native materialization；不证明 solver 轨迹、T1 或任何资格信用。

### C. 单案例 solver-attempt receipt

单独的后续层才可记 solver。每份 attempt receipt 绑定 B 层已验证 receipt、独立 solver authority、exact Definition/control/全部参数、solver executable 与 argv、一次性 lock、实际资源封套、进程树/终态、logs 和不可覆盖的原始输出。失败、OOM、timeout、异常退出或不完整窗口都是保留在预登记分母中的 attempt；不能同 namespace 重试，也不能把失败 receipt 当缺失样本丢弃。

receipt 必须有原始输出 manifest：每个文件的 canonical relative path、frame/output ordinal、声明物理时间、bytes、SHA-256、普通文件属性。manifest 集合必须精确等于 solver 原生目录中的预登记输出清单，缺少、额外、重复 ordinal/time、软/硬链接替代、路径逃逸或运行后变化均 fail-closed。solver full run 的 authority/resource gate 不属于本提案当前允许动作。

### D. Native decode 与 table provenance receipt

本层必须将 C 层每个原始 solver output 映射到 decoder 的一个确定结果，并保留完整 `t=0..TimeMax` 的原生输出时间轴；不能只给选定观察窗。冻结的 decoder manifest 至少包括：decoder executable/代码哈希、精确 argv、输入 BI4 manifest、输出目录 manifest、XML/metadata 解析合同、逐输出 `TimeStep` 映射，以及 canonical frame 编码规则。每帧分别记录 `time_s`、raw ID/position/velocity/density（及表转换实际用到的其他量）的 shape、明确端序/dtype、文件或 canonical-array SHA-256；重复/漏帧、时间不单调或偏离冻结 cadence、raw ID 集不等于该 case generated XML 的精确 fluid+registered-nonfluid 并集、非有限值或质量漂移均拒绝。

fluid-only HDF5 table 需用新 provenance/table schema（至少 v2），绑定 B/C 层 receipts、原始 solver 文件 manifest、decoder 输入—输出 manifest、converter 代码 hash、完整原始时间轴和最终 table hash。其时间轴与原始 canonical frames 必须逐行一致、不得插值/合成/裁切；metric 窗口只是由冻结 `observation_start/end` 在完整轴上选择的闭区间，frame index/time 列表必须与 observation-window parser 重算一致。table ID 轴按 canonical frozen fluid IDs 排序；raw frame 的行顺序可不同，但必须逐 ID 对齐，不得丢弃未知 raw IDs 后再声称输入完备。

**尚未冻结的静态前置条件**：上面逐帧 binary dtype/endian、decoder 元数据字段和预期输出集合，必须用已存在 anchor 产物、官方/本地 decoder 文档及 `core_cfd.native_frame()` 源码作只读交叉核验。当前可见源码不足以证明所有 BI4/solver 输出变体；若证据不够，新增 R008 专用 decoder adapter/schema 并独立审查，而不是运行工具探测或沿用隐式 `Pos.bin` fallback。

### E. 新版 metric adapter 与 T1 adjudication

实现时新增版本化 adapter/table schema；旧 v1 tables、旧 GenCase-only provenance、synthetic tables 和缺少 B/C/D 链的结果必须在 qualification matrix 入口显式拒绝，不能迁移/回填成 v2 PASS。新 adapter 只从 15 个 frozen qualification rows 的 B/C/D 验证链读取数据，重读原始 manifest 和 HDF5，逐行重算 metrics。

来源验证 PASS 不等于 native integrity gate PASS，也不等于 T1。当前 `evaluate_metric_matrix()` 即使完成 15 行指标与比较，仍明确输出 `native_integrity_gates_evaluated=false`、`full_t1_decision=false`、zero credit。最终单独的 T1 adjudicator 必须对 15 行逐行核实完整原生窗口/identity/finite/mass/integrity 门，重算全部指标、8 个空间比较、CFL/time-step comparison 和 native-cadence comparison；所有预登记硬门通过且符合单独的执行/qualification authority 后才可能给 T1 决定。现有 adapter v1、静态 verifier PASS、单行/anchor/preflight 结果始终为 0 credit。

## 3. 接纳集合、失败策略与边界

- 只接纳 frozen R008 T1 scope receipt 中恰好 15 个 `qualification_only=true` rows。32 个 production rows、R001/R002/R007 历史资产、其他 scope 均拒绝。
- 启动前 admission 要求全新空 namespace；事后 receipt verifier 要求该 namespace 和成功/失败 one-shot lock 已存在，并按 lock/auth/output manifest 闭合验证。两阶段不可共用一个“namespace must be absent”谓词。
- 所有验证只读。除独立授权的未来 native attempt 外，不得创建目录、运行工具、写 registry/ledger/queue、改分母。失败 attempt 永远不能由 adapter 筛掉。
- 哈希可以检测内容漂移，但不能证明签名身份、历史时钟可信或对抗有工作区写权限的恶意主体；需要更强 threat model 时须另做签名/可信归档评审。
- 不接纳旧 table schema；旧回执保留历史，不覆盖、不伪造重签。审计版本升级应继续显示 `readiness_pass=false` 和 zero credit，直到真实 15-row 原始结果链与完整 T1 adjudication 都具备。

## 4. 静态审查与实现顺序

1. Terra High follow-up 只读复核本 v2，尤其是两阶段 one-shot、CSV/Definition 对应、raw output/decoded frame manifest、adapter v2 rejection 与 T1 完整门界限。
2. 完成 decoder binary format 的只读证据审计；若无法冻结，明确保持该项 open，不做 runtime probe。
3. 机器可读地冻结 B/C/D schemas 和负例测试；合成正例只用 temporary files。实现只读 verifier 与新版 adapter，不创建 campaign runtime namespace。
4. 重新独立审查 schema、实现、tests 和 immutable audit；review PASS 不授予任何运行 authority。以后若需要 F8 per-case native/solver attempt，仍须独立资源 admission 和明确的单次执行授权。

本 v2 仅是方案修订；不修改 R008 physics、15-row scope、阈值、失败分母或既有回执，也不重开 F8 R001/R002。没有读取/调用 decoder executable、GenCase、solver、worker、GPU 或 queue。
