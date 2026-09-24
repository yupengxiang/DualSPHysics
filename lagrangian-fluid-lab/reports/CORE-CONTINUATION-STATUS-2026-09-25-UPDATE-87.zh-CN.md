# Core continuation status — UPDATE-87

日期：2026-09-25

## 本轮推进

F4 tall-wall collector 的公开 `collect_f4_production()` 输入加载器现对 qualification 外层对象快照 schema，并仅接受其当前 legacy 标签 `core.f4.tallwall120.production_qualification_binding.v1`。Mapping 路径在 `deepcopy(dict(value))` 前拒绝缺失/unknown/synthetic schema；path 路径在读取文件 JSON 后、继续构造 binding 前同样检查。新增 public-entry 负测以 sentinel 确认 synthetic Diagnostic 只读取顶层 schema，不读取嵌套 summary/T1；现有合成 collection 成功路径继续可生成 diagnostic-only reader view。

## 验证

- `test_synthetic_qualification_rejected_before_collection`：通过。
- `test_complete_products_bind_reader_and_preserve_tall_wall`：通过。
- 定向测试 2 passed；collector/测试 `py_compile` 与 `git diff --check` 通过。
- 成功路径仅使用固定静态 design/template 和 `tmp_path` 合成轨迹/审计；未读取 production qualification tick/one-shot receipt，也没有写回仓库、调用 collector CLI、worker、solver、GPU、queue 或 GenCase。

## 重要限制

该标签明确是 legacy wrapper schema，不等于 V12 的 `core.f4.tallwall120.production_qualification_admission.v1`。当前代码仍允许带正确 legacy 标签的内联 summary 进入既有诊断逻辑；因此本次仅提供 schema 污染隔离，不满足 V10–V12 的 descriptor-root raw-byte/ref envelope、strict duplicate-key parser、exact nested refs、source-bound capability 或 trusted runtime identity。V12 要求旧 v1 wrapper 最终 fail-closed；在新 admission producer/root verifier 尚不存在时，collector 的 formal/T1 接纳仍不得据本次变更开放。未取得 Terra High/high 外部复核（agent thread limit），不记 reviewer PASS。
