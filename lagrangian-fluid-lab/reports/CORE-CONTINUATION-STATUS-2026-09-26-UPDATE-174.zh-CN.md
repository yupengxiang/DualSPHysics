# UPDATE-174：F8 R008 其余原生 auxiliary 浮点 writer 扫描

时间：2026-09-26（Asia/Shanghai）

## 本次推进

为 `Part_Head.ibi4`、`PartInfo[ _pNN ].ibi4`、`PartMotionRef[2].ibi4`、`PartFloatInfo[2].ibi4` 新增受限 synthetic-only BI4 finite inventory，并接入已验证 B/C 闭合输出清单。解析只使用调用方已持有的 no-follow、single-link FD 和精确文件名；文件长度先受每类上限与 64 MiB native raw cap 约束，目录清单内本批最多 64 个文件/256 MiB。解析前后及 inventory 末尾均复核 inode/size/time identity 与 manifest SHA。未知结构、未知文件名、错误 filecode、piece 不符、数组类型/数目不符均 fail-closed。

- `Part_Head`：验证 `JPartDataHead`/`MkBlocks`/`MkBlock_NNN` 结构及粒子人口和；扫描全部 float/double root 与 block metadata。
- `PartInfo`：验证 `JPartDataBi4_Info` 平面 root 与追加 `PART_NNNN` 记录；覆盖每行时间、域边界、solver/可选 DEM/Symplectic、GPU memory 与 subdomain 浮点 metadata；识别并验证 `PartInfo_pNN.ibi4` piece 命名。writer 将数组隐藏，因此该文件合同不接受数组。
- MotionRef/FloatInfo：验证精确 main/extra 文件名、版本/root、追加 PART 身份以及 single/batch layout；有限扫描所有 double/float metadata 和数组，包括 `FptCount` 条件性的 force-point 位置/力数组。

发现并修复一项独立代码审查 P2：最初把单帧 64-array SAFE 上限错误套到整个 list-appended 文件，合法长流会被拒绝。现按 writer 的每项精确 schema、受限 item 数、总 metadata 与 64 MiB 原始文件上限做 aggregate bound；新增六条 FloatInfo（含 force arrays）和 60 条 MotionRef 正常追加记录的回归。Terra High/high 配置的 follow-up 对修复未发现新的具体问题；不声称密码学模型身份 attestation。

## PartOut 格式范围决策

本次也按冻结 R008 输入/CPU 路径审查是否要扩大 PartOut parser：已绑定的 CPU GenCase initial XML 明确 `Npiece=1`，native `Idp` 数组为 uint32；官方 `JSph::SavePartData` 校验 `Idp` 为 `TypeUint`，并将 `PartsOut->GetIdpOut()`（`unsigned*`）传入 PartOut writer。故当前冻结 R008 CPU 子集不需要多-piece 或 uint64 `Idpd` 支持；通用官方 writer 的其他 overload 不是本 scope 的执行配置证据。若未来改变 piece/ID 配置，必须另行扩展和审查，不能静默接受。

静态源快照 SHA-256：

| 官方 v5.4 源文件 | SHA-256 |
|---|---|
| `JPartDataHead.cpp` | `686698ac7c6b39be8da07ad6e7982d97735547668fb81dba5bf2d6bd507a9b63` |
| `JPartDataBi4.cpp` | `e507d88c8fac9b990b74d8dce71edb3524f71f46a04b3bdc5d289bf0af4ecdfc` |
| `JPartMotRefBi4Save.cpp` | `de5d3569ff4e7780c1dbe660cb0b7f43ea65364979a35b780cf134ed86bbb8fb` |
| `JPartMotRefBi4Save.h` | `e7e4f012fb562a48f22ae4374b92f0d1049fe5043d0ce07328902d416c072111` |
| `JPartFloatInfoBi4.cpp` | `ef0262bc93fb93938a0d9ee2e9fed5f9d9da7717571cd8f6ddccad0adc3b721e` |
| `JPartFloatInfoBi4.h` | `0fd0c5d9dd0cf3cdbce0ffebe1afb7ee1175cbe2297c3f346cbc0e936cf45a5d` |
| `JDsPartMotionSave.cpp` | `4769b2dfecf7bb1b0a957a68454a8321a24d8d84c2fb9da2d0b5c3410d8dbda6` |
| `JDsPartFloatSave.cpp` | `2ffa6a537707e9ff0b66e16283433976f3d763575270b3ff50d90e2af94dafb9` |
| `JSph.cpp` | `8729eb29db778288b0495855a04fa0984000896546f484dcf96176ec48da5454` |
| `JPartOutBi4Save.cpp` | `1a5d746ae5a962bc10d752e0f96d8acaacb02c31ab3dc647f447f4b2a3b3e2d3` |

writer 创建条件由 `JSph::ConfigSaveData`/`SavePartData` 与对应保存类确认：Part_Head 需 Binx，PartInfo 需 Info，MotionRef 需 Binx 且存在 moving/floating 人口，FloatInfo 需 Binx 且存在 floating 人口；motion/float 的 extra 文件还依赖 `TimeOut2>=0`。这些条件只描述官方 writer；当前扫描不会由缺文件推导某一模式关闭，也不据此认证真实 invocation。

## 验证与边界

- 十个相关 `.venv` suites：**219 passed**，覆盖四类 scanner、B/C inventory、PartOut/RunPARTs、PartExtra、native-state finite inventory/scan/evidence、per-case bundle verifier v1/v2。
- 修改文件 `py_compile`、`git diff --check` 通过。
- 输入均为临时合成 fixture；只读静态源和既有 CPU native preflight initial XML。未读取生产 bundle/frame/HDF5；未运行 GenCase/native decoder/solver/worker/GPU/queue；未修改 registry/ledger/qualification denominator/receipt。
- 所有 present manifest 成员现可逐类扫描或保留为已知未扫描/未知分类；但 `native_auxiliary_presence.expectations_resolved=false`、`all_native_auxiliary_float_sources_scanned=false`。真实 source/runtime/invocation、output-mode 完整性、正常覆盖 `T_end` 与最终 flush/pending-buffer 证据仍未认证；native-integrity、T1、readiness 均 false，资格信用 0。

## 后续

继续处理 PLAN 中剩余静态工作和其他未完成分支。F8 R008 若要完成 source/runtime/output-mode、`T_end` 与最终保存/事件 flush 闭环，仍需要一个获准的真实 solver attempt；本更新没有启动该 attempt，也未扩大执行权限。
