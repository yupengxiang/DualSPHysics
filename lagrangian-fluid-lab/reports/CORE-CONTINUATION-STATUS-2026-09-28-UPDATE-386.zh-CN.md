# Core continuation status — UPDATE-386（2026-09-28）

## F3 graph_raw hidden16 terminal runtime verifier V1

已新增并提交 `f3_graph_raw_hidden16_terminal_runtime_verifier_v1.py`、专项测试、默认 bounded JSON 报告和中文说明，提交为 `a4824ac9`。

verifier 的正向条件是四类证据全部闭合：

1. graph_raw hidden16 三 seed 的 terminal receipt matrix；
2. 每个 evaluator/launcher 的自然退出和 returncode proof；
3. evaluation identity 与 training/checkpoint/manifest/namespace 交叉绑定；
4. 独立 HDF5 validator receipt，证明 835 transitions / 836 frames。

所有 seed 必须固定为 17、29、43，case 为 `F3_DEV_00_a0p903125`、split 为 `test`，并使用全新的 32-hex nonce namespace。verifier 只消费受界限 JSON，不打开 evaluation、progress、checkpoint、trajectory/HDF5 或 manifest；拒绝旧 namespace、路径别名、symlink/hardlink、未知字段、重复键、非有限值和路径漂移。

专项测试 `19 passed`；与 residual process-proof/runtime、MLP launcher/runtime 和 residual terminal matrix 的联合回归共 `119 passed`，py_compile/diff-check 通过。由于当前 fresh graph_raw rollout 尚未形成四类真实终态证据，默认状态保持 `blocked_fail_closed`、`source_bound=false`、formal/T1/T2/qualification/credit=`false/0`。

