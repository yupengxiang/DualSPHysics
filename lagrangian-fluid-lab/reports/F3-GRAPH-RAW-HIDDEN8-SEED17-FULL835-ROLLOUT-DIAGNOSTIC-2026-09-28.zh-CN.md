# F3 graph_raw hidden8 seed17 full835 rollout diagnostic

- 报告 ID：`F3-GRAPH-RAW-HIDDEN8-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28`
- 状态：完整 autonomous diagnostic rollout；不是 formal/T1/T2 资格证据。
- 训练：500/500 updates，hidden=8，参数量 1766，checkpoint verified。
- 评测：835/835 transitions，836 frames，HDF5 validator passed/complete，raw coverage=1。
- 输入隔离：future-state inputs=false；质量误差=0 kg；validity mismatch=0。
- 结论：长时域误差累积，故为 diagnostic negative；qualification/T1/T2=false，credit=0，未修改 registry、ledger、denominator 或 gate。

## 关键结果

| horizon | position RMSE (m) | velocity RMSE (m/s) |
|---:|---:|---:|
| 1 | 0.000210 | 0.001353 |
| 10 | 0.002416 | 0.006954 |
| 50 | 0.010809 | 0.050800 |
| 100 | 0.026783 | 0.049459 |
| 200 | 0.103640 | 0.124895 |
| 400 | 0.502160 | 0.853872 |
| 600 | 1.448731 | 2.799018 |
| 700 | 2.514813 | 4.909581 |
| 800 | 5.526082 | 11.323184 |
| 835 | 7.024502 | 14.443016 |

step 50：position RMSE `0.010808855234180976 m`，velocity RMSE `0.05080001907864858 m/s`。

step 835：position RMSE `7.0245020288875075 m`，velocity RMSE `14.443016181997502 m/s`；最大 kinetic-energy error `4511.601056360172 J`。

## 绑定与验证

- manifest SHA-256：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；case HDF5 SHA-256：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`。
- checkpoint/training/evaluation 路径与 SHA-256 已精确绑定。
- 训练 neighbor truncation=0；trajectory finite、valid 全 true、mass static。
- HDF5 validator：`d29f0985e148924a0fc3e3dbed8501cc1f65e1dc4d44b1485968bc9b9bab1564`；metric summary：`eff0832c1ccccbcb525d961d6f4363c5a1fd099ccdc022e16eb50b4b8bf810ae`。

## 产物 SHA-256

| artifact | SHA-256 |
|---|---|
| checkpoint_sha256 | `2da3c11c7f2e118063e54184f8e27c9ff3f8da04bff90295fd275c785949573a` |
| training_receipt_sha256 | `4914d816e865f156945e06161ba3f973bd6801529ada1978626dbb08a024924e` |
| training_progress_sha256 | `74e5d83b5b02a7ad8e8c2af62ca51c2780c49971a2a85335665def7f5b4cd6d4` |
| evaluation_receipt_sha256 | `2ade392f2843f6e78fcb3d3025c4145fcfd645871feec786df61c1ba1516428b` |
| evaluation_progress_sha256 | `e5e131d80a4bf0a23b74fa83f9c00be7aef8efb0cf41bb28d118c65b2ab27b7e` |
| trajectory_sha256 | `0d10fa37ceeed033effb7ba1f0ba561e649e953f403496cdd8fbbd14d3e60bdf` |
| hdf5_validation_sha256 | `d29f0985e148924a0fc3e3dbed8501cc1f65e1dc4d44b1485968bc9b9bab1564` |
| metric_summary_sha256 | `eff0832c1ccccbcb525d961d6f4363c5a1fd099ccdc022e16eb50b4b8bf810ae` |

详细机器报告：[JSON](F3-GRAPH-RAW-HIDDEN8-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json)。
