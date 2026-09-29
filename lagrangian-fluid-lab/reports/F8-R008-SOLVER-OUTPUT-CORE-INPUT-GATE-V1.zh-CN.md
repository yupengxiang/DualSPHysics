# F8/R008 solver-output → Core input gate V1

本交付物补的是一个窄接口，而不是重复已有的 target-pin、syscall、trusted-worker 或 terminal 合同：现有 `f8_r008_core_trajectory_adapter_v1.py` 可以把已验证的 native-fluid table 写成 diagnostic Core trajectory，但此前没有独立的 canonical solver-output descriptor → Core input projection 层来约束 caller 传入的逐案例输出绑定。

实现 `scripts/f8_r008_solver_output_core_input_gate_v1.py` 只消费有界 canonical JSON bytes，不打开任何路径。它 fail-closed 校验：

- 固定 R008 qualification case、case/attempt/nonce 和 Definition/control/initial/configuration/parameter digest；
- 固定 D-stage manifest/table 相对路径、artifact role、大小上限与 SHA-256；
- 逐帧 `frames/Part_NNNN.bi4` 路径、连续 ordinal、单调 canonical binary64 时间轴、逐帧及总大小上限；
- fluid cohort 的 `case_np`、fluid count 和 ID-order digest 的双向绑定；
- Core trajectory schema 与严格 diagnostic/zero-credit boundary。

输出只是给未来已完成 B/C/D held-FD verification 之后使用的 input projection，不返回文件描述符、执行 capability 或资格结果。descriptor 仍是 caller-supplied claim，因此成功不等于文件存在、solver 真实生成、runtime trusted、terminal complete、native integrity 通过或 T1 资格成立。

验证：

- `tests/test_f8_r008_solver_output_core_input_gate_v1.py`：`11 passed`；
- `python -m py_compile`：script/test 通过；
- `git diff --check`：通过；
- report 与 `build_report()` 精确相等。

本闭环没有读取 production bundle/solver frame，没有调用 HDF5/BI4/native/solver/worker/GPU/queue，也没有 privileged probe；没有修改 PLAN、registry、ledger、denominator、gate 或 completion。剩余 blocker 是 producer-authenticated descriptor、实际 B/C/D bundle+held-FD source reader、trusted target/runtime/worker identity、terminal/native-integrity 与最终 T1 adjudication。
