# Core continuation status — 2026-09-27 — UPDATE-237

## F8 R008 bounded RunPARTs/RealStr/OutputTime cadence diagnostic v1

按 GPT-5.6 Luna Max 对 native-integrity proposal v7 的 raw cadence 要求，新增 [`f8_r008_runparts_realstr_cadence_diagnostic_v1.py`](../scripts/f8_r008_runparts_realstr_cadence_diagnostic_v1.py) 及合成测试。输入只接受有界 UTF-8 `RunPARTs.csv` bytes，保留每个原始 CSV/`RealStr(TimeStep)` token，并以 binary64 值执行 stateful `OutputTime` recurrence；覆盖 simple/special 多 cadence crossing、`T_end`/overshoot、无 final `SaveData`、重复/非递增/NaN/Inf、跨 attempt 和边界超限负例。

专项测试 **21 passed**；与现有 RunPARTs timestep、PartOut diagnostic 和相邻 F8 合同联合回归 **117 passed**；`py_compile`、`git show --check` 通过。该模块的成功状态仍为 `synthetic_structural_untrusted`，明确 `source_authenticated=false`、`runtime_authenticated=false`、`native_integrity_evaluated=false`、`T1_numerical=false`、`gate_decision_eligible=false`、`qualification_credit=0`。

本轮未读取生产 HDF5/RunPARTs 文件，未运行 native/solver/worker/GPU/queue，也未修改 gate、registry、分母或历史 receipt。真实 `RealStr` 生成、attempt/source 身份、运行时 `OutputTime` 配置、正常终止、writer flush/close 和 native integrity 仍未认证；因此该诊断不产生 F8 T1 信用。实现提交为 `d46391a0`。
