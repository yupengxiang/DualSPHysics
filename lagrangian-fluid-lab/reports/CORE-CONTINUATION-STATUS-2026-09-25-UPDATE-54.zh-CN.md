# UPDATE-54：F8 synthetic non-qualifying harness v2 设计修订

日期：2026-09-25（Asia/Shanghai）

## 修订依据

UPDATE-53 v1 的审查请求指定 `gpt-5.6-terra` / `high`，但回复自述当前会话可见为 GPT-5 基础配置且无独立身份 attestation。故审查结果不登记为 Terra High；技术结论 `REVISE` 仅用于修补草案。

修订点：

- 为所有诊断结果定义唯一 code/boolean 决策表，覆盖参数错误、尺寸/编码/JSON/重复键/深度/形状、scope/row 单项与双项不匹配及可恢复内部异常。
- 将 `production_input_consumed` 改为 `harness_performed_external_io`；文档明确不能据此判定调用者传入内存 bytes 的来源。
- 明确输入原始字节长度先于解码/BOM 检查，根对象深度计数、JSON 深度 precedence、expected token ASCII 类型及独立字符串相等的狭窄语义。
- 使用 `synthetic_bindings_match` 取代 `ok`，并在 schema/API 命名中声明 `non_qualifying`。即便该代码出现，状态仍恒为 open、零 credit。
- 限定依赖和入口；提出 AST import allowlist、无 I/O/registry spy、异常注入等测试。文档不把纯函数约束夸大为宿主机隔离或密码学信任证明，并明确 OOM/进程/解释器失效不承诺输出。

## 状态

新增待审 [v2 草案](F8-R008-SYNTHETIC-NON-QUALIFYING-CONTROL-HARNESS-V2-DRAFT-2026-09-25.zh-CN.md)。当前没有实现、测试、C-v1 兼容接线或生产数据读取。该文件只规范内存 JSON 的确定性诊断，scope/row 只是两个互不关联的 opaque token 比较，不形成执行证据或资格判断。

下一步：按用户指定请求 `gpt-5.6-terra` / high 对 v2 作只读审查。若审查通过，只考虑实现该无资格 harness 和纯合成负例；真实 execution contract/gate 继续 open。未运行 solver、worker、GPU、队列或 native/GenCase。
