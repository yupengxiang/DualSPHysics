# Core continuation status — 2026-09-27 — UPDATE-243

## F3 bounded profile neighbor-cap parameter

按当前策略使用 `GPT-5.6 Luna`、reasoning `Max` 完成一个最小接口补丁：`core_models.tensors` 与 `ModelPredictor` 现在接受显式 `max_neighbors`，`core_learning profile` 增加 `--max-neighbors`，并在诊断输出中记录实际 cap。默认值仍为 `64`，旧调用保持兼容；该参数没有接入 `train_model`、checkpoint 合同、正式 rollout/admission 或 gate。

本地验证通过：`tests/test_core_models.py` 与 `tests/test_core_learning.py` 共 `71 passed`；加上 dataset/compact/benchmark 回归共 `122 passed`；profile CLI help、`py_compile` 和 `git diff --check` 通过。非法 cap 在 API 层 fail-closed，显式 cap 只影响 bounded profile/model-input 诊断。

该补丁只是为下一步真实 F3 cap=192 profile 提供可审计入口，不产生训练或资格信用；未修改 PLAN 之外的历史 receipt、生产 HDF5、registry、ledger、分母、solver/worker/GPU/queue 或 gate。
