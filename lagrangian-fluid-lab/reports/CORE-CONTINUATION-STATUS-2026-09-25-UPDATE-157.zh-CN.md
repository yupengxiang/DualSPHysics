# UPDATE-157：F8 R008 timestep 源码语义审计

时间：2026-09-25（Asia/Shanghai）

## 结果

新增 F8 R008 源码语义诊断脚本与对抗性测试。它核验冻结 Definition/control pack 的 47 个定义（15 qualification、32 production），并按 C++ 函数检查配置覆盖、CPU timestep、RunPARTs 和运行终止路径。审计结论只针对所读源码文本及 `standard_cpu_single` 路径；没有认证源码来源、编译产物或实际运行身份。

主要发现：

- 47 个冻结 Definition 都没有显式 `StepAlgorithm`。XML 默认值是 Verlet，但后续 runtime config 和命令行可覆盖算法；`-CFL`、`-TMAX`、`-TOUT`、`-NSTEPS` 也能改变运行控制。仅凭 Definition 默认值无法认定有效 runtime 算法或控制值。
- 在被审计的 CPU single 路径中，Verlet 的 `DtVariable(true)` 所记 `PartDtMax` 来自随后传给 `ComputeVerlet(dt)` 的同一 `dt`。Symplectic 实际应用前一步 `SymplecticDtPre`，而 `PartDtMax` 记录 corrector 候选 `dt_c`，不能当作该步实际采用的最大 timestep。
- `RunPARTs.csv` footer 可在 `SDAT_Info` 开启且文件 append 时由 `FinishRun` 写出；它本身不证明完整正常完成。`NstepsBreak` 能早于 `TimeMax` 退出；minimum-fluid stop 会改写 `TimeMax`。CPU 主循环保存调用链最终进入 `JSph::CheckTermination()`，变化的 `TERMINATE` 文件也可能改写 CPU `TimeMax` 并产生 warning。
- 审计已绑定 CPU 主循环保存分支、派生 `SaveData`、基类 `SaveData` 与 `CheckTermination`；对关键配置/积分器语句检查函数作用域、直接语句、变量声明和分支嵌套。条件编译锚点和 C++ 反斜杠续行均 fail-closed；检查器不是 AST/CFG，也不验证编译 flags 或运行二进制。
- 增加机器可读的 runtime completion evidence 字段及 tolerance 公式。诊断 helper 只返回 `conditions_satisfied_untrusted`，不发出 accepted/资格判定；容差 hash、backend 声明和运行证据仍须由可信来源验证。

脚本与测试 SHA-256：

- `f8_r008_timestep_source_semantics_v1.py`：`28921a019ed2f8056c8ab549ad06f6b3a0643bc487b4cbe25426e48887795cae`
- `test_f8_r008_timestep_source_semantics_v1.py`：`91aae968431e0a5943d0965bcaa3a24462d2663f8c42313f9ff71a8953521fc3`

验证结果：源码语义审计测试 39 passed；与 RunPARTs parser、metric adapter、matrix review 和 readiness v6 的联合回归 192 passed；`py_compile` 与 `git diff --check` 通过。Terra High（gpt-5.6-terra/high 配置）的只读对抗性 follow-up 确认 `TERMINATE` 分支绑定已修复，并同意将此变更作为“不发布 receipt”的静态审计实现保留/提交；该 reviewer 结果没有密码学模型身份 attestation。

## 收据与权限边界

没有生成或声称存在 JSON receipt。目标目录的现有祖先均为 `775 jade:jade`，组可写；writer 因路径不安全而 fail-closed。没有 chmod、sudo/root 操作或其他权限变更。匿名 inode 发布只提供原子不覆盖，不防御恶意同 UID 修改；不把它称为不可变存储。若后续要求此类收据，需要另行提供受保护的 append-only 存储或独立发布身份。

## 门槛状态

没有启动 solver、worker、GPU 或 queue，也未改 registry、ledger、分母或资格。运行 backend/source identity、15-case 可信运行证据、native integrity 与真实 timestep adjudication 仍未闭合；T1、readiness 和 qualification credit 均保持 false/0。F8 R008 readiness v6 未被本次静态诊断升级或重写，Core 完成状态不变。
