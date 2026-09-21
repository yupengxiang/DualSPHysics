# F5 WaveRunup 第三 T1 anchor 科学负结果（2026-09-21）

F5 的受保护 anchor 已经真实执行完成，随后用只读工具重新核对了 `Run.out` 和原生输出。solver 日志显示 `Finished execution (code=0)`，登记窗口为 `0–16.0 s`，原生输出 cadence 为 `0.02 s`，共有连续的 801 帧、11 个 gauge，且 `Excluded particles=0`。第一次 worker attempt 被标为失败的原因只是旧 cadence parser 读取了错误字段；[postrun-audit-v2](../campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor/20260921T061057-efc149b14810/product/postrun-audit-v2.json) 已在不重跑 solver 的情况下修正了这一执行分类。

科学审计仍然失败。固定 9 帧样本覆盖了首尾和中间时间点，在斜坡与 blocks 上观察到 **3,354 个实体穿透粒子帧**，以及 **1,435 条保存帧 chord crossings**；分量计数为 slope 891、blocks 2,463、piston 0、bottom 0。F5 的登记硬门要求这两个数量都严格为零，因此一个样本中的正值已经足以拒绝 anchor。样本报告明确标记为非全帧覆盖；本次没有继续消耗完整全帧解码来“证明”一个已经被硬门否定的 anchor。

因此该 anchor 的状态为 `completed_scientific_negative_anchor_sampled_geometry`，`T1_numerical=false`、`qualification_claim=none`、`matrix_credit=0`。事件阈值和外部 CIEMito 对照仍是诊断信息，不能覆盖几何硬失败；固定 15 行分母保持不变，其他 14 行未执行。没有 same-input retry，也没有修改 registry、科学 ledger 或 qualification matrix。原始 solver 产品、cadence 后审和 sampled scientific review 全部保留在 attempt 目录，压缩后的零 credit 证据见 [negative-evidence JSON](../campaigns/core-v1/evidence/f5-wave-runup-third-t1-anchor-negative-evidence-v1.json)。
