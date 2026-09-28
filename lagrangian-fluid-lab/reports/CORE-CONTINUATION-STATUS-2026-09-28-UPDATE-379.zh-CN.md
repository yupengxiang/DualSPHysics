# Core continuation status — UPDATE-379

日期：2026-09-28（Asia/Shanghai）

## 本轮完成

完成 F3 `graph_residual` / hidden16 full835 终态 runtime verifier V1，提交为
`50696b9b`。这是对既有 receipt-only terminal matrix 的加性独立核验层，不替换
旧矩阵，也不修改历史回执。

每个 seed 必须同时提供以下四类 bounded JSON 证据：

1. receipt-only terminal matrix；
2. evaluator 与 launcher 均已退出且 return code 为零的 process-exit proof；
3. 与 training/checkpoint/manifest 绑定的 evaluation identity；
4. 独立 HDF5 validator 的完整 835-transition/836-frame receipt。

verifier 对三 seed 的 run/config/case/split、唯一 fresh 32-hex nonce，以及
manifest、training receipt、checkpoint、trajectory、evaluation 的 path/SHA/bytes
做交叉一致性检查。未知字段、伪造 PID/formal/credit 别名、重复键、非有限值、
路径逃逸、身份漂移和任意缺失都 fail-closed。

## 边界与当前状态

实现只读取有界 JSON envelope；不打开 HDF5、trajectory、checkpoint、evaluation、
progress、manifest 或 solver 文件，不启动或控制 worker/GPU/queue，不写 registry、
ledger、denominator、gate 或 completion。正向结果仍明确为 diagnostic-only、zero-credit。

默认机器回执当前为：

```text
status=blocked_fail_closed
source_bound=false
independently_terminal_verified=false
formal/T1/T2/qualification=false
credit=0
```

专项测试 `26 passed`，`py_compile` 与 `git diff --check` 通过。只有真实终态
rollout 的四类证据全部闭合后，才能重新运行该 verifier；即使闭合，也不会把
diagnostic rollout 计入 Core 正式训练、T1/T2 或资格分母。
