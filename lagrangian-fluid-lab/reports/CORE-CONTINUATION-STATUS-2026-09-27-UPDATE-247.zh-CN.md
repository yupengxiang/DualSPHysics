# Core continuation status — 2026-09-27 — UPDATE-247

## F3 precision-isolated provenance validation: 10-step profile passes

在 UPDATE-246 暴露 step 5 distance mismatch 后，修复 formal graph 输入的精度边界：`tensors` 保留 State 的 float64 position，`DualIncrementModel.forward` 用该原始坐标做 provenance distance validation，同时将独立的 compute position 转为 float32 做 graph message arithmetic。没有放宽 `allclose` 容差、删除 validator 或忽略 mismatch。

修复后的真实 F3 `F3_DEV_00_a0p903125` profile 使用 `graph_raw`、seed `17`、hidden `16`、full chunk `34,560`、cap `192`、CPU、10-step autonomous state feedback，成功完成 `10/10`。step wall 为 `20.6275–30.1987 s`，mean=`25.815490224189126 s`，p95=`30.130237200262492 s`，peak RSS=`4421.64453125 MiB`；输出和源绑定见 [`F3-MODEL-PROFILE-CAP192-STEP10-FIXED-2026-09-27.json`](F3-MODEL-PROFILE-CAP192-STEP10-FIXED-2026-09-27.json)。

回归通过：core model/learning/graph 80 passed，dataset/compact/benchmark/learning/model/neighbor diagnostic 基线 135 passed，`py_compile` 与 `git diff --check` 通过。该成功仍是 diagnostic-only，不是训练或 T1/T2 资格；没有 checkpoint、生产 HDF5、registry、ledger、分母、gate 或 solver/worker/GPU/queue 副作用。下一步可在同一接口上做更长 bounded profile 或训练资源/正式 admission 的独立设计，但不能把这 10-step 结果升级为正式证据。
