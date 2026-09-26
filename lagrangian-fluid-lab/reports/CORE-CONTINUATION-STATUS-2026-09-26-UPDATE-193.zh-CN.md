# UPDATE-193：F3 model-material v2 独立进程 SIGKILL 恢复 parity

时间：2026-09-26（Asia/Shanghai）

## 本次推进

补上 PLAN 中“独立进程 kill/resume 后与连续执行一致”的合成验证。新测试先在父进程生成连续参考 trace；另起 Python 子进程运行同一小型 synthetic case，并在首个 RK 子步的行数据、checkpoint、hash-chain commit 与 `committed_rows` 已更新后暂停。父进程对该子进程发送 SIGKILL，确认退出码为 `-SIGKILL` 且 trace 显示两行有效提交；再启动全新 Python 进程以 `resume=True` 恢复。恢复后的 HDF5 dataset、journal 内容及科学摘要与连续执行相同。

完整 `test_f3_native_volume_mls_model_material_v2.py` 合成套件 **11 passed**，包含新增独立进程测试；上一轮 profiler suite **4 passed**。无生产 HDF5/solver/worker/GPU/queue 输入或运行，资格声明与 T2 状态不变。

## 边界与剩余工作

该测试验证进程被杀后，操作系统仍运行且 HDF5 文件保持可读时，在已提交行边界的恢复；不模拟断电、内核崩溃、存储设备缓存丢失或 HDF5 元数据损坏。真实 F3 全源/全时域材料执行、正式材料资格与全局 Core 目标仍未完成。
