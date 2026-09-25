# Core 计划续推状态 UPDATE-146

## F4 collector 旧入口保持 diagnostic-only

V13 要求 trusted V3 capability-only collector consumer 尚未实现。因此，`collect_f4_production()` 与 `assemble_multifamily_manifest()` 现在会在解析参数、访问 Mapping/path、解析 data root 或迭代 sources 前拒绝 `formal_release_requested=True`；传入非精确 `bool` 也会 fail closed。`formal_release_requested=False` 的旧 diagnostic 流程及内部资格证据校验保持不变，不产生 trusted capability。

新增 sentinel 测试证明 collection 不读取调用方 Mapping、不解析指定路径，multifamily assembly 不迭代 sources，即会拒绝正式请求。既有伪造 qualification 的深层 binding 检查继续直接覆盖 `_validate_qualification(formal=True)`，不因 public ingress guard 而失去回归。

F4 collector、connector、V3 codec 与 formal-admission-readiness 定向测试：**60 passed, 1 deselected**；被排除的既有 `test_real_first_eight_is_reader_hold_with_fixed_denominator` 使用 `qualification-tick.json`，其顶层只有 `binding` / `result`，而既有读取器要求顶层 `schema`，故在本次改动前的 schema 校验处失败。尝试替代当前 tick 文件也无法满足旧 reader 的 summary 投影或 batch 绑定；本轮不改历史收据、不放宽 schema/formal gate，也不将该 reader 迁移混入此安全封口。`py_compile` 与 `git diff --check` 通过。

未运行 worker、solver、GenCase/native、GPU 或 queue；未发起 F4 canary。本次只封闭旧 public collector/assembler 的 formal-release 旁路，没有实现 trusted root、V3 capability、snapshot/fs-verity 或 worker/runtime 闭环，不增加任何 T1/T2/资格信用。V13 trusted capability-only consumer 与旧生产诊断收据读取器的版本对齐仍待后续推进。
