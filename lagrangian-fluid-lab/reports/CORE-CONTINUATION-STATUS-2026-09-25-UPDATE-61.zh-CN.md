# UPDATE-61：F8 solver build/source provenance 静态盘点

日期：2026-09-25（Asia/Shanghai）

只读盘点 standard `src/source` 与独立 `src_mphase/.../NNewtonian` 的 Make/CMake targets，发现 CPU/GPU/构建系统选择会改变宏、flags、CUDA arch 和最终路径；标准构建文件的版本注释又与 `main.cpp` 版本常量不一致。非牛顿路径是独立 v5.0.164 源码/target，不能用作 R008 lineage。`bin/linux` 当前没有任何 DualSPHysics solver target；若未来按默认输出位置构建，现存 `DsphConfig.xml` 会被 solver 从 executable-parent 自动读取。静态 build definitions、追踪到的库 hashes 均不能证明某个运行 binary 是如何产生或实际加载了什么。

详见[构建来源审计](F8-R008-SOURCE-BUILD-PROVENANCE-STATIC-AUDIT-2026-09-25.zh-CN.md)。本次未调用构建器或 solver，未读取 production 轨迹，未运行 native/GenCase/worker/GPU/queue；execution trust root/source-to-binary 仍 open，R008 T1 false、零信用。
