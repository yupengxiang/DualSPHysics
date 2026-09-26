# UPDATE-211：F8 terminal completion contract v6 复审与 v7 修订

时间：2026-09-26（Asia/Shanghai）

## V6 独立复审

Terra High 配置 reviewer 对 V6 最新文本做了只读复审，结论 `REVISE`、无 P0；reviewer 未 attestate 模型身份。它确认 V6 已闭合 registry self-hash、固定 registry snapshot、seal event 表述、main PART 与 PartExtra 区分，并未放宽原有授权边界。

仍有以下合同缺口：

- **P1：** V6 watcher 仅允许 child exit 后的 seal 事件，却拒绝 verifier 随后为 manifest/hash 执行的只读 reopen/read；`FAN_OPEN_PERM` 也没有区分受信 verifier 的只读访问。
- **P1：** `process_group_id`、`writer_cgroup_inode` 与 `mount_setattr` 缺少可独立核验的原始来源、FD/目录身份、系统调用 ABI 参数、完整属性字节、trace 身份和覆盖范围。
- **P2：** locale/runtime guard 未闭合 `dlmopen`、`dlvsym`、glibc loader 内部别名及 fork/vfork/clone3/进程型 clone 的覆盖边界。
- **P2：** `input_access` role 没有 `runtime_config`，未为自动加载 `DsphConfig.xml` 定义 present/absent 的绑定证据。
- **P2：** BI4 byteorder 观测没有绑定实际 child/TID、可执行文件/源码调用点、每个 BI4 文件及该文件首次 header write 的先后顺序。

## V7 additive proposal

新增 [terminal completion evidence contract v7](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V7-2026-09-26.zh-CN.md)，仅新增修订文本，不覆盖 V1–V6。V7 定义 child exit、只读 mount seal、verifier-only read/hash 三阶段与事件 union；补充 cgroup held-FD、`/proc/<pid>/stat` 原始 bytes 和完整 `mount_setattr` syscall 记录；要求闭合 loader entrypoint/alias 清单、进程创建 seccomp+syscall trace；将自动配置文件纳入 runtime_config input role 并区分 present/absent；为每个 BI4 文件绑定实际 writer 的 GetByteOrder probe 与首次 header write。

V7 当前等待 Terra High 配置独立只读复核。它仍是设计合同，不代表这些 monitor/supervisor/trust 工件已实现或部署；不得据此执行 F8 solver、worker、GPU/queue 或改动 gate/registry/ledger。R008 readiness、T1 数值资格与 credit 均不变。

F4 supportcap candidate v5 继续停留在 synthetic-only：Gaussian interface RMSE 相对 v3 仍退化 69.64%，因此没有启动已授权范围内的 CPU/native canary 预检；一次性预检授权未消费。
