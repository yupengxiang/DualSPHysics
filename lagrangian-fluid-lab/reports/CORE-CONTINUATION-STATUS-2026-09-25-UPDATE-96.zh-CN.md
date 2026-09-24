# Core 计划续推状态 UPDATE-96

日期：2026-09-25（Asia/Shanghai）

## 本次完成：两项只读独立技术审查

两项审查均按用户当前要求配置为 GPT 6 Luna Max，均只读源码、草案、schema 和测试定义。没有独立模型身份/投入强度 attestation；结论是范围内技术审查，不是密码学身份凭据、资格证明或执行授权。

### F8 R008 B/C/D per-case bundle verifier：REVISE

`f8_r008_per_case_bundle_verifier_v1.py` 对 detached manifest、输出树 inventory、no-follow/单链接读取、目录变化检测及 B→C→D receipt 引用做了较强结构校验；但它仍可能在关键阶段语义未核验时输出 `all_stages_passed=true`：

- B 阶段未验证冻结 Definition/control 字节与 case 输入绑定，也未核验 `gencase_execution` 和 `safe_decode_receipt`；相应合成收据字段为空仍可通过。
- C 阶段虽要求 `solver_execution` 与 `execution_controls` 字段存在，实际未按其语义校验；空对象可以随合成链通过，`status="passed"` 未绑定退出码、超时/信号、资源使用及进程树终止/清理事实。
- D 阶段只闭合 native-fluid table 的文件路径、大小和 SHA-256，没有验证 HDF5 schema、shape/dtype、完整时间/ID 轴或逐帧值与 C 原始 BI4、D 解码产物的对应关系。
- 非 `passed` 的 C attempt 仍被无条件要求完整预期帧轴，无法按已登记分母保留自然产生的 partial/failed attempt。

因此 v1 的结构性闭合不能被消费者解释为 solver execution 或 D table 内容已验证。caller 提供的授权字节、one-shot 独占创建、review 身份及 loaded-runtime identity 仍是外部前提；review helper 内的常量 PASS 不能认证 reviewer。详情见本轮静态复核摘要与源码定位：`f8_r008_per_case_bundle_verifier_v1.py` 的 B/C/D 分支、`test_f8_r008_per_case_bundle_verifier_v1.py` 的空语义字段合成夹具，以及 `f8_r008_per_case_provenance_implementation_review_v2.py`。

### V12 synthetic harness 与 C-execution V4：REVISE

新草案对摘要分层、递归 projection schema、KnownInputs 重算、query journal、XML raw slice 和 PID generation 有实质补充，但仍有以下高优先级缺口：

1. V12 §1/§3 未规定 batch decision capability 与 preparation capability 必须引用同一份 qualification admission 原始对象；`qualification_receipt_sha256` 还混淆完整 envelope、binding admission、evaluation admission 与 evaluator raw result，可能导致资格来源可错配或合法产物被拒。
2. C-execution V4 的 query poll/loop-guard 仅要求 process generation 出现在同 attempt 的 process journal，未把该 generation 约束为 invocation 所绑定的 solver root/合规子进程，也未绑定每个 query 事件到该 generation 的存活时间区间。
3. V12 的 descriptor-root/no-follow 设计未要求核验后继续使用同一 FD 或不可变 snapshot。当前 dataset reader 可先按 path 校验、之后重新按 path 打开，存在检查后替换路径目标的 TOCTOU。
4. planner projection 只检查 HDF5 SHA 字段格式，而不在 `launch_allowed` 前由受信 case-audit capability 绑定实际 HDF5 内容；后续 dataset reader 检查不能倒推为 planner 时已验证。
5. V4 的 cache-hit 指向历史同时间 miss 仍不够；需按 generation、instance、entry 与 poll 顺序重算单槽 `LastTimestepInput` 状态，证明引用的 miss 在 hit 时仍是 cache 当前值。

现有 `prepare_production_batch`、collector 与 formal planner 尚未实现 V12 所描述的 admission producer/verifier/capability；这些拒绝行为仅存在于草案，并非已生效实现。后续应先修订 V12/C-v4 规范，再实现和测试独立的新版本，不得把结构 PASS、synthetic-only PASS 或 descriptor hash 等同于 producer/runtime trust。

## 状态边界与后续工作

- 这轮没有改写任何冻结证据或 one-shot receipt，没有读取生产 bundle/solver frame，没有运行测试、planner/collector/preparation、GenCase/native/solver/worker/GPU/queue。
- F8 `T1_numerical=false`、`readiness_pass=false`、资格信用为零；15-case T1 结果仍未生成。F3 row30 与 F4 supportcap 的已消费一次性预检没有重试。
- 可直接推进的下一项：新增 V13/V5 只读设计修订，固定 qualification 原始对象身份与各层 digest 名称、验证/消费同 FD 或 snapshot、planner launch gate 的 HDF5 绑定，以及 solver query-event ↔ process-generation ↔ invocation 的因果和生命周期约束；同时明确 per-case v1 仅作结构检查，或以新版本 fail-closed 取代其“全阶段已通过”表述。
- C V4/V5 仍是 synthetic-only 合同工作；可信 supervisor、event source、source-to-loaded-binary/runtime closure 与 out-of-band trust activation 没有实现前，production execution gate 必须保持关闭。
