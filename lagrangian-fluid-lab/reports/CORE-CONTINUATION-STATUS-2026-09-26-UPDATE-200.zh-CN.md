# UPDATE-200：F8 R008 原生辅助输出生成条件静态审计

时间：2026-09-26（Asia/Shanghai）

## 本次推进

逐项核对仓库锁定的 DualSPHysics v5.4 官方 writer，而非根据某个输出文件“存在/缺失”推断运行模式。对照输入使用既有 `cpu-native-preflight-v3/native-initial.xml`，其中 population 为 `CaseNfixed=4096`、`CaseNmoving=0`、`CaseNfloat=0`、`CaseNfluid=6656`。本次只读源码与该既有静态输入；未读生产 solver bundle/HDF5/frame。

| 输出族 | 官方 CPU writer 条件 | 对 R008 已有静态 population 的结论 |
|---|---|---|
| `PartMotionRef.ibi4` / `PartMotionRef2.ibi4` | `SDAT_Binx && (CaseNmoving || CaseNfloat)`；第二文件另需 extra stream active | 该输入的 moving/float 都为零；若 C run 与该输入一致，writer 不创建该对象。出现该文件应视为输入/谱系不一致，不能只当成普通 finite-scan 成功。 |
| `PartFloatInfo.ibi4` / `PartFloatInfo2.ibi4` | `SDAT_Binx && CaseNfloat`；第二文件另需 extra stream active | 同上，float population 为零时不会创建。 |
| `Part_Head.ibi4` | `SDAT_Binx` | 是否应存在取决于实际 binary-save mode；不能从输入几何单独判定。 |
| `PartInfo.ibi4`、`RunPARTs.csv` | `SDAT_Info`；RunPARTs 在每个保存点追加，并在正常 CPU `FinishRun` 路径写 footer | 实际 `-sv`/输出模式未绑定，缺失不能解释为关闭了 Info，也不能据 footer 证明最后一个 PART 已保存。 |
| `PartOut_*.obi4` | `SDAT_Binx` 创建 writer；每次保存点仅在 `PartsOut->GetCount()!=0` 时写事件文件 | 文件缺失不能证明排除粒子数为零；必须依赖实际完整运行、RunPARTs 与逐段事件输出联合证据。 |
| `PartExtra_####.bi4` | `SDAT_Binx && !SvExtraParts.empty() && (TBoundary==BC_MDBC || !SvPosDouble)` 建立 writer；具体 PART 还需满足 `cpart>0`、间隔与筛选条件 | 冻结的 15 份 qualification Definition 均声明 `Boundary=2`，官方 parser 将其映射为 mDBC，因此本 scope 的 `SvPosDouble` 不影响 writer 是否启用。真正未冻结的条件是 `SvExtraParts` 是否非空：`SaveExtraParts` 可来自 XML，`-svextraparts` 也可覆盖；其精确值/argv 尚未绑定。 |

来源代码的 SHA-256 已记录：`JSph.cpp` `8729eb29db778288b0495855a04fa0984000896546f484dcf96176ec48da5454`；`JSphCfgRun.cpp` `1917b8c2debad3b4dece4c05c597cb03e44fa77122548e2ffcc172f5ff69b048`；`JDsExtraData.cpp` `4b9248319e3bb8646c669fd49690c7c0483729f135f06de4b5d6b5ac91a24cb7`；`JDsPartMotionSave.cpp` `4769b2dfecf7bb1b0a957a68454a8321a24d8d84c2fb9da2d0b5c3410d8dbda6`；`JDsPartFloatSave.cpp` `2ffa6a537707e9ff0b66e16283433976f3d763575270b3ff50d90e2af94dafb9`；`JSphCpuSingle.cpp` `2af63868305d2b38b3876f26563c82e979da7f8c4cb86743b339d2c25572b5fd`。静态 population XML SHA-256 为 `0c5201e6177346f618018a0b7cd918e83d9c883c466b3ccbaf698277afd20f9f`。

## 后续合同应冻结的字段

一次真实执行若要关闭这些分类，至少需把 solver binary/source、精确 argv、`-sv`、`-svextraparts`、相关 XML execution parameters、初始 population、实际完整终止与输出树 manifest 一起绑定。`Boundary=2` 的冻结 Definition 证据缩窄了 `PartExtra` 条件，但未证明实际 solver 消费的正是这些 Definition，也未证明 `SvExtraParts` 的最终值。生成条件审计不能认证一次 invocation 确实采用这些选项。

## 边界

此审计仅把零 moving/float 对 `PartMotionRef*` 与 `PartFloatInfo*` 的静态 writer 条件闭合，并收窄 `PartExtra` 的待绑定字段；不把任何缺失文件升格为模式关闭或物理零事件。未运行 GenCase、native decoder、solver、worker、GPU、queue，未修改任何资格门、registry、ledger 或旧 receipt。T1/readiness/credit 不变。

检查时系统 load 为 `251.17`，可见 CPU 数为 `128`；本轮没有增加 CPU-intensive regression 或 workload，也未干预现存进程。
