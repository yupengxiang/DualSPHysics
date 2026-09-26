# UPDATE-195：训练独立进程 kill/resume 全状态一致性

时间：2026-09-26（Asia/Shanghai）

## 本次推进

先按计划复核评测失败分母：锁定项目 Python 运行时的 7 个定向用例通过，覆盖 NaN/提前发散、`TimeoutError` 与 `subprocess.TimeoutExpired`、短时域缺失尾帧，以及 setup failure 的固定分母。该项现有实现和测试已闭合，本次没有重复修改。

随后加强 Core 训练真实进程中断回归。子进程在原子 checkpoint 可读后由父进程 `SIGKILL`，新进程恢复到相同终点；现在除模型权重与 history 外，还逐项比较 optimizer 参数组/状态张量、sampler RNG/抽样计数、归一化、Python/NumPy/Torch RNG，以及 validation/history。合成夹具新增独立 validation case，确保四条验证记录确实进入恢复比较。连续执行对照与真实进程用例 **2 passed**；评测分母定向用例 **7 passed**。运行使用锁定 Python 3.12 环境、CPU，并禁用 CUDA。

## 边界与剩余工作

该测试验证进程被杀且原子 checkpoint 已持久可读时的训练恢复等价，不模拟断电、内核崩溃或存储设备缓存丢失；小型四步合成训练不替代正式 32k 更新、9 次正式运行或规模化资源测量。Core 的训练、T1/T2 资格、完整 held-out 评测与异机产品复现仍未完成。
