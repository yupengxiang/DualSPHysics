# F3 graph_raw hidden16 seed17 diagnostic rollout：blocked RERUN1

- 模型：`graph_raw / hidden16 / seed17 / 500 updates`
- current-manifest：`f3-dataset-v2.json`，raw SHA `8d87da6a…e680`，canonical SHA `5d53fd9c…c768`
- 训练 evidence：`complete`；checkpoint SHA `1e191bf2…9ace6b`
- 目标闭环：`835 transitions / 836 frames / F3_DEV_00_a0p903125 / test`
- GPU 预检：GPU0–7 均 `15 MiB used / 48,497 MiB free / 0% util`；选择 GPU2

## 真实入口结果

使用已有 seed17 admission receipt 调用仓库的 `f3_graph_raw_hidden16_seed17_diagnostic_runner_v2.py --diagnostic-execute`。入口在 Popen 前 fail-closed：

`fail-closed: fail-closed: authority must be an object`

因此本轮：

- `popen_attempted=false`、`wait_attempted=false`、`real_workload_started=0`
- 没有生成 terminal receipt；不能声称完成 835-transition/836-frame rollout
- 没有启动 GPU、solver、worker、queue，也没有停止或重启任何既有进程
- 没有写 registry、ledger、denominator、gate 或 completion；`formal=false`、`credit=0`

## Validator 与测试

- runner blocked report：已验证通过
- terminal-artifact validator：`blocked_fail_closed`，未打开生产 artifact，真实 producer/terminal proof 均缺失；report 已验证通过
- 定向安全入口回归：`61 passed`

原始 runtime blocked report 保存在模型专属 runtime attempt；可提交的副本及 validator report 见同目录 `reports/`。已有 admission receipt 保持原样，没有补写 `authority` 字段或绕过执行边界。
