# Core continuation status — 2026-09-27 — UPDATE-246

## F3 cap-192 autonomous profile: provenance distance precision blocker

在真实 F3 full-chunk/cap=`192` profile 上尝试 10-step bounded autonomous 窗口。step 1–4 成功；第 5 步在进入下一次 graph 输入时，以 `ValueError: neighbor provenance distance does not match position` fail-closed，output 不存在。失败前 state time 为 `0.04001995865810541 s`，位置范围为 `0.19172677397727966…1.0890281051397324`；捕获 traceback 绑定在 [`F3-MODEL-PROFILE-CAP192-STEP10-BLOCKED-2026-09-27.json`](F3-MODEL-PROFILE-CAP192-STEP10-BLOCKED-2026-09-27.json)。

这不是 cap 截断或 OOM：cap=192 的当前邻居表已足够，RSS 也未越界。根因边界是 `neighbor_table`/provenance 以 float64 位置计算距离，而 `tensors` 为模型输入转成 float32；autonomous 更新后绝对坐标增大，严格距离回验首先在 step 5 暴露精度差异。下一步只隔离“validator 使用原始 float64 坐标、模型消息计算仍使用 float32”的修复，并保留 fail-closed 语义；不放宽容差、不删校验、不改变 gate/credit。当前仍未训练、未创建 checkpoint、未修改生产 HDF5/registry/ledger/分母，也未启动 solver/worker/GPU/queue。
