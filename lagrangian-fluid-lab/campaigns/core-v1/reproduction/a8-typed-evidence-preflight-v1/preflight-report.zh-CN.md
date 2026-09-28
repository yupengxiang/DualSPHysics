# A8 typed-evidence preflight（diagnostic-only）

本报告对应 `preflight-report.json`，由
`scripts/core_independent_reproduction_preflight.py` 只读生成。它只验证
bounded JSON/hash 证据的结构和跨文件绑定，不启动 workload、solver、worker、GPU
或 queue，也不打开 HDF5、checkpoint 或其他二进制数据。

## 结果

- 结构预检：`pass`
- typed evidence：五类、六个 role 均已装配
- 两个 data root：canonical path distinct，两个 package manifest 使用同一
  `package_sha256`，且 package artifact SHA-256 已核对
- 组件链：`reader -> prediction -> scoring` 的 output SHA-256 绑定闭合
- prediction：声明 autonomous、full horizon，且
  `future_state_inputs=false`、`predictor_future_state_inputs=false`
- `diagnostic_only=true`
- `independent_reproduction=false`
- `full_product_reproduction=false`
- `formal_admission=false`
- `formal_training_count=0`
- `credit=0`、`qualification_credit=0`

## 输入范围

projection 的 `input_origin` 是 `historical_receipt_projection`。它绑定了已有的
A8 reader preflight、model reproduction report 和 score report 的路径、字节数与
SHA-256；新的 typed wrapper 不改写这些历史文件。

reader、prediction、scoring 的输出 wrapper 分别绑定 reproduction host、relocated
data root 以及前一阶段的 artifact hash。data-roots wrapper 同时绑定 source 与
reproduction package manifest；manifest 再绑定实际 package artifact 的 SHA-256。

## 尚缺的外部证据

这次通过的是结构性 preflight，不是 Core gate 的 independent-reproduction 通过。
仍需由受信 root review 提供并重新绑定：

1. 同一条证据谱系上的 source host、reproduction host、两个 data root 和三阶段
   输出的可信 root receipt；
2. 非 diagnostic 的、在另一台物理机器和 relocated root 上完成的 reader、自治
   prediction、scoring 全产品证据；
3. 对完整登记矩阵的正式复现、失败分母与 gate verifier 记录。

历史 A8 资产仍包含 diagnostic-only、单案例/工程 preprofile 以及 same-host
relocation 限制，因此本报告不会把它们升格为 `independent_reproduction`、formal
admission 或任何 qualification credit。

## 执行边界

本次 intake 的 execution constraints 全部保持只读：

```text
workload_started=0/false
solver_started=0/false
worker_started=0/false
gpu_started=0/false
queue_mutation=0
registry_mutation=0
ledger_mutation=0
denominator_mutation=0
gate_mutation=0
```

因此该报告可以作为 A8 后续 root review 的输入候选，但不能直接写入
completion、registry、ledger、denominator 或 gate。
