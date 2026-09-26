# UPDATE-187：F3 row30 新鲜资源预检与 F8 R002 静态复核

## F3 material row30：v5 新鲜资源/调度预检

按用户新授权新增独立 one-shot wrapper 与命名空间，并消费一次 v5 预检。不可变回执为 [receipt](../campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v5/receipt.json)，SHA-256 `ab0d72386a6f91f625ce320781c581eaad7dc1f448dad8acf46cf3b93f7fed7a`；一次性锁 SHA-256 `79fa15deea7af0efbcff25c611fad519385c2e4c3ac5554e5f89bc769da6bcd1`。该记录 supersede v4 观察，但保留全部旧 receipt/lock。

状态 `blocked_no_worker_authorized`。观测时可用 CPU 128，1 分钟 load 约 103.48，RAM 226,253,938,688 bytes、磁盘空闲 8,173,389,967,360 bytes；无匹配 row30 worker，scheduler active jobs 为 0。阻塞项仍为历史资源 ledger 已于 `2026-09-16T00:00:00Z` 过期、累计 CPU 上界 `911.958 > 896` core-hours。故按 fail-closed 规则未重新 hash production HDF5 或 PREPARED 文件；receipt 也明确 `worker_launch_authorized=false`。仍需新的 root resource decision 与独立 worker-launch authorization；本次预检不授予二者。

v5 wrapper 和负例测试只实现独立 receipt/lock、v4 历史绑定及 no-worker 边界。F3 row30 v1–v5 五个专项测试 **14 passed**，v5 `py_compile` 通过。未启动 worker/solver/GPU、未触碰 queue/ledger/registry，T2 credit 保持 0。

## F8 R002：封存输入只读静态复核

当前 Definition、control CSV、CPU/native preflight receipt 与保留 GenCase stdout 的字节数及 SHA-256 均与既有 static-design-review-v3 receipt 相符。R002 Definition 不含 `<hswl>`；封存 GenCase v5.4.354.01 日志明确报告缺少 `hswl` 并以退出码 1 停止。这证明该次 R002 GenCase attempt 失败，R002 继续 `closed/no retry/credit=0`。Definition 同时相对绑定的官方 DualSPHysics v5.4 Poiseuille Definition 缺少 `rhopgradient`、`gamma`、`speedsystem`、`coefsound`；这些是静态兼容差距，日志并未证明它们也触发失败。

control CSV 为七列，705 行有限数值，时间严格递增 `0–11.196636217394023 s`；首步长与 `TimeOut=0.015904312808798327 s` 一致，其他五个控制分量为零。由于 Definition 在解析阶段失败，现有证据**不证明 control CSV 被 GenCase 加载或消费**。本轮未改输入、未重试 R001/R002，也未调用 GenCase/native decoder/solver/GPU/worker/queue。

本轮请求的 Terra High/high subagent 未能 attestate 实际模型身份，且其补充比较引用了另一条 W04 文件路径；因此不声称获得独立 Terra High verdict。这里的结论以已绑定的 R002 v3 receipt、原始日志和官方 v5.4 vendor Definition 的本地只读复核为依据；不改变历史回执或 R002 的关闭状态。

## 边界

- F3 v5 one-shot 已消费；不得把 blocked 预检重试成 worker 启动。后续首先需要更新/签发有效 root resource decision，再另行评估执行授权。
- F8 R002 不得编辑或重试；任何修正必须是 fresh revision/namespace 并另获其自身授权。
- 本轮仅新增 v5 预检脚本、专项测试、不可变回执/锁与本报告/PLAN 记录；没有改变资格阈值、分母、registry、ledger 或生产数据。
