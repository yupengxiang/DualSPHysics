# Core 计划续接状态更新（2026-09-23 12:22 UTC）

本更新接续 UPDATE-01；仅新增 R008 独立静态审查、一次性 CPU/native 预检授权与当前资源门观测。不改变资格分母、T1/T2 credit、solver/worker 队列或训练状态。

## F8 R008 静态审查与受限预检授权

- Terra 模型子代理对 R008 的 T1 scope、输入包、v3 request 和资源证据做只读审查，结论为 `pass-with-gaps`：13 个空间配置加 CFL/输出 cadence 两个对照共 15 格，定义和门槛冻结；94/94 Definition/control 哈希、24/24 源码哈希均匹配。代表 case 为 `space-q0p5-dp0p0075`，与 R007 几何子树一致；R007 输出与 credit 不复用。
- 审查发现旧资源准入与 capability probe 仍引用 request-v1。因此新授权直接绑定 request-v3、94 个输入、24 个源文件、capability probe、审查回执、GenCase/decoder 二进制，以及执行器、监测 wrapper、审计代码和测试。模型身份无法由审查工具独立证明，回执仅记录所请求的 `gpt-5.6-terra / high`，不声称额外认证。
- 新的一次性授权仅覆盖 `space-q0p5-dp0p0075` 的一次 CPU GenCase 和至多一次 BI4 decode：4 GiB systemd/cgroup `MemoryMax`、native 子进程固定单 CPU、串行执行、超时与完整 cgroup `memory.peak`/`memory.events`/RSS 留证。任何输入/几何错误、超时、cap pressure 或 OOM 都零 credit、停止且禁止重试。
- 明确不授权 solver、GPU、worker、queue/scheduler、训练、registry/ledger/分母变更或 T1/T2 qualification。静态授权本身不创建 runtime namespace，也不消耗 one-shot lock。
- 新执行器定向测试 `12 passed`；R008 v3/输入包与继承的 R006/R007/R003 审计测试合计 `50 passed`（排除一个已知旧 R007 环境冲突）。完整相关测试运行中，`test_runner_builds_only_registered_argv_and_rejects_scope_substitution` 因历史 R007 one-shot 输出目录已存在而失败；没有删除或改动该历史产物。

## 当前资源预检（只读）

- 2026-09-23 12:22 UTC：CPU affinity `128`；load average `133.41 / 136.62 / 138.99`；可用内存 `226,297,638,912` bytes；磁盘可用 `8,188,948,971,520` bytes。RAM/磁盘门通过，1 分钟负载门不通过。
- F3 material row30 R003 的 coordinator/worker PID `1151859/1151871` 仍活跃；只读原子 checkpoint 为 `687/835`。未读取 `trace.h5` 或 checkpoint NPZ。
- rootless systemd user manager 响应正常，两个 R008 专用 scope 名称均为 `not-found`。执行器 `--preflight-only` 返回 `deferred_resource_gate_blocked`（负载超 128 且 F3 活跃），确认 runtime namespace 与 one-shot lock 均不存在。
- 本更新没有启动 GenCase、BI4 decoder、solver 或任何 worker；一次性授权仍未消费。后续只在 F3 worker 退出且所有即时门槛通过后，才可运行这一次 native-only preflight。
- Core status 复核仍为 `can_finalize=false`：T1 家族只有 F3/F4，macro T2 家族为 0，正式训练 `0/9`，目标 T1 分母缺 `432`、材料分母缺 `288`，独立复现门未通过。

## 下一步

1. 继续只监测 F3 R003；完结后审计完整 835 帧、输入身份及材料接受门。
2. F3 退出且 load、RAM、磁盘、systemd/cgroup 与 namespace 门均通过后，执行 R008 唯一一次 GenCase + native decode；发生任一失败即保留证据并关闭，不重试。
3. 同一资源窗口下再评估已授权的 F4 supportcap CPU canary 预检；solver/GPU/队列/T2 范围仍关闭。Core 总体状态按 UPDATE-01 所列门槛继续保持未完成。
