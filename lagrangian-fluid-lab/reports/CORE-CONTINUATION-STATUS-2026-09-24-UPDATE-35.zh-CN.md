# Core continuation status — 2026-09-24 UPDATE-35

## Outcome

本轮继续推进 F8 R008 的静态实现，新增两个 additive v2 层：

- [native-fluid-table producer](../scripts/f8_r008_native_fluid_table_producer_v2.py)：接受 held output-directory FD、冻结 table 属性/时间轴/流体 ID/CaseNp/MassFluid 和由调用方提供的 raw-frame factory。它逐帧流式构建精确 v2 HDF5 表；临时表初始 `conversion_complete=false`，全部行落盘后才更新为 true，随后使用独立 table-v2 语义 verifier 对第二遍 source stream 全量重算。只有语义验证和 inode/hash 复核通过后，才用同目录 no-replace hard-link 发布最终 basename。已存在目标不覆盖；异常清理按 inode 身份执行。
- [15-case matrix adapter](../scripts/f8_r008_t1_metric_matrix_adapter_v2.py)：消费 held-FD B/C/D v2 verifier 的逐案例零信用输出摘要，严格要求冻结的 15 个 case 全部出现；校验逐案例指标及 table/review/status/hash 绑定，再运行 8 项跨分辨率、solver timestep 和 cadence 比较。solver audit JSON 受 1 MiB 上限约束，以 no-follow/nonblocking 方式打开并验证普通单链接文件及读取前后身份；绑定的 source log 流式校验字节数和 SHA-256。

matrix 输出将 `native_integrity_evaluated=false`、`full_t1_decision=false`、`readiness_pass=false`、资格信用 0 固定为边界。失败 case 保留在完整分母中，关联比较或 timestep/cadence 门失败会传递到聚合结果。

## 独立审查与验证

Terra High（`gpt-5.6-terra`, high；agent `01a0d2ed-c88b-76c0-9ec5-38077fa80a7a`）对 producer 静态实现复核为 `PASS`，机器回执：[producer-review-v2/receipt.json](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/producer-review-v2/receipt.json)。producer synthetic suite 7 passed；归档完整性与 producer 合计 11 passed。

matrix review 经两轮审查补充后最终 `PASS`，机器回执：[metric-matrix-review-v2/receipt.json](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v2/receipt.json)。最终 matrix synthetic suite 22 passed，覆盖 15-case 固定分母、失败传播、跨分辨率时间网格和阈值、timestep 顺序/相位、cadence 时间戳/长度、receipt/hash 绑定、非零信用/T1 输入拒绝，以及 oversized/symlink/FIFO audit 拒绝。

含 table-v2、B/C/D metric verifier、v1/v2 metric adapters、producer、matrix 及两层 immutable review archive 的最终联合 synthetic 回归 96 passed。新增 Python 文件通过 `py_compile`，`git diff --check` 通过。

## 边界与未完成项

全部测试只使用临时合成 source frames、HDF5、B/C/D bundle 和 audit/source-log 文件。未读取 production B/C/D bundles 或 solver frames；未运行 GenCase、native decoder、solver、worker、GPU 或 queue。

producer 是序列化 primitive，尚未接入真实 D-stage artifact/receipt 生成链。调用方仍需负责以安全、哈希绑定的方式在两遍独立重开 raw C source；primitive 不认证 B/C provenance、授权真实性或 runtime identity。matrix 消费逐案结果对象，不自行重开并认证调用方 B/C/D receipts。native-integrity gates、loaded-module/runtime identity、真实 solver timestep evidence 和最终 T1 adjudicator 仍未完成；当前也没有本轮可用于正式 15-case 评分的 production solver frames。因此 R008 仍非资格通过，readiness false、零信用，solver/worker/GPU/queue 执行门未改变。

## 后续推进

下一块静态工作应把 producer 的安全 source-frame contract 与既有 C-manifest/逐案 D receipt 流程接起来，并补齐 native-integrity 审计接口；接线前仍不能将这些静态 adapter 描述为端到端可信执行链。正式 T1 必须等待独立执行授权、资源准入和真实 solver 产物。
