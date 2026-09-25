# Core 计划续推状态 UPDATE-99

日期：2026-09-25（Asia/Shanghai）

## 本次推进：formal planner 对未认证 metadata 永久 hold

UPDATE-81 已指出 `core_formal_planner` 可由普通 Mapping/JSON、manifest inline T1/audit 和未版本化 evidence 得出 `formal_eligible=true`，进而构造 9 个 `launch_allowed_by_planner=true` spec。当前代码没有 source-bound trusted admission capability 可供该入口验证。

本轮将 `inspect_inputs()` 明确限定为 metadata-only diagnostic audit：

- 无论普通 Mapping/JSON 上的 `formal_release`、T1、hard-audit、case/family 数量、source snapshot 和 profile 表面状态如何，审计都加入 trusted-capability 缺失 hold；`formal_eligible=false`，并标记 `admission_basis=metadata_only_untrusted`。
- 未受信 metadata 不再导出肯定的 `family_t1`；各 family 值为 `null`。描述性 case/family 计数与负向 audit finding 仍用于诊断。
- `build_plan()` 保留 required 9-run 分母，但当前无 capability 时始终 `launch_allowed=false`、0 job、0 spec；完整 JSON-path 与内存 Mapping 都有回归覆盖。模块文档同步说明此状态。

使用仓库 `.venv` 运行 `tests/test_core_formal_planner.py` 与 `tests/test_core_formal_admission_readiness.py`：24 passed；`py_compile`、`git diff --check` 通过。只读测试读取了现存 F3 compact manifest、继承 qualification/resource/environment metadata 与 formal admission/source-closure fixture，并只在临时目录写 hold report/synthetic snapshots；没有打开 HDF5，也没有写入正式 specs、ledger 或 campaign 状态。系统 Python 的 h5py/NumPy ABI 问题仍通过仓库 `.venv` 规避，未改依赖。

## 未完成项

这是 fail-closed 安全门，不是 trusted capability 的实现。现有 public planner 暂时不能生成正式训练 specs；后续需先实现并独立验证 source-bound verifier/capability（包括 raw-byte/duplicate-key、trusted root 与运行时闭合），再为 planner 接入唯一 capability consumer。不能用 schema 标签、Mapping、重哈希或本轮 metadata audit 代替资格。F4 connector 的独立 ingress、V13 CoreDataset snapshot reader、F8 worker/T1 与整体 Core T1/T2 目标仍未完成、零资格信用。

未运行实际训练、planner 外的 job preparation、collector、GenCase/native、solver、worker、GPU 或 queue；未读取 solver/HDF5/one-shot 生产产物，未更改 F3/F4 一次性授权。本轮没有正式作业被创建或启动。
