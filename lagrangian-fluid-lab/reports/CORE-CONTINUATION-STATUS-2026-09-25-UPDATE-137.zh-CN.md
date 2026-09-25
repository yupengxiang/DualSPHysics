# Core 计划续推状态 UPDATE-137

## 本次推进：F8 R008 逐案例 attempt evidence 绑定

新增 `f8_r008_attempt_evidence_binding_v1.py`，将冻结的 15 行 qualification matrix、caller-supplied attempt ledger、逐 attempt V2 投影及 B/C/D receipt envelope 接入同一只读诊断路径。它核对每个 ledger ref 对应的 receipt identity、raw SHA-256 和 status claim，并要求 receipt envelope inventory 与全部 attempt 投影精确闭合。ledger aggregate 仍保留完整注册历史与重试次序；开放 attempt 和无 receipt 的非 `not_run` status 会显式计数，不会被说成已绑定。

aggregate 的 attempt-result 字节预算改为增量计数并在超限时停止；V2 投影为 event-seq 列表及时间十六进制字符串加固定上限。集成测试覆盖 status 不匹配拒绝、未引用 failure status、开放/未启动 attempt，以及同一案例 retry 顺序和分母保留。

定向跨模块回归 **296 passed**（attempt ledger、V2 projection、C V5 journal、原 stage verifier、native-fluid-table verifier/metric adapter）；相关文件 `py_compile` 与 `git diff --check` 均通过。只使用合成输入，没有访问或启动 worker、GenCase/native decoder、solver、GPU 或 queue。

本 API 只证明调用者提供的对象之间有界的结构和字节一致性；receipt 内容仍是不可信 status claim，不认证 descriptor root、producer、supervisor、runtime 或真实执行语义。15 行与所有 attempt 仍为 `unresolved`，`T1_numerical=false`、资格信用为 0。Core 的 T1/T2、训练、完整逐案例来源证据与异机复现仍未完成。
