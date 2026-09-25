# Core 计划续推状态 UPDATE-132

## 本次推进：F8 attempt-ledger 引用与调用方原始对象字节绑定

新增 `bind_untrusted_attempt_ledger_raw_objects()`，仅接受调用方提供的精确内存字典 `{(stage, role, object_id): raw_bytes}`，并要求：

- 字典 key 集合与 ledger 中所有非空 stage receipt、process journal、attempt terminal 引用完全一致；缺项、多项及同一 object identity 的冲突描述符均拒绝。
- 每个对象的 builtin `bytes` 长度和 SHA-256 分别与 ledger ref 一致；对象数量与累计 raw bytes 均有硬上限。
- 不做路径查找、对象 JSON/receipt 解析、阶段语义判定或来源认证。回执明确标记 producer / descriptor root 未认证、阶段内容语义未验证、ledger 不完整、outcome 未解析、T1=false、资格信用为零。

Terra High（`gpt-5.6-terra` / high）只读复核未报 P1/P2，指出若干 fail-closed 分支缺直接测试；现已补充重复 identity 冲突、错误 key、长度不符、`not_started` 空引用和资源上限测试。未做复审，因此不把该轮称作独立最终 PASS。

## 验证与边界

- attempt-ledger、V2 attempt projection、V5 journal 三个定向测试文件：**166 passed**；ledger 文件单独为 **78 passed**（含于上述总数）。
- `py_compile` 与 `git diff --check` 通过。
- 仅使用冻结 scope receipt 与合成 JSON/raw bytes；没有从磁盘或生产目录解析任何 ledger 引用对象，也未调用 worker、solver、GPU、queue、GenCase/native decoder 或 sudo。

本次只证明 caller-supplied 原始字节与 untrusted 引用描述符相等，不证明对象来自可信 descriptor root，也不证明 receipt/journal 内容正确或完整。真实引用对象 reader、B/C/D stage 语义复核、可信 ledger completeness、执行 outcome、F8 15-case T1 和后续 Core T1/T2 仍未完成；不改变任何运行授权和资格信用。
