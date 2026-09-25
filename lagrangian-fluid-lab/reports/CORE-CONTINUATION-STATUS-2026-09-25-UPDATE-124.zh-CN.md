# Core 计划续推状态 UPDATE-124

日期：2026-09-25（Asia/Shanghai）

## 本次推进：冻结矩阵与 ledger row identity 绑定

补齐 V2 remediation 草案此前未定义的 `qualification_row_sha256` 算法：对 scope receipt `matrix.rows[i]` 完整 row object 做 strict parse，按仓库 V12 `canonical_json_bytes` 规则（UTF-8、默认 ASCII escaping、排序 key、紧凑分隔符、无末尾 LF）编码后 SHA-256；scope receipt 的原始 bytes 仍由独立的 `qualification_matrix_raw_sha256` 绑定。新增的矩阵 inspector 校验固定 F8 R008 scope/schema、exact 15 rows、冻结行字段集合、顺序、唯一 case ID 与 qualification-only builtin booleans，并返回每行可复算 digest。

ledger inspector 现在必须同时接收 raw qualification-matrix bytes：检查其 raw SHA 与 ledger 声明相等，并要求每个 attempt 的 case ID / row SHA 属于该 15-row matrix；V2 attempt projection 也必须经该矩阵交叉核对。此链只证明 caller 输入间的内部字节/身份一致，不证明矩阵来源可信；摘要输出 `frozen_matrix_source_authenticated=false`，supervisor attestation、ledger completeness、T1 与资格 credit 仍固定 false/零。

验证：ledger + V2 suites **50 passed**，C-execution V5 suite **66 passed**，旧 v1 合成 B/C/D chain **1 passed**（合计 **117 passed**）；`py_compile`、`git diff --check` 通过。另用 bounded strict reader 对仓库冻结的静态 scope receipt 做兼容性探测：识别到 15 行，原始 SHA 为既有固定值 `65671b…6ac8`，首行 canonical digest 为 `7a540d…fdce5`。这是静态设计合同检查，不是 solver/生产 evidence。全程未运行 GenCase/native decoder/solver/worker/GPU/queue，未触碰 one-shot 数据，未提权。

## 尚未闭合

row digest 补充规则及这轮实现没有独立 reviewer 复核，尚不能视为 Terra/GPT 6 Luna Max 审查通过。scope receipt 的 out-of-band 固定哈希/descriptor-root capability、ledger attestation/key activation、stage receipt 和 process journal 内容重验、15-case official aggregate 与 row outcome derivation、retry/失败分母及资格/T1 adjudication 仍未完成；不得将这项内部 digest 对账升级为 trusted matrix 或完整 ledger。
