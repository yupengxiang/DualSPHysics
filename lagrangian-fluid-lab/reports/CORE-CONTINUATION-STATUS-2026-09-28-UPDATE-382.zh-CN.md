# Core continuation status — UPDATE-382（2026-09-28）

## F3 MLP hidden16 fresh full835 diagnostic rollout

本次启动只为补齐后续 terminal runtime verifier 所需的真实运行链，不能替代 Core 正式训练、T1/T2、异机复现或任何 qualification credit。

| seed | GPU | fresh nonce | namespace | launch state |
|---:|---:|---|---|---|
| 17 | 0 | `b5f8d1a3c7e90426d8a1f3b6c9e2074a` | `/tmp/f3-mlp500-hidden16-seed17-full835-nonceb5f8d1a3c7e90426d8a1f3b6c9e2074a-*` | running at launch |
| 29 | 1 | `e2c6a9047b1d3f85a8e0c2d6f9b4173a` | `/tmp/f3-mlp500-hidden16-seed29-full835-noncee2c6a9047b1d3f85a8e0c2d6f9b4173a-*` | running at launch |
| 43 | 2 | `f7a3d0c9e5b21864a1f6d8c3b0e9472a` | `/tmp/f3-mlp500-hidden16-seed43-full835-noncef7a3d0c9e5b21864a1f6d8c3b0e9472a-*` | running at launch |

固定合同为既有 `f3-dataset-v2`、case `F3_DEV_00_a0p903125`、split `test`、`maximum-steps=835`、`chunk-size=34560`、`--diagnostic`。三份 checkpoint 均来自已绑定的 MLP hidden16 seed17/29/43 training evidence matrix。输出只写入各自 fresh `/tmp` namespace；不覆盖旧 rollout。

## 边界

- 启动时显存充足；启动后只能通过进程自然退出判断终态，不能把 PID、进度文件或仍在增长的 trajectory 当作完成。
- 当前不记录 evaluation/HDF5 内容；进程退出后才允许读取小型终态 JSON，并必须运行独立 HDF5 validator。
- 需要的证据类别仍是 training matrix、rollout identity、evaluator/launcher process-exit proof 和独立 validator receipt 四类同时闭合。
- `diagnostic_only=true`、`formal=false`、`T1_numerical=false`、`T2_macro=false`、`qualification=false`、`credit=0`；Core registry、ledger、denominator、gate、completion 均未修改。

此前一次用错误相对路径的启动尝试在 dataset manifest 打开前退出，未创建输出，不属于上述 namespace，也不作为运行证据。

