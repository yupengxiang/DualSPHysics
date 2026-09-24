# Core continuation status — UPDATE-86

日期：2026-09-25

## 本轮推进

F4 tall-wall connector 的 `batch_decision()` 增加 qualification schema 前置门：单次读取并要求 exact builtin `core.qualification.v1`，否则 fail-closed 返回 `scope_review_required`，不读取 binding/family/scope/T1，也不复制或读取 audits。内部的 partial-matrix 负向 fixture 现在带正式 schema，以继续覆盖原本的 incomplete-matrix 分支。

新增 synthetic Diagnostic 读探针，覆盖 qualification marker 和 audit mapping 两侧的前置拒绝；有效 schema 的 8→24 bound-audit 递进及 partial-matrix、tampered-registration 回归继续通过。

## 验证与边界

- 4 个定向测试项/参数组：8 passed。
- connector 与测试 `py_compile`、`git diff --check` 通过。
- 仅读取 connector 固定静态设计并在 `tmp_path` 构造合成审计；没有执行 proposal/prepare、GenCase、worker、solver、GPU 或 queue。
- 未获得 Terra High/high 外部复核（agent thread limit）；没有 reviewer PASS。
- schema 是跨 schema 污染防线，不是 producer、raw bytes、root capability 或 runtime identity 认证；正确标签/可伪造 binding 仍不构成可信 qualification，V9/V12 capability 缺口与 T1 gate 保持未闭合。
