# Core continuation status — UPDATE-380

日期：2026-09-28（Asia/Shanghai）

## 并行 rollout 启动

为沿着 F3 `graph_residual` / hidden16 方向先走通一条完整诊断链路，新增了以下
独立 GPU namespace：

- 既有 seed17/29/43 `diagnostic-v1` full835 任务继续运行，未停止、重启或改写；
- seed17 的 `F3_DEV_01`–`F3_DEV_05` 在独立 `diagnostic-v2` 路径运行；
- seed17/29/43 各一条 `full835-nonce<32-hex>` 任务在 GPU3 的剩余显存中运行，
  这是唯一允许进入 UPDATE-379 runtime verifier 证据链的新增 rollout 集合。

GPU3 启动时已有外部任务，但显存余量足够；没有终止或迁移该任务。每条 evaluator
均使用独立 trajectory/progress/evaluation 输出路径，避免不同任务互相覆盖。

## 当前边界

本轮启动只证明调度和 namespace 隔离，不证明 rollout 完成。记录时 nonce 三条
evaluator 仍存活，evaluation JSON 尚未出现；旧 `diagnostic-v1/v2` 路径也不符合
新的固定 nonce 终态合同，不能被 runtime verifier 接受。所有任务保持
`diagnostic_only=true`、formal/T1/T2/qualification=false、credit=0，未写入
registry、ledger、denominator、gate 或 completion。

每条任务退出后还必须：

1. 读取真实 return code 和 launcher/evaluator exit proof；
2. 只在退出后运行独立 HDF5 validator；
3. 生成 evaluation identity、validator receipt 与 terminal matrix 的交叉绑定；
4. 运行 UPDATE-379 verifier，缺任何一项则保持 `blocked_fail_closed`。
