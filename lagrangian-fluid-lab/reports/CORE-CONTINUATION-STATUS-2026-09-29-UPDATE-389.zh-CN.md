# Core continuation status — UPDATE-389

日期：2026-09-29

本轮继续优先推进 F3 MLP hidden16 的完整 rollout 方向，并把 residual/raw 的 partial 终态审计同时收口。当前 subagent 策略入口仍固定为 `gpt-5.6-luna`、reasoning `max`；历史 GPT-6 Luna、Terra 与其他 receipt 保留为历史记录，不改写。

## 已完成的可提交任务

- `68117347`：新增 bounded fresh-terminal intake builder，固定 seed17/29/43、F3 case、835 transitions/836 frames、fresh nonce 与 evaluation/trajectory/validator/training/history/process-proof 交叉绑定。
- `dac6d55b`：补齐 pretty-printed evaluator JSON 的流式 whitespace 解析，并加入真实格式回归。
- `a2d87747`：sidecar producer 只能在真实 Popen 成功自然退出、输入绑定和 terminal artifact 检查通过后被授予一次性 capability。
- `02a7de15`：新增 sealed、一次性 post-terminal validator capability；validator callback 不能取得 Popen、PID、checkpoint、plan 或 sidecar 路径，返回值不被当作证据。
- `9e77eb98`、`f9696b0e`：partial rollout audit reducer 与其安全加固，补齐过深 JSON fail-closed、progress SHA/父路径稳定性及 row-level 权限字段校验。
- `4dbc5f2f`：记录六个 fresh residual/raw namespace 的 bounded terminal audit。

## 当前事实边界

MLP 三个旧 fresh evaluation JSON 已能通过 bounded streaming parser；但当前仍缺独立 trajectory metadata 和可信 process-exit proof，因此 intake 结果保持 `blocked`、`source_bound=false`、`formal=false`、`credit=0`。residual/raw 六条 partial namespace 分别只达到 residual `250/250/225`、raw `150/150/125` frames，没有终态 evaluation/HDF5/process proof，不能冒充完整 rollout。

上述组件只保留 diagnostic-only 语义，不写 registry、ledger、denominator、gate 或 completion。Core completion status 仍为 `can_finalize=false`：正式九条 training run、完整 T1/material denominator、第三个 T1 family、两个 macro-T2 family 和 independent reproduction 均未闭合。

验证记录：launcher 专项 `27 passed`，MLP hidden16 相关回归 `55 passed`，partial reducer 加固专项 `27 passed`；此前联合专项回归 `201 passed`。所有运行未停止或重启 live evaluator，未把 GPU 占用视为阻塞。
