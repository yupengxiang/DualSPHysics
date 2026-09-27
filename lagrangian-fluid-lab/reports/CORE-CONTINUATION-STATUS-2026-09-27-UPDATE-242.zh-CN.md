# Core continuation status — 2026-09-27 — UPDATE-242

## F3 synthetic two-hop provenance/capacity diagnostic

按当前 subagent 策略使用 `GPT-5.6 Luna`、reasoning `Max` 完成了一个严格 synthetic-only 的 F3 邻居 provenance 诊断，代码与测试分别位于 `scripts/f3_neighbor_provenance_diagnostic_v1.py` 和 `tests/test_f3_neighbor_provenance_diagnostic_v1.py`。诊断不读取真实 HDF5，不依赖 `core_models.py`，因此不会把 synthetic 结果误当成生产验证。

专项测试覆盖：默认 cap=`64` 的 required-row 截断 fail-closed、提高到 cap=`65` 后完整 provenance、非 required 行截断的显式状态、非法 cap、缺失 provenance 和不完整 provenance 负例；canonical JSON 还固定 `diagnostic_only=true`、`formal_training=false`、`T1=false`、`native_integrity=false`、`gate=false`、`credit=0`。专项及相邻 `core_models`/periodic graph/full-field halo 回归共 `35 passed`，`py_compile` 与 CLI canonical JSON 检查通过。

该结果只闭合了接口诊断边界：提高 cap 在制造图上可以恢复完整性，但不授权修改生产 cap，也不授予 T1/T2 或训练资格。真实 F3 frame 0 的 cap sweep、真实 profile blocker 和全局 Core 缺口保持不变；未修改 formal validator、历史 receipt、生产 HDF5、registry、ledger、分母或 gate，未启动 solver/worker/GPU/queue。
