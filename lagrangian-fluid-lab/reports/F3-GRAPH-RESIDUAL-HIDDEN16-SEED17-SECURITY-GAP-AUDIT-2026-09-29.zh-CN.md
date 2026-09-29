# residual graph_hidden16 seed17 diagnostic admission/secure runner v2 独立安全审计

状态：`closed_minimal_fail_closed`；本地测试全通过，但生产运行证据仍有明确 blocker。

本次只收敛 residual seed17 专属边界。admission 现在要求外部 Ed25519 scheduler authority；authority 将 plan、namespace inode、resource snapshot 与 GPU UUID/PCI digest 绑定，并通过外部一次性 claim 后才允许本地 receipt consumption。输入、source、executable、cwd、namespace 和 terminal artifact 均要求稳定 FD/path identity；runner 将输出绑定到 receipt root/namespace，拒绝已有输出和身份漂移。

runner 的 execution capability 仍未安装：`build`、dry-run 和显式 diagnostic execute 都不消费 receipt、不调用 `Popen`/`wait`、不启动 GPU/solver、不启动 validator、不生成 terminal receipt，credit 与 formal/Core side effects 保持 `0`。报告校验也会拒绝伪造的 `popen_called`、`wait_observed` 或 `validator_started`。

验证：`.venv/bin/python -m pytest -q tests/test_f3_graph_residual_hidden16_*.py`，seed17 专项 10 项、相关 residual hidden16 回归共 187 项，全部通过；执行期间未启动 GPU/Popen/solver。

仍无法由本地静态证据关闭的 blocker：

- 生产 scheduler trust anchor、真实 scheduler reservation 及原子一次性 claim 尚未提供；测试 authority 是隔离 synthetic fixture。
- 没有 live GPU UUID/PCI 与精确 child launch 的运行时 attestation。
- 没有获准的真实 sealed `Popen`/`wait` witness、descriptor-bound child output publication 或独立 terminal HDF5 validator 运行证据。

范围明确排除 residual seed29/43、raw、MLP 以及 Core registry/ledger/denominator/gates/completion/PLAN。
