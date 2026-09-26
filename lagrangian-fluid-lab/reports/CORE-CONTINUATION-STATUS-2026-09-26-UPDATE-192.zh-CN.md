# UPDATE-192：F3 model-material v2 profiler 记录产物大小

时间：2026-09-26（Asia/Shanghai）

## 本次推进

补齐 UPDATE-191 合成阶段 profiler 的产物大小记录：在临时目录清理前读取 synthetic source HDF5 与生成 trace HDF5 的实际字节数，并将 `source_file_bytes`、`trace_file_bytes` 与各自 SHA-256 一同写入 profile 结果。没有改动模型积分、trace 格式或资格语义。

新增断言验证微型 model-provider profile 返回正整数文件大小。v2 profiler 专项 **4 passed**；真实执行只使用测试内 4 seeds × 64 particles × 1 interval 的临时合成数据。`py_compile` 与 `git diff --check` 通过。

## 边界与剩余工作

这些字节数仅是微型 synthetic fixture 的实测，不可推算为 F3 生产输出大小。默认 512 × 4096 × 20 synthetic profile 仍须通过 load gate 后执行；本轮主机 1 分钟负载高于 process-visible CPU capacity 时不运行默认 workload。真实 F3 全源/全时域 profiling、独立进程中断恢复 parity 与正式材料资格仍未完成；没有读取生产 HDF5、启动 solver/worker/GPU/queue、改动 ledger/registry 或产生资格信用。
