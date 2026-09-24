# UPDATE-53：F8 R008 execution evidence synthetic-only 范围收敛

日期：2026-09-25（Asia/Shanghai）

## Terra 配置复审结论

对 v3 synthetic schema 的审查请求指定 `gpt-5.6-terra` / `high`，技术结论为 `REVISE`；但回复自述当前会话可见模型为 Codex/GPT-5 基础配置，且没有独立身份 attestation。因此该结果只记为未认证 reviewer 的技术意见，**不计为 Terra High 审查**。未修改代码、测试、冻结输入或执行状态。

审查发现 v3 仍未达到可冻结的机器合同：

1. `(stage, role, object_id)` 到固定对象的 allowlist、root 身份及角色配对未定义完整；manifest/journal/build/trust 之间的有向无环图和唯一性约束也不足，builder 签名缺少完整 envelope。
2. input inventory、cgroup 限额与事件、外部配置绑定、终态、日志、accinput 标量等嵌套类型仍有字段或界限缺口；部分引用角色未列入 role enum。
3. “synthetic 永远 open”尚未覆盖所有非法输入和异常返回路径，也没有 API 层不可写 registry 的机械保证；scope 与资格行摘要没有与所有 horizon digest 逐项强制相等。
4. `accinputs` 还需绑定连续 runtime 顺序、MK range、XML 元素身份、解析后的 table 结果及逐 entry 查询域，并以 `[TimeIni, TimeEnd]` 与控制表时间域作严格包含核验。cgroup membership 也需绑定 mount/root/parent、连续成员记录与失联处理。
5. event union 的 enum、取值、字段与资源上限必须在当前 schema 内完整定义；不能依赖旧草案补足。

一项路径事实在此更正：C→B 完整链路使用绝对规范化路径绑定；`../B/receipt.json` 只出现在断开的 synthetic fixture 初始占位值，构建完整链时会由测试更新为 B receipt 的实际路径。证据见 `lagrangian-fluid-lab/tests/test_f8_r008_per_case_bundle_verifier_v1.py:390`、`:442` 及 verifier 的 `_binding_matches` 调用（`:1629` 附近）。因此不能把 fixture 占位值描述成生产链格式，也不能让未来 resolver 直接打开不可信路径。

## 范围调整

新增 [synthetic open-only control harness v1](F8-R008-C-SYNTHETIC-OPEN-ONLY-CONTROL-HARNESS-V1-DRAFT-2026-09-25.zh-CN.md)，不再试图把尚未闭合的生产 runtime 证据字段塞入 synthetic schema。该 harness 只解析一个小型内存 JSON probe、对照调用方给定的 scope/qualification-row 摘要，并恒定返回 `gate_state=open`、零信用、`registry_write=false`；它没有文件、FD、网络、C-v1 verifier 或 registry API，也不读取任何 execution evidence。

该 v1 草案的复审虽不计 Terra High，仍发现可采纳的具体缺口：输出状态与错误码缺少完整决策表；异常/I-O 保证说得过强；`production_input_consumed` 无法证明调用者传入字节的来源；输入边界和五个布尔字段未完全定义；两个 expected digest 只是独立字符串相等，不构成共同来源证明；`ok` 命名有误读风险。v1 保留为历史，v2 草案收紧这些定义后再请求 Terra High 复核。

这只是 synthetic parser 的安全边界测试候选，不是 C execution evidence schema，不证明 argv、输入、horizon、终态、资源、构建或签名。旧 v1/v2/v3 草案和本次 `REVISE` 均保留为历史，不覆盖。待 Terra High 只读复核；通过也只考虑实现该纯内存 harness 与负例测试。

## 真实 execution gate 状态

生产 gate 所需的 supervisor/event-source trust root、stage-role object catalog/resolver、journal 与 DAG exact schemas、builder/source-to-binary 证明、完整 solver call graph、逐 entry accinput 语义、连续 cgroup membership、C-v1 activation/兼容策略仍未闭合。当前不得判 `control_no_extrapolation` 为 pass；R008 `T1_numerical=false`、资格信用为零。未运行 solver、worker、GPU、队列或 native/GenCase 工具。
