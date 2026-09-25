# UPDATE-170：新增 F8 R008 PartExtra finite-value 诊断

时间：2026-09-26（Asia/Shanghai）

## 本次推进

根据 `JDsExtraDataSave` 的 CPU writer 静态实现，新增独立 `JPartExtraBi4` 诊断解析器，不修改已冻结的主帧 SAFE BI4 decoder。解析器固定 root metadata 名称/类型及 `FormatVer=211030`，仅接受一个 `Normals` float3 数组，并按 `UseNormalsFt` 对应的 `CaseNbound` 或 `CaseNbound-CaseNfloat` 检查总体；逐分量统计法向 finite 值，同时统计 `TimeStep`。解析全程绑定 held FD、预期 SHA、单链接常规文件、固定 PartExtra header/root，并在 parse 和 payload scan 后复核文件身份与整文件摘要。

返回值只包含诊断计数、摘要、单位/语义和原始 timestep 位模式；非有限 timestep 不会直接进入 JSON 数值字段。未知 metadata/数组、错 dtype/count、Part identity 或 case 人口不符均 fail-closed。代码复用旧 SAFE decoder 的私有 bounded item parser；这是显式版本耦合，需在未来 decoder 变化时重新审查。

只读代码审查给出 PASS、未报 P0–P3，但 reviewer 明确无法 attestate `gpt-5.6-terra/high`；因此不记作 Terra High 独立审查通过。更重要的是，这个 parser **不**核验 PartExtra 属于哪个 B/C/D bundle，也不证明 auxiliary 输出清单完整；不能关闭 `native_state_finite` gate。

## 验证与边界

- PartExtra + 主帧 finite inventory + raw finite scan 定向回归：**49 passed**。
- PartExtra parser/test `py_compile` 通过，`git diff --check` 通过。
- PartExtra 只用合成 BI4；未读取生产 PartExtra、bundle、HDF5/frame，未运行 GenCase/native decoder/solver/worker/GPU/queue，也未写 evidence receipt/registry/ledger 或改变资格分母。
- 新解析器保持 diagnostic-only、bundle membership/completeness false、source/runtime authentication false、native integrity/T1/readiness false、credit 0。后续仍须完成 bundle-level closed-world inventory、源/运行时认证、control source/consumption 绑定及完整 15-case 终端证据。
