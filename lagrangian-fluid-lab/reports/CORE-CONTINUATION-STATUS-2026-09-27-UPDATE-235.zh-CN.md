# Core continuation status — 2026-09-27 — UPDATE-235

## F3 real 32-case reader verification

按统一入口对真实 F3 开发 manifest 做了两次相同的只读 verify；第二次结果持久化在 [`F3-READER-VERIFY-2026-09-27.json`](F3-READER-VERIFY-2026-09-27.json)。固定 manifest SHA-256 为 `8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`，32/32 案例通过 source hash、known-input contract 和首/中/尾三个 transition oracle，逐案例 `transition_count=3`，总 wall time `66.32410485902801 s`。

该回执的 `full_temporal_scan=false` 是有意的：本轮完成粗粒度真实数据链路（reader、源文件哈希、身份轴、时间轴和代表性 oracle），没有对每个案例的 835 个 transition 做全场重算。`qualification_inferred=false` 保持不变；没有修改生产 HDF5、split、registry、ledger、T1/T2 credit 或 Core 分母。全时域 oracle、材料侧车和正式模型运行仍是后续独立任务。

同一轮没有启动 solver/worker/GPU/queue。系统 Python 的 h5py/NumPy ABI 问题没有影响仓库 `.venv` 入口；当前结果使用 `PYTHONPATH=. .venv/bin/python` 生成。
