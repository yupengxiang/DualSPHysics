# Core continuation status — 2026-09-27 — UPDATE-248

## F3 graph training/evaluation neighbor-cap binding

按当前 subagent 策略使用 `GPT-5.6 Luna`、reasoning `Max`，将 `max_neighbors` 从 profile-only 参数扩展到 `core_learning` 的训练、validation、milestone evaluation、checkpoint predictor 和 evaluate-checkpoints 参数链。默认仍为 `64`；训练 receipt/checkpoint config 记录实际 cap，resume 和 checkpoint predictor 不允许使用不同 cap 覆盖；缺少该字段的 legacy checkpoint 按默认 `64` 兼容。CLI `train --max-neighbors` 已接通。该改动没有放开 V13 verified-reader、formal admission、T1/T2、gate 或 credit。

新增 tiny regression 验证 cap=`3` 会写入 checkpoint 并由 predictor 恢复，resume/显式 cap 不匹配 fail-closed，legacy checkpoint 缺字段默认 64。`test_core_learning.py` 与 `test_core_models.py` 共 `74 passed`；连同 dataset/compact/benchmark/neighbor diagnostic 回归共 `137 passed`；CLI help、`py_compile` 与 `git diff --check` 通过。

本轮只运行 tiny synthetic training contract，没有启动真实训练、solver/worker/GPU/queue，也未修改生产 HDF5、registry、ledger、分母或历史 receipt。真实 F3 cap=192 profile 的 10-step diagnostic receipt 与 formal training 缺口保持不变。
