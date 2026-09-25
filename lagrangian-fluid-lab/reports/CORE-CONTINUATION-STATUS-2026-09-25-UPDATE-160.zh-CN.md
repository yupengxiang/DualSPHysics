# UPDATE-160：DualSPHysics CPU 隔离 CMake 构建闭合

时间：2026-09-25（Asia/Shanghai）

## 本轮修复

`src/source/CMakeLists.txt` 现保留 `bin/linux` 等历史默认输出目录，同时允许 `CMAKE_RUNTIME_OUTPUT_DIRECTORY` 将产物重定向到独立目录；MoorDynPlus target 依赖仅在启用该可选组件时添加；GNU CPU target 使用 GCC 支持且与仓库 CPU Makefile 一致的 `-ffast-math`，CUDA target 仍保留 CUDA 专用选项。`src/source/JBinaryData.h` 显式包含 `<cstdint>`，为现有 `SIZE_MAX` 用法提供标准定义。

## 构建与核验

环境为 Conda `neural_lagrangian_solver`，CMake 4.3.0、GNU C++ 13.4.0。CMake 4 读取项目旧 `cmake_minimum_required(VERSION 3.0)` 需要显式传 `CMAKE_POLICY_VERSION_MINIMUM=3.5`。隔离 Release CPU 配置关闭 CUDA、Chrono、WaveGen、MoorDynPlus，并把 binary 输出到 `/tmp/dsph-cmake-cpu.rxEH5w/out`。目标 `DualSPHysics5.4CPU_linux64` 完整编译并链接成功（exit 0，100%）；另一个未指定输出覆盖目录的 configure-only 检查成功，其生成规则仍指向传统 `bin/linux` 路径，且未在仓库内生成 binary。

产物由 `file`/`readelf` 静态识别为 x86-64 ELF64 PIE 普通文件，大小 30,907,968 字节、单链接；SHA-256：`ab71a0d55cb0bcb4e6aff5374c8ddb1aaf33ca5f86e18d2a6b953f385322c61b`。没有执行 binary，也未运行 GenCase、native decoder、solver、worker、GPU 或 queue；该通用 CPU binary 不是 R008 invocation/source/runtime provenance，也不提供任何资格信用。

`git diff --check` 通过。Terra High 独立审查尝试被当前 Codex 账户的模型可用性策略拒绝，review agent 未读取项目内容，因此本轮不声称独立审查 PASS；保留本地代码检查与实际隔离编译结果作为验证。

源码 SHA-256：

- `src/source/CMakeLists.txt`：`76fbf1ab4acf2c9f3dcae57bad0996002dc04e3e857ebab27afce5ba70b8822d`
- `src/source/JBinaryData.h`：`6c5ae894216685b6c24792c229760e093eb1ffdcdab71ea22261784e3a251903`

## 计划状态

这只补上通用 CPU target 的可复现隔离构建基础，不代表 R008 的定义/编译器/链接库/运行时身份已绑定，也没有运行 R008。F8 readiness、T1、执行授权及 Core 总体验收状态均不变。
