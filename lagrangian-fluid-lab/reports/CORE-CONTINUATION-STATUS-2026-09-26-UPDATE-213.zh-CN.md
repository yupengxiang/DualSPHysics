# UPDATE-213：F8 V13–V16 合同推进、A8 可移植性修复与 Core 状态复核

时间：2026-09-26（Asia/Shanghai）

## F8 terminal completion evidence

Terra High 配置对 V13 的只读复核为 `REVISE`、无 P0，reviewer 未 attestate 模型身份。P1 主要指出：`io_token` 只是证据而非执行 gate；syscall/ptrace/seccomp 次序和 task census/copy-out 缺少可审计状态图；syscall exit 后 fanotify drain 不能证明 deferred final-fput 已结束；fanotify 分组不能构成 kernel global order；native copy-out 仍可能遭外部 mm writer/userfaultfd；完整冻结 syscall-number/argument/predicate policy 及 maps 原始行闭合尚未落成。

Terra High 配置对 V14 独立只读复核为 `REVISE`、无 P0，身份未 attestate。P1 指出：旧版 USER_NOTIF/ADDFD/pidfd_getfd 条款未被精确 supersede；ptrace skip/return、signal/restart/exec/clone 状态未封闭；virtual-FD 与不同 mm 共享 files_struct、copy-out 授权不完整；`__fput`/fanotify event 的 object-generation join 不足；permission event 的 event-FD 生命周期、fanotify group UAPI mask/actor 尚未精确定义；`KCMP_VM` 是已枚举任务 pair 的比较器而非 peer 搜索器。P2 指出 token 缺 `token_kind`/精确 nullability；完整逐号 profile 仍只是前置件。

Terra High 配置对 V15 只读复核亦为 `REVISE`、无 P0，模型身份未 attestate。P1 指出 supersession matrix 不完整；`PTRACE_SYSEMU` register/return/signal transition 不够精确；placeholder FD 的真实预置/编号安装、全量 task/files/mm lineage census、fanotify exact mask/scope/event-FD join 与 final-fput cookie/refcount/loss join 仍不足。P2 指出 terminal token subtype/causal parent 与 supervisor copy 权限记录缺失。复核后将 V15 placeholder-pool 机制补入工作稿，随后由 V16 全面替代这轮运行机制设计。

新增 [terminal completion evidence contract V14](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V14-2026-09-26.zh-CN.md)、[V15](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V15-2026-09-26.zh-CN.md) 与 [V16](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V16-2026-09-26.zh-CN.md)。V16 加入逐版本/章节效力矩阵、target syscall 与 terminal/seal token 的分型和 causal parents、通过 `orig_rax=-1` dummy syscall 返回 stop 的 x86-64 suppression ABI、trusted launcher ancestry/cgroup birth closure、exec 前固定 descriptor pool、逐项 fanotify group mask/FID/PIDFD/event-FD profile，以及单 backing OFD 的 file-cookie/refcount observer join。V16 Terra High 独立审查待回。完整 hash-pinned syscall generator/table/predicate artifact、可信 supervisor、fanotify responder 与 final-fput observer 均不存在，因此 runtime-readiness 继续 false，不能接入 qualification gate。

只读检查到本机安装的 generated x86-64 UAPI header `unistd_64.h`（`__NR_syscalls=462`，SHA-256 `4b97d57bc894b6505218da84fe2aebb950e732230ada3d1af74326171dc6128b`）；搜索的 kernel headers 中没有对应 `syscall_64.tbl`。该本机文件未被当成 DualSPHysics 支持 profile，也未生成/登记 syscall policy、predicate proof 或运行时能力结论。

## A8 portability / diagnostic gate

- `core_benchmark` 对显式 case selection 永远不签发 `full_product_reproduction=true`；paired cross-host 结果单列为 diagnostic，`core_campaign` 拒绝将该 diagnostic marker 升格为 prediction completion。
- reader smoke report 移至 bundle 外的临时目录，验证前后重验 immutable bundle；bundle tree verifier 拒绝 symlink、special、未登记/缺失文件与目录。bundle 和 reproduction 使用统一的 runtime code closure，覆盖 `core_package` 等动态依赖。
- 新测试保留历史单案例 diagnostic 记录的原样语义，未改写任何历史 campaign/registry/ledger 数据。
- 锁定项目 Python 3.12 环境执行 Core benchmark/package/campaign suites：**78 passed**；F4 v6 synthetic-candidate suite：**4 passed**；`git diff --check` 通过。

## F4 v6 candidate 与总控

F4 v6 仍为 synthetic-only negative candidate：使用原 analytic calibration corpus 调过的 regularization 参数，不构成独立验证；候选 gate 重算出现 3,680 个 v3-pass/v6-fail regression，`preflight_recommendation=not_justified`。本轮未启动 CPU/native canary；该一次性预检授权未消费。

只读 `core_campaign.py status` 仍为 `can_finalize=false`、`issues=[]`、T1 家族 F3/F4（2/3）、macro T2 0/2、正式训练 0/9；固定目标 T1 尚缺 432、材料尚缺 288、独立全产品复现 false。没有运行 GenCase/native/solver/worker/GPU/queue，没有写 registry/ledger/completion snapshot，也没有给候选或 F8 文件任何资格信用。

本轮仅对 A8/F4 synthetic code 执行离线回归，其余为静态文档审查；未执行 root/sudo 操作、host capability probe 或生产数据读取。F8 的真实可信执行来源和完整 15-case solver evidence、第三 T1 家族、T2 路径、正式训练及独立全产品复现仍未完成。
