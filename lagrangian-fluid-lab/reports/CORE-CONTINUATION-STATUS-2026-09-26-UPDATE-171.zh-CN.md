# UPDATE-171：F3 row30 新鲜资源预检与 F8 R002 静态复核

时间：2026-09-26（Asia/Shanghai）

## 已授权事项

### F8 R002 静态设计复核

按本轮授权对现有 R002 Definition、控制 CSV、保留 GenCase 失败日志/预检回执和官方 v5.4 Poiseuille Definition 做只读复核。结果仍为 **FAIL / R002 closed / qualification credit 0**：Definition 缺 `hswl`，保留 GenCase 日志对同一绑定输入报告 XML 第 5 行缺该字段、退出码 1；`rhopgradient`、`gamma`、`speedsystem`、`coefsound` 也缺于官方模板，但仅 `hswl` 有该次引擎失败日志佐证。七列控制表结构有效，有 705 行有限值且时间从 0 严格递增至 `11.196636217394023 s`；因为 GenCase 在 Definition 解析阶段停止，这不证明控制文件曾被加载。

审查 agent 被配置请求 `gpt-5.6-terra/high`，但 agent 明确自报为 GPT-5 Codex、无法 attestate Terra High。因此这只记录为只读复核，不声称 Terra High 独立审查。没有修改或重试 R001/R002，没有调用 GenCase/native decoder/solver/GPU/worker/queue，也没有读取 HDF5/NPZ。绑定：Definition `086fa1cab8019c39c2d22fdfbee069441663b0615cdf9246c4383fd51b1b0bea`；control CSV `bd623b5681f449804a3a2bdf61cded339e180065cf37e2d5d8b6ac92f9e3cfc1`；GenCase log `9d6233c836781b84f840145d8e0597920430b395dad8686a5342516244a8a26b`；preflight receipt `2c4680deffeeb09d5220ac2f760745e28575126fc9ebf33f55a562fd20675928`；官方 Definition `ab7e06d9a5c2a5bad899f36ef393bc1d3867cd88fbf7aba5a734ee1e4ffaa2fe`。

### F3 row30 新鲜资源/调度预检

新增 v4 wrapper/test 与独立 one-shot namespace；不可覆盖保留 v1–v3 历史。按新授权执行一次，回执为 `blocked_no_worker_authorized`。快照：128 个可用 CPU、load averages `218.92 / 196.87 / 179.39`、可用 RAM `222,654,455,808` bytes、可用磁盘 `8,175,239,704,576` bytes；没有匹配的 row30 worker，scheduler active count 为 0。硬阻塞为 1 分钟负载高于 CPU affinity、历史资源 ledger 于 `2026-09-16T00:00:00Z` 到期，以及预计累计 `911.958` CPU core-hours 超 `896` 上限。

因此 source HDF5 和 PREPARED 资产按既有 fail-closed 策略未 rehash；本次没有 worker、solver、GPU、queue、ledger 或 registry 活动，T2 credit 仍为 0。one-shot lock 与 v4 回执已写入 `campaigns/core-v1/material/evidence/f3-material-row30-resource-preflight-v4/`；回执绑定 v4 builder/test 和前序 v3 receipt。新的 root resource decision 与单独 worker-launch authorization 仍必需。

### F4 supportcap 范围

当前仓库仍只有已登记的 `f4_supportcap_affine_query_bound_v3`，旧 R002 preflight one-shot 已消费并标记 same-scope retry forbidden；没有独立的新 F4 candidate 可供本次新候选预检绑定。故保留该次 F4 授权未消费，不伪装成对旧 v3 的新预检，也不创建未获具体设计范围的候选、不运行 canary/solver。

## 验证

- F3 v3/v4 contract tests 与 PartExtra/主帧 finite tests 合并：**54 passed**。
- v4 one-shot receipt/lock 可解析，receipt 状态、source hash short-circuit 与 no-worker fields 已逐项核对；v4 builder/test SHA 与回执 bindings 相符。
- 仅做资源/调度快照及静态文件复核，没有启动计算工作负载。
