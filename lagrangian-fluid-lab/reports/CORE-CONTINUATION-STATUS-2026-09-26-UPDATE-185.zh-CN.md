# UPDATE-185：F3 model-material v2 流式写入与安全恢复

时间：2026-09-26（Asia/Shanghai）

## 实现

新增独立的 `f3_native_volume_mls_model_material_v2.py`，保留 v1 因果 provider、MLS/RK4、事件更新和科学字段语义，同时按初始帧及每个 RK 子步增量写出可扩展 HDF5 trace。每行包含完整积分状态快照、诊断计数、行 SHA-256 与 hash-chained commit log；恢复先核验 provenance/参数绑定和全部已提交行，只修剪未提交尾部。默认拒绝覆盖已有 trace，显式 `resume` 才继续，资格声明固定为 `none`。

Terra High/high 只读审查发现一项 P1：原始实现绑定未覆盖传递依赖，代码变更后可能用不同输入读取或墙面可见性语义继续旧 checkpoint。修订后 implementation binding 加入 `core_material.py`、`core_contract.py`、`passive_tracers.py`、`f3_material_neighbors.py` 的路径与 SHA-256，以及 SciPy 版本；新增依赖哈希变化时恢复必须拒绝的负测。Terra High follow-up 确认 P1 已关闭，无新 actionable finding。

## 验证

- v2 专项合成回归：**7 passed**。覆盖 v1 合成科学摘要 parity、连续与停机恢复 dataset 精确 parity、依赖/来源/参数绑定拒绝、已提交前缀损坏拒绝、仅截去未提交尾部和拒绝静默覆盖。
- 两个新增文件 `py_compile` 与 `git diff --check` 通过。
- 流式 v2 初始实现单独提交为 `63cd32e2`；本次依赖绑定修复和状态记录另行提交，避免混淆实现历史。

## 边界与后续

仅合成 HDF5 输入；未运行真实 F3 数据、solver、GenCase、worker、GPU、queue、profiling 或训练，也未刷新历史收据、registry、ledger 或资格分母。实现仅承诺 HDF5 仍可读取时的行级恢复；不承诺任意断电或 HDF5 元数据损坏可恢复。测试比较 HDF5 dataset 内容，不声称连续/恢复文件字节完全相同。该工具仍是诊断输出，不产生材料可靠性或 T2 资格。

性能剖析阶段计时、F3 闭壁 RK stage 失败的边界处理设计，以及真实材料运行仍未完成。
