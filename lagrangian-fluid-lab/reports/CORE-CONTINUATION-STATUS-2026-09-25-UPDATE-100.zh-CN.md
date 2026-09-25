# Core 计划续推状态 UPDATE-100

日期：2026-09-25（Asia/Shanghai）

## 本次推进：关闭 F4 旧 qualification Mapping 到 production 的入口

V13 草案要求 V3 trusted qualification bundle 必须由唯一 root reader 创建并由固定 consumer 使用；当前 F4 connector 仍接受普通 Mapping，且 `verified=true` 等字段可以直接影响 8→24 batch decision。尚无 V3 capability mint/consumer 实现，因此本轮将旧 API 限定为 diagnostic：

- `batch_decision()` 不读取 caller design、qualification 或 audit 字段；固定返回 `scope_review_required`、无 ready case、`missing=null`（表示未做可信逐案 accounting）和 capability 缺失原因。
- `prepare_production_batch()` 与 `production_job_spec()` 在检查 gate 字段、root tick、读 prepared path、导入 `core_cfd` 或创建输出前拒绝 legacy 调用。
- `build_proposal()` 的资格视图将正式 `matrix_complete`、`T1_numerical`、artifact binding 和 qualification-admitted 标为 false；输入中观察到的旧字段仅放在 `observed_*`，并置顶声明 trusted bundle unavailable / formal batch not admitted。
- 正向 Mapping、伪造 audit、partial matrix、direct preparation/job-spec 输入均有拒绝或无字段读取回归。

`tests/test_f4_tallwall120_production_connector.py`：21 passed；`py_compile` / `git diff --check` 通过。仓库 `.venv` 用于测试。Proposal integration regression 以 synthetic tick/evaluation monkeypatch 测试，不重跑实际 root qualification tick；测试仅读取冻结 F4 manifest/evaluation/design/reuse/resource/template metadata，并在临时目录构造 synthetic audit，未读取/修改生产 HDF5 或 archive。未执行 CPU canary、GenCase/native、solver、worker、GPU、queue，也未准备 production batch/job 或写入 ledger/registry。

## 剩余信任缺口

此举只是让旧 connector fail closed，不产生 V3 capability，也不证明 producer/root/runtime 身份。可信 root reader、exact raw JSON parser、V3 qualification bundle、descriptor snapshot/broker、运行时代码闭合与独立审查仍待实现。旧 F4 CLI 的 read-only proposal/tick 可以继续观察 metadata，但不能授权任何 production batch；CPU canary 的既有一次性边界不变。本轮正式 F4 admission 信用为零，整体 Core T1/T2 目标仍未完成。
