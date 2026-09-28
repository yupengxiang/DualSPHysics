# F3 graph_residual hidden16 current-manifest full835 rollout contract

- 状态：`blocked_fail_closed`
- 范围：固定 current canonical manifest、`graph_residual`、hidden16、500 updates、case `F3_DEV_00_a0p903125`、test split、835 transitions / 836 frames、seed 17/29/43。
- 每个 seed 要求显式 v3 training/checkpoint identity、非零 32-hex fresh nonce namespace 和 canonical command digest。
- 默认 `launch_allowed=false`；当前实现不启动、停止或重启进程。未来只有独立受审计 execute capability 才能接入执行器。
- terminal verifier 只读取有界 receipt JSON，并对声明产物做元数据检查；不打开 checkpoint、HDF5、trajectory、evaluation 或 progress 内容。
- formal、T1、T2、qualification、credit 均保持 `false/0`。

当前没有受本 contract 绑定的 terminal receipt，因此不产生 runtime completion 或任何资格 credit。
