# UPDATE-169：加固 F8 R008 finite inventory 原始字节绑定

时间：2026-09-26（Asia/Shanghai）

## 本次推进

在 UPDATE-168 的 provisional finite inventory 上完成安全与字段报告补强。入口不再接收 caller-supplied `ScanResult`，而是从已持有 raw-frame FD 内部重建 BI4 树并校验预期 SHA-256，再将同一 descriptor 交给流式 finite scanner 做状态数组读取与完整性复核。未知、重复或错位的 PART 数组仍 fail-closed；扩展数组负测现直接从带真实未知数组的合成 BI4 原始字节触发拒绝。

逐个 state-array、float metadata 和 control-column 结果补充来源 SHA、dtype、单位、语义与 population。未知浮点 metadata 仍计入 finite 总数，同时明确标成语义未分类。控制 CSV 的 T/64 步长下溢、非有限 horizon/timestep 比率及越界情况均 fail-closed。测试使用冻结 15 行 qualification matrix 的实际 control renderer 验证各表 finite 与时间轴；全局最大表为 1,497 行。

只读代码审查给出 **PASS**、未报 P0–P3；未运行测试或生产/native workload。审查没有提供来源/运行时密码学身份认证。独立 `PartExtra` 与其他 auxiliary output 仍未纳入扫描，不能据此关闭 `native_state_finite` 或任何资格 gate。

## 验证与边界

- 最终 finite-inventory + raw-finite-scan 定向套件：**36 passed**。
- 八文件相邻回归：**198 passed**（149.05 秒）；随后仅对测试 fixture 增加真实未知数组输入及对应测试，定向 36 项复验通过。
- 相关三个 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- 仅用合成 BI4/CSV、冻结 scope 和仓库内 control renderer；未读取生产 bundle/HDF5/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue，未创建 receipt、改 registry/ledger 或变更资格分母。
- 输出仍是 `diagnostic_only_not_adjudicated`，native integrity、T1/readiness 均 false、资格信用为零。可信 source/build/runtime、control source binding/consumption、PartExtra/auxiliary 全输出 inventory、完整 15-case 执行证据仍未闭合。

下一步应先实现并独立复核 bundle-level PartExtra/auxiliary closed-world inventory，再考虑新版本 evidence/schema 的安全接线；不能将当前主帧与控制表诊断提升为 gate。
