# F3 graph_raw hidden16 terminal artifact validator/canary

- 状态：`blocked_fail_closed`
- capability admitted：`false`
- launch allowed：`false`
- HDF5 观察：`not_run`（本次没有 synthetic fixture 输入）
- 合同：`graph_raw / hidden16 / test / 835 transitions / 836 frames`
- 边界：只允许带 marker 的临时 synthetic HDF5；checkpoint/evaluation/manifest 只做 bounded metadata 声明绑定，不读取内容
- real producer proof：`false`
- real terminal proof：`false`
- credit：`0`

## Blockers

- 未提供 bounded validator metadata。
- 缺少真实 producer proof。
- 缺少真实 terminal proof。
- terminal artifact capability 仅为 diagnostic-only，未授权 launch。
