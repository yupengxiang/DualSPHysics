# Core 计划续接状态更新（2026-09-23 11:29 UTC）

本更新接续 `CORE-CONTINUATION-STATUS-2026-09-23.zh-CN.md`，仅记录新的静态产物和运行状态观测；不改变研究分母、资格、资源授权或运行队列。

## F8 R008 静态预检请求

- v2 请求发现路径解析缺陷：native argv 使用仓库相对路径，但声明的工作目录位于更深的 Definition 目录。该请求从未执行，未创建运行目录。
- 保留 v2 作为审计记录，并由 v3 明确标记 `superseded_not_executed`。v3 对 GenCase、Definition、BI4、输出使用绝对路径，仍只绑定 94 个静态输入及其哈希。
- v3 请求闭合 24 个静态来源哈希；4 GiB systemd/cgroup 上限仅引用已验证的“应用机制”，未声称 native 峰值或压力测试已测。
- 定向测试：`16 passed`；`git diff --check` 和 Python 编译检查通过。
- 提交 `0e5f4e6 prep: bind F8 R008 request to absolute native paths` 已推送到 `codex/lagrangian-fluid-pipeline`。
- v3 仍是 request-only：没有启动 GenCase、native decode、solver、GPU、worker、queue 或训练；没有创建 `cpu-native-preflight-v3` 运行目录，资格信用为 0。

## F3/F4 运行门与 Core 状态

- 2026-09-23 11:29 UTC，只读检查 F3 material row30 R003 的原子 checkpoint JSON 为 frame `624/835`；没有读取活跃 `trace.h5` 或 checkpoint NPZ。F3 worker 仍运行，CPU 使用约 `99.5%`。
- 同期主机 load average 约 `133.61 / 138.71 / 137.93`，可用逻辑 CPU 为 `128`。F4 supportcap R002 的唯一 CPU-native 预检仍受“无活跃 F3 worker 且 1 分钟 load 不超过 CPU 数”条件阻塞；可用 RAM 和磁盘门也须在执行时重新检查。预检回执尚不存在，单次机会未消耗。
- Core status 仍为 `can_finalize=false`：合格 T1 家族为 F3/F4；目标 T1 case-run 缺 `432`，材料 case-run 缺 `288`，正式训练为 `0/9`。F8 R008 的静态请求不改变这些门槛。

## 下一步

1. 只监测 F3 R003；worker 结束后，先审计终态回执、完整 835 帧区间、输入哈希与材料接受门。
2. 仅当 F3 worker 已退出，且 F4 单次预检的 CPU、RAM、磁盘、输出命名空间和来源身份条件全通过，才消耗该预检授权。任何一项不满足都不启动。
3. F8 R008 请求文件本身不授予执行权限；后续探索仍限 CPU/native 预检及其已授权范围，不扩展到 solver、GPU、queue、worker 或 T2。资源门未解除前不启动。
