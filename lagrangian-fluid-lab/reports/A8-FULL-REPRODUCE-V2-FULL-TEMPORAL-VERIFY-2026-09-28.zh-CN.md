# A8 reader bundle v2 全时域验证回执

- 状态：`passed=true`
- 注册案例：`32/32`
- 全时域：`full_temporal_scan=true`
- 每案例 transition：`835`
- 通过案例：`32/32`
- `qualification_inferred=false`
- 用时：`3536.6901789649855 s`
- manifest SHA-256：`7da606f7177e0bb607af5d31b53ed122cd4ca88527c90c5e9fe698c0c3d892e4`
- bundle.json SHA-256：`da0fdcdc10ed56e47e94eb70dfecf864808337d3b7cf9e2d3e22c14df5e6c5ed`
- 验证 JSON SHA-256：`5fa16cda177ed40fadb068e0d742cb7206953db36ecdf96efefadb99c4562971`
- 验证 JSON bytes：`10427775`

## 执行边界

验证命令为：

```text
code/scripts/core_benchmark.py verify --manifest dataset.json --data-root . --full-scan
```

执行根目录是 `campaigns/core-v1/reproduction/a8-full-reproduce-v2`。本次只读打开 reader 数据并重算每个注册案例的完整时间轴 oracle；没有打开 checkpoint、没有执行训练/预测/solver/worker/GPU，也没有写 registry、ledger、denominator 或 qualification gate。

该回执闭合 A8 reader/data full-temporal integrity 层，不等价于模型复现、异机复现、正式训练或 T1/T2/qualification credit；`qualification_inferred` 保持 false。
