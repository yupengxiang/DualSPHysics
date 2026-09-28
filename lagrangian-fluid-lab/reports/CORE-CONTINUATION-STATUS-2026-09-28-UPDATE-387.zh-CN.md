# Core continuation status — UPDATE-387（2026-09-28）

## 三个新证据组件的独立安全复核

本轮只读复核了 residual process-proof builder、MLP diagnostic launcher、graph_raw terminal runtime verifier 及其测试；没有编辑、提交、启动/停止/重启 evaluator，也没有打开 live evaluation、progress、checkpoint、trajectory/HDF5。

基础回归：builder `18 passed`、MLP launcher `9 passed`、graph_raw verifier `19 passed`；三脚本 py_compile 和三个提交的 diff-check 均通过。

复核发现：

- P1：MLP `build_process_exit_proof()` 只检查任意正 PID/returncode，缺少真实 Popen/wait provenance；
- P1：MLP build plan 到 execute 之间对 interpreter/script/manifest/checkpoint 的输入 identity 存在 TOCTOU；
- P1：graph_raw `validate_report()` 只验证外层状态，可接受三 seed `evidence={}` 的伪造正报告，process envelope 也过度信任 PID/returncode；
- P2：residual command 只按 basename 识别 `core_learning.py`，command digest 未进入 normalized proof；artifact SHA 是 producer 自报；
- P2/P3：MLP 全零 nonce、MLP 路径父目录竞态、raw JSON array 缺少显式元素上限。

当前所有组件仍强制 `diagnostic_only=true`、`formal=false`、`T1/T2/qualification=false`、`credit=0`，因此没有 formal credit 直接提权；但在修复 P1 前，不能把任何 runtime verifier 的正状态解释为可信终态。修复任务已拆为三个互不重叠的独立提交，现有 17 条 live evaluator 不受影响。

