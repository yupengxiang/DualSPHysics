# UPDATE-210：F8 terminal completion contract v5 复审与 v6 修订

时间：2026-09-26（Asia/Shanghai）

## V5 独立复审

Terra High 配置 reviewer 对 V5 的有效只读复审结论为 REVISE、无 P0；reviewer 未能独立 attestate 模型身份。它确认以下旧问题的处理正确：registry 的自身 hash 已从 signed registry 移出；正时长/末次主循环保存、DsphConfig 自动输入、argv/input trace 和零执行/零信用边界未回退。BI4 标头偏移也与 JBinaryData v5.4 writer 一致。

仍有实现阻塞：

- **P1：** termination_watch 要求 child exit 后出现 seal event，同时又拒绝所有 child exit 后的 event，形成不可能通过的条件。
- **P1：** seal 仍是 supervisor 声明；缺少签名的原始 mount/cgroup/task/FD/mount_setattr/只读状态证据、sealed-tree manifest schema 与 watcher ID 交叉绑定，不能机械地区分真实封存和自述。
- **P1：** task policy 固定 registry payload SHA，却允许更高 registry sequence 更新，外部固定哈希与动态更新冲突；外部 policy 自身也缺 exact schema/更新边界。
- **P2：** locale wrapper 未记录 ABI-level category、locale_t handles、dlsym/dlopen module/symbol/flags 与 thread-start 细节。
- **P2：** BI4 仍将闭合 grammar 仅写成 profile hashes，且未区分官方 native reader 的 host-endian 限制与 sidecar parser 能力。

## V6 additive proposal

新增 [terminal completion contract v6](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V6-2026-09-26.zh-CN.md)，保留 v1–v5 为历史版本。V6 规定一个 root-key 签名的外部 task policy 与单一 registry snapshot；registry 不在 attempt 内滚动更新。child exit 后只容许一个非文件变更 seal control event，文件变更仍全部拒绝。增加可交叉核对的原始 kernel observation 对象、签名 output-seal evidence、cgroup/task/namespace-FD/FD 扫描、mount_setattr 记录、fanotify actor 记录与目录/文件 sealed manifest。

V6 进一步为 locale wrapper 定义 ABI union 和线程登记；BI4 固定为经 GetByteOrder 观测后才接受的小端/SI64=0 的独立 sidecar profile，明确不声称官方 native reader 支持跨 endian。按本地 writer 源码修正了草稿误分类：BoundNor 属于独立 PartExtra，而非 main PART；终态 main PART 数组限于 Idp/Posd/Vel/Rhop。V6 当前正由 Terra High 配置 reviewer 对完整文本与源码片段做只读审查；其 verdict 尚未返回，不能记 PASS。

仅新增合同文本及静态源码核对；git diff --check 通过。无生产 bundle/HDF5/PART/BI4 访问，无 GenCase/native decoder/solver/worker/GPU/queue，无 registry/ledger/gate/scope/分母更改。R008 仍 readiness=false、T1_numerical=false、credit=0。

F4 supportcap synthetic-only 结果见 [UPDATE-209](CORE-CONTINUATION-STATUS-2026-09-26-UPDATE-209.zh-CN.md)：v5 blend 在界面场退化，未消费获准的一次新候选 CPU/native preflight。
