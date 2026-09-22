# F8 Core scope decision packet（2026-09-22）

这是一个需要明确 root/user 裁决的静态 packet，不是 admission 或运行授权。
它绑定 PLAN、当前 F8 candidate card v2、static bundle v3、第三 T1 frontier
audit 和 Core completion state。

唯一问题：是否允许完全充满、非自由表面的
`body-force-driven oscillatory channel` 作为 Core 第三个机制家族？

- 选择“按机制家族接受”：只允许进入下一次独立 root review，仍不授权
  Definition/control、CPU/native、solver/GPU、queue、registry、ledger 或 training；
- 选择“Core 必须自由表面”：F8 保持 zero credit，转为 Core 之后扩展候选。

packet 不隐式选择任何一项，也不改变当前 `F3/F4`、T2=0、训练=0 的完成状态。
