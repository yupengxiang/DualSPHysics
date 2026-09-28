# F8/R008 syscall policy contract v1（静态、非授权）

本轮 bounded additive audit 确认：已有 Linux v6.8 x86-64 syscall universe baseline、signed-int32 selector partition、source audit 与 readiness v8，但它们尚未提供一个独立的、可校验的逐号 policy contract。baseline 的 462 行仍将 `disposition` 与 `predicate` 保持为 `null`；selector 与 readiness v8 也明确记录逐号字段和 target-kernel/config pin 尚未完成。

新增：

- `scripts/f8_r008_syscall_policy_contract_v1.py`：fail-closed 静态 verifier/schema。它绑定 baseline artifact、selector artifact 与既有 Linux v6.8 source-audit artifact，要求 policy 精确覆盖 native `0..461` 的 462 行；每行只能使用固定 disposition 枚举，并在完成状态下提供显式、非 wildcard predicate。它还定义 target kernel build/source/UAPI identity 与 target config hash/relevant options 的结构化 pin 字段。
- `reports/F8-R008-SYSCALL-POLICY-CONTRACT-V1.json`：462 行静态模板。所有 disposition/predicate 与 target kernel/config pin 仍为空，因此 `contract_state=incomplete_static_template`、readiness/T1/credit 均保持关闭。
- `tests/test_f8_r008_syscall_policy_contract_v1.py`：模板、完整 synthetic contract、缺行/缺 predicate、hole allowlist、wildcard、source binding、config pin 与 capability boundary 测试。

完整 synthetic candidate 只在临时测试对象中验证 schema 完整性，不写入 production artifact，也不声称 target kernel 已验证。即使静态字段完整，contract 仍固定为 `runtime_conformance_verified=false`、`execution_authority=false`、`readiness_pass=false`、`T1_numerical=false`、`qualification_credit=0`；既有 source audit 的 `target_kernel_source_pinned=false` 也保持不变。

复验：

```text
32 passed
contract --verify: incomplete_static_template, 462 rows,
  per-number disposition/predicate=false,
  target kernel/config pin=false, readiness=false, credit=0
```

本轮未执行 kernel probe、root/sudo、ptrace/seccomp runtime、native/solver/worker/GPU/queue，也未修改 readiness v8、registry、ledger、denominator 或历史 receipt。
