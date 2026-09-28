# A8 独立复现 Readiness Contract V1（2026-09-29）

## 结论

本报告是 synthetic-only、bounded、read-only 的 A8 readiness 诊断合同。结构化 projection 可以闭合 typed preflight、source/reproduction 两个 data-root identity/hash 绑定，但当前没有可信 trusted-root review，也没有真实 external-host attestation，因此：

- `status=blocked_missing_trusted_root_and_external_host_attestation`
- `structural_contract_passed=true`
- `readiness_pass=false`
- `independent_reproduction=false`
- `full_product_reproduction=false`
- `credit=0`
- `qualification_credit=0`

这里的 `passed=true` 只表示 synthetic projection 通过了结构合同，不表示独立复现或任何正式资格通过。

## 三项边界

1. typed preflight projection：通过。输入保持 `diagnostic_only=true`、`independent_reproduction=false`、`credit=0`。
2. independent data-root identity binding：通过。合同重算并绑定 source/reproduction root、各自 manifest SHA-256 与共同 package SHA-256；仅是 synthetic projection binding，不是可信外部 root attestation。
3. trusted root / external host：均不通过。fixture 明确使用 `authenticated=false`、`attested=false`、无 receipt reference；合同拒绝把 caller 的 synthetic boolean claim 当成 authority，也没有伪造或读取外部 host receipt。

## 执行边界

合同只处理 bounded canonical projection；未打开 checkpoint、HDF5、trajectory 或其他 production artifact，未启动 native、solver、worker、GPU、queue，未写 registry、ledger、denominator、gate 或 completion。

下一步必须由真实、独立可信的 root review、真实 external-host attestation，以及另一台物理机上的 non-diagnostic full-product evidence 提供；本报告本身不能替代这些证据，也不改变 Core gate。

机器报告：[A8-INDEPENDENT-REPRODUCTION-READINESS-CONTRACT-V1-2026-09-29.json](A8-INDEPENDENT-REPRODUCTION-READINESS-CONTRACT-V1-2026-09-29.json)

