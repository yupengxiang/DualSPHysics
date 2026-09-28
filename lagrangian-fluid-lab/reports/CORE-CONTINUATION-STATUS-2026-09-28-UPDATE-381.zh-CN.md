# Core continuation status — UPDATE-381

日期：2026-09-28（Asia/Shanghai）

## MLP terminal runtime verifier

新增 F3 `mlp` / hidden16 full835 terminal runtime verifier V1，提交为
`c463d946`。它与 residual verifier 分文件、分 schema、分报告，读取边界只允许
有界 JSON：

- 三 seed MLP training-evidence matrix；
- 三 seed full835 rollout diagnostic summary；
- 每个 seed evaluator 与 launcher 均已退出且 return code 为零的 exit proof，
  并绑定固定 32-hex fresh namespace；
- 每个 seed 的独立 HDF5 validator receipt。

所有正向字段必须交叉绑定到 MLP、hidden16、500 updates、固定 F3 test case、835
transitions/836 frames、training/checkpoint/evaluation/trajectory/validator 的
path/SHA/bytes 及 manifest identity。未知字段和别名、重复 JSON key、NaN/Infinity、
越界路径、symlink/hardlink、身份漂移和缺失证据均 fail-closed。

## 当前状态与边界

已有 MLP full835 summary 与 validator JSON 可读，但没有独立 process-exit proof，
所以默认机器回执为：

```text
status=blocked_fail_closed
source_bound=false
independently_terminal_verified=false
formal/T1/T2/qualification=false
credit=0
```

verifier 不打开大 evaluation、progress、manifest、checkpoint、trajectory 或
HDF5 内容，不启动/控制 GPU、solver、worker、queue，不写 registry、ledger、
denominator、gate 或 completion。专项测试 `11 passed`，py_compile 与
`git diff --check` 通过。该 diagnostic verifier 即使未来闭合，也不产生 Core
正式训练、T1/T2 或资格信用。
