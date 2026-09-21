# Core full-field / halo oracle 接口诊断 — 2026-09-21

本次只读诊断使用 8 个粒子的 CPU 小样例，直接调用现有
`core_learning.ModelPredictor.predict_step(previous, known, dt)`、
`core_models.DualIncrementModel.forward(..., centers=...)`、
`core_models.two_hop_halo`、`core_contract.commit` 与
`core_contract.updater_oracle`。样例使用固定 seed `17`、`graph_raw` 未训练模型、
`dt=0.1 s`、`h=0.016 m`，没有 optimizer、backward、GPU、trajectory reader 或正式训练。

诊断 receipt 是
`campaigns/core-v1/learning/core-fullfield-halo-oracle-diagnostic-20260921.json`，
SHA-256 为
`031166cd3a2d11b6ded2933e6c0f6909f940b2ea40ce3186afc5b1fd38d4621f`；其 closure
sidecar 同时保存在同目录。完整粒子轴为 `8`，中心分为四个两粒子 chunk，每个 chunk
保留完整 field neighbor table 和 exact two-hop halo；全场与分块预测的最大绝对误差为
`2.9802322387695312e-08`，commit 后位置误差相同量级、速度误差为 `0`，符合 CPU
float32 推理容差 `1e-7`。

privileged oracle 使用独立的 displacement 与 native `delta_velocity`：
`max(|displacement/dt - delta_velocity|)=0.038`，因此没有把速度增量错误地重建为
位移有限差分。`predict -> commit` 的位置和速度误差均为 `0`，公共
`updater_oracle` 也均为 `0`。向 `KnownInputs` 递归注入 `nested.future_state` 被
`ValueError` 拒绝，且 future state 没有传入 predictor。

该 receipt 明确 `diagnostic_only=true`、`training_excluded=true`、
`qualification_excluded=true`、`formal_release=false`、`formal_job_count=0`、
`formal_runs_counted=0`；registry/ledger 均未写入。实现
`scripts/core_fullfield_halo_oracle.py` 的 SHA-256 为
`9821a68dc3e485fa79c5b7b37e8b7f433943972f418e6ffa42103106404e1c0f`，测试
`tests/test_core_fullfield_halo_oracle.py` 的 SHA-256 为
`1312bf86a79c56e5d9e3eeb0f504fb9d497d45bce3558601d8f61668b2d15045`。

定向测试命令覆盖新 receipt/verifier 与既有 contract/model/learning 接口测试；结果为
**59 passed in 72.25 seconds**。该诊断只证明接口与 halo 分块合同，不计入 9 个正式
model-seed runs。
