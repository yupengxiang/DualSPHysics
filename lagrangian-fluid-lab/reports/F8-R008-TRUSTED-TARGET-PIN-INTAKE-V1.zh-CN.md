# F8/R008 trusted target-kernel/source/build/runtime pin intake V1

状态：`blocked_missing_external_trusted_pin_attestation`。

本次新增的 F8 专属 intake 只接收两份由外部提供的 bounded canonical JSON：

- target-kernel/source/build/runtime ABI 与 host identity 的 pin attestation；
- 与其严格绑定的 external trust-root/key anchor。

attestation 还必须包含已消费的 one-shot receipt，并同时绑定 scope、完整 pin-set SHA、host identity SHA、trust-root/key、nonce、generation 和消费窗口。验证器会检查严格 schema、canonical JSON、Ed25519 签名、跨域 SHA、kernel release/source commit/source tree/UAPI/config/build ID、runtime ABI（含 0..461 selector domain）以及 receipt transition。

当前真实 external attestation 和 trust anchor 均不存在，因此所有 pin 均为 `false`，状态保持 `blocked`；本机 kernel/config/header、synthetic fixture、candidate/self-signed key 都不能升格为 production proof。即使未来收到结构上完整的 external attestation，本 intake 也只产生 non-authorizing structural evidence，不测量 live runtime、不观察 replay ledger、不授予 execution/readiness/T1/credit。

本模块没有读取 current host kernel、procfs/sysfs、source tree、build artifact 或 solver 产物，没有执行 privileged probe、native、solver、worker、GPU、queue，也没有写 registry、ledger、gate、denominator、completion 或 PLAN。

机器报告：[F8-R008-TRUSTED-TARGET-PIN-INTAKE-V1.json](F8-R008-TRUSTED-TARGET-PIN-INTAKE-V1.json)。
