# F8 R008 solver source/build provenance 静态审计（2026-09-25）

## 结论

仓库提供多套可生成不同 solver binary 的入口，且当前 `bin/linux` 没有 `DualSPHysics5.4_linux64` 或 `DualSPHysics5.4CPU_linux64`。因此现阶段没有可绑定到 R008 的标准 DualSPHysics solver executable/build artifact；CPU/native GenCase 预检不补足这条来源链。

即便后续在同一源码仓构建，也不能只用 `main.cpp` 中的版本字符串或 binary SHA 声称 source-to-binary 通过：构建入口、CPU/GPU macros、CUDA arch、库依赖和 CMake/Make 配置均可能不同，且没有仓内 builder attestation/manifest 将实际 exec 进程、binary 与链接/运行时模块绑定。

## 静态构建路径

| 路径 | 目标/宏与默认 | 关键歧义 |
|---|---|---|
| `src/source/Makefile_cpu` | `DualSPHysics5.4CPU_linux64` → `bin/linux`；`g++`、`-D_WITHMR`、不定义 `_WITHGPU`；默认 `-O3 -ffast-math -fopenmp`，`-march=native` 关闭 | Makefile 参数可覆盖；调用者、环境、工具链版本未记录；模式注释写 v5.4.351，而 `main.cpp` 编译常量是 v5.4.355 |
| `src/source/Makefile` | `DualSPHysics5.4_linux64` → `bin/linux`；host `g++`、CUDA `nvcc`、`_WITHGPU`/`_WITHMR`；默认 CUDA 12.8 路径、`-use_fast_math`，Makefile 的 CUDA 12 gencode 到 `sm_86` | `CUDA` make variable 可改 CUDA 版本；选定目标架构随此变量变化；源码注释版本仍为 v5.4.351 |
| `src/source/CMakeLists.txt` | 默认 `ENABLE_CUDA=ON`，若探测到 CUDA 则创建 CPU 与 GPU targets；CUDA ≥12 的静态 arch 列表含 61/70/75/80/86/89/90 | CMake cache、compiler/toolchain、探测结果、构建命令和 compile database 未绑定到某次 solver；文件头仍写 v5.4.316 |
| `src_mphase/DSPH_v5.0_NNewtonian/source/*` | 独立 `DualSPHysics5.0_NNewtonian{CPU,}_linux64`，输出 `bin/linux/DSNNewtonian`；加入 `JSphCpu_Tensors`，旧 ABI/CUDA 设置 | 是不同旧源码/物理实现，不可与 R008 标准 Newtonian solver 混作同一 binary lineage |

标准 CMake 与 Make 也不是同一 GPU codegen：比如当前 Makefile CUDA12 架构到 `sm_86`，CMake 对 CUDA ≥12 列入 `sm_89`/`sm_90`。这不评价哪套正确，只说明单一“GPU build”标签不足以识别可执行结果。

Makefile pattern rule 直接把 `.cpp` 编为 `.o`，未声明头文件 dependency/depfile；成功后才清掉 object files。可复现 build 应从全新隔离 build tree 构建，不复用中断构建留下的 `.o`。CMake 也需要冻结其 build directory/cache 和生成 compile commands，不能从 Makefile 注释反推实际命令。

## 实际共享配置与依赖

