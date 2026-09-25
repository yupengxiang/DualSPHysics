# Core 计划续推状态 UPDATE-126

日期：2026-09-25（Asia/Shanghai）

## 本次推进：aggregate V2 的独立诊断复算入口

新增 `validate_untrusted_attempt_aggregate_v2`：从 15 个 case row 中取出完整 attempt-result inventory，复用固定 matrix/ledger structural inspectors 与 unresolved attempt guard 重建预期 aggregate，再按 canonical JSON bytes 比较候选与重算结果。这样会同时校验精确顶层/row fields、冻结 row 顺序与身份、ledger registration inventory、retry 归属和顺序、全部 outcome counts、descriptor-ref 字节绑定、attestation 缺失状态，以及资格/T1 false、credit=0。canonical bytes 比较也避免 Python 中 `False == 0` 导致布尔值伪装整数计数。

该 validator 仍是 non-authorizing consistency check：它只比较 caller 提供的 raw matrix/ledger 与 aggregate，未增加可信 source authentication、descriptor registry、attestation key verification 或 outcome adjudication，不 mint capability。

验证：ledger + V2 suites **70 passed**；加入 C-execution V5 与旧 v1 synthetic B/C/D reference chain 的集成回归 **137 passed**；`py_compile` 通过。新增篡改负测覆盖 case 数、row 顺序/outcome、case/attempt counts、bool-as-int、credit、额外 row 字段及未经验证 attestation。

未读取生产 bundle/frame/HDF5/BI4/one-shot 数据，未运行 GenCase/native decoder/solver/worker/GPU/queue，未提权或改变外部状态。此次没有 Terra High 独立代码审查。

## 尚未闭合

UPDATE-125 所列可信来源与 attestation、可信 inventory/completeness、stage/runtime evidence 验证、outcome/retry/T1 adjudication 仍未完成；diagnostic validator 的 PASS 只表示 caller inputs 在当前 restricted contract 下自洽，不代表 scope/ledger 可信或 F8 获得资格。详见 [V2 remediation draft](F8-R008-PER-CASE-BUNDLE-VERIFIER-V2-REMEDIATION-DRAFT-2026-09-25.zh-CN.md)。
