# Core continuation status — UPDATE-385（2026-09-28）

## F3 MLP hidden16 diagnostic rollout launcher V1

已新增并提交 `f3_mlp_hidden16_diagnostic_rollout_launcher_v1.py` 与独立测试，提交为 `20aff5c0`。

launcher 的边界：

- 默认只生成三 seed 的 dry-run 命令，不启动进程；只有显式 `--execute` 才会运行 evaluator。
- 固定 MLP / hidden16 / 500-update checkpoint、seed `17/29/43`、case `F3_DEV_00_a0p903125`、split `test`、835 transitions / 836 frames。
- 每次执行要求 32-hex fresh nonce 和唯一 `/tmp` namespace，拒绝旧 namespace 复用、路径 alias、symlink/hardlink、路径穿越和输出覆盖。
- evaluator 只有自然退出且 returncode=0 后才可记录 process-exit proof；不以 PID 或 progress 充当终态。
- 不打开大型 checkpoint、evaluation、trajectory/HDF5 或 manifest；所有输出强制 `diagnostic_only=true`、`formal=false`、`credit=0`。

专项 launcher 测试 `9 passed`，与 MLP terminal runtime verifier 联合回归 `20 passed`，py_compile/diff-check 通过。当前 GPU 上的 MLP fresh rollout 是在 launcher 提交前启动的独立诊断任务，launcher 没有接管、重启或替换它们。

