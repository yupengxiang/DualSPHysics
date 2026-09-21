# Core model / rollout contract 补强 — 2026-09-21

本次工作只补强学习接口基础，没有启动训练、GPU、solver 或 queue，也没有修改
Core registry、ledger、T1/T2 分母或 F6 canary。

现行接口固定为：预测器的 `predict_step(state, known, dt)` 只接收当前已提交
`State`、不可变 `KnownInputs` 和正的时间间隔，并返回包含独立
`displacement` 与 native `delta_velocity` 的 `StepPrediction`。唯一公开提交路径是
`commit`；旧的 `apply_prediction` 只是兼容别名。`CausalPredictorAdapter` 对任意
预测器执行相同的返回值、形状、有限性和时间间隔检查。

`reference_displacement_oracle(previous, following)` 只在特权评分边界由连续参考帧
生成位移和 native 速度增量，然后复用 `commit`。它不把 `displacement / dt` 当作
速度，也不把 following state 传入 predictor。既有 `updater_oracle` 和 autonomous
rollout 已切换到这条统一更新路径。

新增回归覆盖：

- adapter 的 current-state-only 调用签名和 `Predictor` protocol；
- `commit` 与旧 `apply_prediction` 的等价性；
- reference displacement 与 native velocity 增量的独立性及 oracle 精确回放；
- predictor 在读取下一帧参考状态之前被调用；
- 非 contract 输出和非推进时间间隔的拒绝。

定向验证命令：

```bash
./.venv/bin/python -m pytest -q tests/test_core_model_rollout_contract.py
./.venv/bin/python -m pytest -q tests/test_core_contract.py tests/test_core_models.py
```

两组测试分别通过 `5 passed` 与 `23 passed`。这份记录是接口诊断，不构成模型训练
或科学资格证据。
