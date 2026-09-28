# Core continuation status — UPDATE-384（2026-09-28）

## F3 graph_residual hidden16 process-exit proof normalizer

已新增并提交 `f3_graph_residual_hidden16_process_exit_proof_builder_v1.py` 及其独立测试，提交为 `311b8b93`。

该工具用于 evaluator 自然退出后的 bounded 证据组装，不启动运行时、不读取大型 artifact、不改变 Core 状态。它固定校验：

- graph_residual / hidden16 / 500 updates / seed 17、29、43；
- `F3_DEV_00_a0p903125`、`test`、835 transitions / 836 frames；
- evaluator 与 launcher 的自然退出和 returncode，以及 command digest；
- full835 输出必须使用独立的 32-hex fresh nonce namespace；
- checkpoint、training、evaluation、trajectory、validator 只保留安全路径与 `lstat` 元数据，不打开内容。

builder 拒绝 PID、formal、credit 等伪字段，拒绝路径穿越、symlink/hardlink、未知键、非有限值和缺失终态证据。默认无输入运行保持 blocked，不会伪造 receipt 或写入真实报告。

验证：builder 专项 `18 passed`，residual terminal runtime verifier 回归 `26 passed`，py_compile 与 diff-check 通过。当前 residual evaluator 仍在运行，尚未生成可供 builder 绑定的真实 process-exit proof；formal/T1/T2/qualification/credit 继续为 `false/0`。

