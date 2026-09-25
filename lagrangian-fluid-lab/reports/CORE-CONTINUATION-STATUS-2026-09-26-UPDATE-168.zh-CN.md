# UPDATE-168：F8 R008 finite inventory 与七列控制值诊断

时间：2026-09-26（Asia/Shanghai）

## 本次推进

新增 provisional、synthetic-input-only 的 `f8_r008_native_state_finite_inventory_v1.py`，不改动原 finite scan/evidence v1。静态核对 `JSph::AddBasicArrays()`、`JPartDataBi4::AddPartData()` 和 extra-data writer 后，将主帧 inventory 明确为：全 `CaseNp` 上恰一 `Pos`/`Posd`、`Vel`、`Rhop`；`Idp` 是 uint32 identity 数组，不参与 IEEE 浮点有限值计数；BI4 root 与所选 PART 的所有 float/double scalar/vector metadata 逐组件计数。帧中未知、重复、错位或未分类数组 fail-closed。单独的 `PartExtra`/auxiliary 文件不由此 API 扫描，仍需 bundle-level inventory 分类，不能据此通过 finite gate。

新增纯 bytes 控制 CSV 诊断，核对冻结七列表头，对全部 `Time` 与六个线/角加速度列逐数值解析并计 finite/nonfinite；另核对从 0 到声明 `T_end` 的 T/64 采样轴。冻结 15-row qualification scope 的实际最大控制表为 **1,497 行**，测试按 scope 逐行验证上限及网格。解析器只报告字节摘要、逐列计数与声明覆盖；它不认证 frozen 参数/源绑定，不证明 solver 消费该控制表。

返回对象固定 `diagnostic_only_not_adjudicated`，native-integrity/T1/readiness 均 false、qualification credit 为 0；没有写入或连接 15×8 registry。因此 `native_state_finite` 仍 open。该 inventory 是待独立静态复核的候选实现，不是已审定 gate 合同。

## 验证与边界

- 新 inventory + 原 raw finite scanner 定向套件：**34 passed**，包含七列各自注入 NaN、非有限 metadata、未知扩展数组及完整最大行数负测。
- 扩大七文件回归最初为 **137 passed / 1 failed**；唯一失败揭示实现把最大控制轴误设为 321 行。以冻结矩阵实际最大 1,497 行修正后，新 inventory/raw scanner 专项复跑 34 passed。其余六个回归文件在该次扩大运行均通过。
- `py_compile` 与 `git diff --check` 待本次最终提交前复验。
- 只使用合成 BI4/CSV 与仓库内冻结 scope/源码定义；没有读生产 bundle/HDF5/frame、没有运行 GenCase/native decoder/solver/worker/GPU/queue，也没有写 evidence receipt、registry、ledger 或改资格分母。

下一步需要对 provisional inventory 做独立静态复核，再决定是否写新的 evidence schema 接线；在 source/build/runtime、控制字节绑定、全输出扩展 inventory 与完整执行证据未闭合前，不可把诊断结果用于 native-integrity adjudication。