- 当前源码中 `main.cpp` 的版本常量为 `v5.4.355`，而 Makefile/CMake 文件头分别标注 `v5.4.351`、`v5.4.316`。这些注释不能作为 build identity。
- 标准构建目标落在 `bin/linux`。该目录当前已有 tracked `DsphConfig.xml`（SHA-256 `0644c9a6a6687678950fc8966e352b4bbd3de9d3cb787db9e507c2eb7ccaddcd`），设置 `createdirs=1`、`csvseparator=0`，未设 `csvsepthousands`。若未来 solver 按默认 target 放入该目录，`JCfgRunBase` 会从 binary parent 目录读取这份配置；其字节/存在性必须绑定到该 attempt。
- 当前 `bin/linux` 只有 GenCase 与工具程序、配置和共享库，没有上述 solver target。`src/lib/linux_gcc` 有 tracked Chrono `.so` 与 WaveGen `.a`；Makefile 以 `-l...` 选择它们并按编译选项链接。`bin/linux` 的 Chrono `.so` 副本与 `src/lib/linux_gcc` 对应项 SHA 相同，但未来 build/runtime 仍需记录真实 link map 和进程加载的模块，不能假定目录副本就是实际加载文件。
- 可复现 builder 需固定精确源码树/提交与 dirty state、构建系统及完整 options/cache、完整 argv/环境、compiler/linker/binutils/CUDA versions、CPU/GPU target flags、每个静态/动态库 bytes/hash、build log/compile commands、产出 binary digest；执行期还需以可信来源证明启动进程的 executable inode/hash 及实际加载库。只有 binary digest 不认证构建来源；只有 builder 自报也不能构成独立 trust root。

## 对 R008 execution contract 的影响

首个 R008 runtime profile 必须固定标准 Newtonian source tree，并仅允许经审查的 CPU 或 GPU target 之一；记录实际 target name 不足以区分 CMake/Make 和被覆盖的 flags。构建前冻结干净 checkout/生成 build tree，保存完整构建输入与工具链/库清单，产物发布使用不可变路径；execution supervisor 需将该 binary 与 `execve` 的 file descriptor/inode、加载模块、feature set 和全程子进程绑定。没有可验证 builder/supervisor trust root 时，source-to-binary 与 execution gate 必须继续 `open`。

这次只读 Make/CMake、源码、仓库 tracked file list 和现有轻量 `bin/linux` 目录；未调用 compiler/Make/CMake/solver，也没有读取 production trajectory。未运行 GenCase/native decoder/worker/GPU/queue，未改源码、资格范围、阈值、分母、registry 或资源账本。R008 `T1_numerical=false`、资格信用 0、无 execution authority。

## SHA-256

| 文件 | SHA-256 |
|---|---|
| `src/source/Makefile_cpu` | `4038165b761e233b207b7196f320dc59b3092737d5eaf8c98c9a282b9e900a91` |
| `src/source/Makefile` | `0e7d60ed96437ae22c1d411ec7d12fcae1adad8a9e91f39dd0ea6023846c63f1` |
| `src/source/CMakeLists.txt` | `69a130cd319ff79beee3d88ad0bec54244af7c7c7aaaa3aef1aa584b0bf67e99` |
| `src/source/main.cpp` | `43ce552b8177dad089148f7f552bc44f9467220eb0da6503964f6bfd6c888b4c` |
| `src_mphase/DSPH_v5.0_NNewtonian/source/Makefile_cpu` | `f790b4bbd6b6f32e51ffdb44d718744633b29913b2a6bb3a5f421b82d320faff` |
| `src_mphase/DSPH_v5.0_NNewtonian/source/Makefile` | `e7141e4a2a433fce7b2de4741cf4c94675af135cb64b3ea26dc3a88b00c573aa` |
| `src_mphase/DSPH_v5.0_NNewtonian/source/CMakeLists.txt` | `db5bc00b82e069f66bdd4560bc02041aab99febdd401fa4607ced5967aa81046` |
| `bin/linux/DsphConfig.xml` | `0644c9a6a6687678950fc8966e352b4bbd3de9d3cb787db9e507c2eb7ccaddcd` |
| `src/lib/linux_gcc/libChronoEngine.so` | `3adb8a5ef36b988add7717d60ee5e50bf7107a5623b448c3a5300d087c2b32e7` |
| `src/lib/linux_gcc/libdsphchrono.so` | `6a7a94ed7adcdd4e9dddee58cde0f080dee95d930e169bd39cc78894d1a2c937` |
| `src/lib/linux_gcc/libjwavegen_64.a` | `af835a1f8faf053d7a5eba4c6ddf23585974da640f6c25e48123c887b131e8ac` |
