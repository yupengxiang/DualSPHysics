# A8 package/reproduction readiness boundary audit V1

结论：当前 A8 路径没有可直接晋级 trusted-root、external-host 或 independent-reproduction 的证据；但发现了两个具体、可独立推进的 package bridge 边界缺口，因此本审计保持 fail-closed，未授予 readiness、independent reproduction、formal admission 或 credit。

审计只读取有界 JSON 和历史 receipt：

- 当前 `core.reader_bundle.v2` 有 32 个 case，但 `checkpoint_count=0`、`model_reproduction_supported=false`，因此它是 reader-only 包，不是当前 trusted model package。
- 当前 package/reproduction report 虽为 `local_package_ready=true`，仍明确是 `diagnostic_only`，`formal_admission=false`、`full_product_reproduction=false`、credit 为 0；大 HDF5/NPZ/checkpoint 内容没有打开。
- trusted-root/external-host contract 仍是 synthetic blocked；历史 second-host pair 仍是 diagnostic-only，不能替代 fresh external attestation。
- 历史 independent receipt 自身同时出现旧 v1 bundle、`full_product_reproduction=true` 与 `blocked_for_full_product_release; diagnostic_model_reproduction_only`，故只能作为历史 metadata，不能作为当前 authority。

发现的边界缺口：

1. `core_product_repro_bridge_v1._reader_report_projection` 对 `core.verification.v1` 只检查 `passed=true`，未强制 receipt 的 diagnostic-only/zero-credit 边界。内存负向变异中，带有非 diagnostic、formal-training 和正 credit 字段的 payload 仍被接受为 passed projection。
2. `core_product_repro_bridge_v1._diagnostic_pair_projection` 信任 `distinct_host_evidence` 和 `observed_hosts` 自报值；内存负向变异将两个 host id 改成同一值后，rollout 与 score 仍为 passed，且无 blocker。

真实的最小推进单元是 package bridge projection hardening：补齐 reader receipt 的精确 diagnostic/zero-credit 检查、补齐 host list 的非空/两两不同及独立 second-host receipt 绑定，然后重新运行 bounded package/reproduction readiness projection。该单元不需要外部 attestation、不需要打开大文件，也不需要 solver、worker、GPU 或 queue；本报告本身不允许 promotion。

本轮没有伪造 attestation，没有启动 workload，没有修改 registry、ledger、denominator、gate、completion、PLAN 或 UPDATE-410，也没有写入 F3/F4 文件。验证范围限定为目标回归、`py_compile`、JSON verify 和 `git diff --check`。
