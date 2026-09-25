# UPDATE-161：F8 R008 十五案例诊断组合适配器 v5

时间：2026-09-26（Asia/Shanghai）

## 本轮实现

新增 `scripts/f8_r008_t1_metric_matrix_adapter_v5.py`，要求输入严格对应冻结的 15 个 case，并在本层直接调用 matrix-v4；不接受调用方序列化的 v4 结果或逐案例诊断。对全部 15 行重新解析原始 RunPARTs 字节、StepAlgorithm 声明和 runtime claims。每行的 RunPARTs observation 都精确检查 v2 schema、fresh-single-segment scope、26 列校验标志、原始字节数/SHA、DtMax 和必要解析字段。

冻结 baseline/refined pair 的 RunPARTs 原始字节数和 SHA 必须与 v4 安全解析回执一致，DtMax 必须同时匹配 v4 与逐案例重算；pair 相位只取自本次 v4 直接重算。v4 status 被固定到诊断态；case-result binding 只接受四个既定摘要字段，其中 receipt/manifest 分别严格校验 B/C/D 三键和 SHA-256，并显式投影，禁止透传任意嵌套成功或资格字段。runtime horizon 对齐 tolerance 由原始 claims 在本层重算并精确比对上游诊断值，然后再与冻结行 `observation_end_s` 比较；这些仍只是未认证 caller claims。

首次实现严格 binding 白名单时，合成回归显示 v4 实际 receipt/manifest digest 是 B/C/D 嵌套映射；据实际 v4 结构修正为递归 exact-schema 校验和窄投影，并加入 nested `passed`、v4 status、RunPARTs parser 契约和 tolerance 漂移负测。

所有输入/来源认证、执行 identity、runtime 配置、有效积分器、native integrity、正常完成、solver timestep、T1 和 readiness 仍为 `False`，`qualification_credit=0`；不输出 `passed`。不发布 receipt，不改 registry、ledger 或分母。

## 独立审查与验证

- Terra High（`gpt-5.6-terra`, max）初轮只读审查要求修复 v4 status/binding 投影、15 行 parser-contract 校验及 tolerance 重绑定；本地完成修复后 follow-up **PASS**，无 P0–P3。审查只读，reviewer 未运行测试，也无密码学模型身份 attestation。
- v5 新增专项合成回归：**27 passed**。
- 五组相邻 F8 parser/adjudicator/matrix/review 回归：**141 passed**。
- `py_compile` 通过。所有 RunPARTs 仅为临时合成字节；未读取生产 bundle/RunPARTs/frame，未运行 GenCase、native decoder、solver、worker、GPU 或 queue。

实现 SHA-256：

- `f8_r008_t1_metric_matrix_adapter_v5.py`：`70090188594d2903f754ec51e1747fc36bfe17533d7f33a0512c53b599030f3e`
- `test_f8_r008_t1_metric_matrix_adapter_v5.py`：`01f63650d3cf58709aab85970b9ea7034f2694e294003ce4264aa5feb31683a5`

## 计划状态

本轮把现有 matrix-v4、逐案例 runtime/timestep 诊断与冻结 pair diagnostic 组合到 15 行的静态诊断层，不构成 provenance-verified 的 solver-result matrix。F8 readiness v6 的可信 worker/source/supervisor 与 loaded-module/runtime identity、真实来源验证的 15-case solver 结果、native-integrity 与有效 timestep/完整终止裁定仍未完成；T1、readiness 和资格信用不变。
