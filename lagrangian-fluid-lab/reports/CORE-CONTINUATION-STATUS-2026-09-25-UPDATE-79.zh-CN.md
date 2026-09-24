# Core 计划续推状态 UPDATE-79

日期：2026-09-25（Asia/Shanghai）

## 本次完成

为 V8 consumer 清单中的 native-fluid gate reducer 增加 `test_synthetic_verification_mapping_rejected_before_reduction`。临时 synthetic HDF5 table 配合三种输入：裸 exact V8 Diagnostic、带完整 table-verification 字段的 synthetic 重包装，以及仅将有效 verification 的 schema 替换为 V8 schema。测试分别断言缺 case identity、exact-field mismatch、schema/zero-credit verification 错误；`_reduce_window` sentinel 确保未进入 density/Mach/window gate reduction。

## 复核与验证

- 仓库 `.venv` 下完整 `tests/test_f8_r008_native_fluid_gate_reducer_v1.py`：13 passed。
- 指定 Terra High/high 静态复核确认 schema relabel 在 HDF5 `fstat`/打开及窗口采样前拒绝，FD 在 `finally` 关闭；无独立身份/effort attestation，不作为可审计身份或资格证明。

## 边界与未完成项

fixture 只在 pytest `tmp_path` 写入 synthetic HDF5。该测试仅证明 Diagnostic/重包装/schema relabel 不进入 reducer；不认证 producer、raw bytes、签名、可信根或 runtime，也不能阻止伪造正确 table-verification schema 的 mapping。native integrity/T1 最终判定仍独立且未关闭，R008 gate open、`T1_numerical=false`、零资格信用；未访问 production bundle/solver frame，也未运行 GenCase/native/solver/worker/GPU/queue。
