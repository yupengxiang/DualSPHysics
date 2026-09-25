# Core 计划续推状态 UPDATE-109

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V5 source fragment 与 clean Git HEAD 的原始字节对照

新增 `inspect_untrusted_v5_source_callgraph_against_clean_git_head`。它先按 V5 synthetic callgraph schema 校验声明结构，然后限定于固定 `source_file_object_id → src/source/...` 映射，从 Git `HEAD` 读取 tracked regular-file blob；对所引用源路径要求 Git 状态干净，并通过 directory FD + `O_NOFOLLOW` 重新读取工作树文件，要求工作树 bytes 与 HEAD blob 完全相等。对每个 fragment 检查半开 byte range 位于文件大小范围内，并以 HEAD blob 对应 slice 重新计算 SHA-256。

新增临时 Git 仓库合成测试，覆盖正确 slice、fragment hash 不匹配、工作树源文件偏离 HEAD。V5 parser focused suite **60 passed**；`py_compile` 通过。GPT‑6 Luna Max 只读安全复审正在进行；最终 `git diff --check` 与提交待复审后执行。

## 能证明与不能证明的内容

成功结果只说明 JSON 自报的 range bytes/hash 与当前本地 HEAD 中同一路径切片相等。它不证明 range 是对应 C++ function 的完整 definition，不重算 normalized AST/call edges，不证明 feature/macro 覆盖，不把 Git HEAD/source tree SHA 与 build attestation、加载的 binary 或 runtime image 交叉绑定，也不验证 descriptor root 或 trusted event source。相关输出始终为 `source_function_definition_ranges_verified=false`、`source_fragments_reparsed_from_source=false`、`source_tree_sha256_matched_build_attestation=false`、`source_callgraph_verified=false`、`gate_state="open"`、zero credit。

本执行环境检测到 GCC 11 / `cpp`，未检测到 Clang、Tree-sitter Python bindings 或 GCC plugin development headers。因此本轮明确停在 raw-source bytes 比较；没有用 lexical/regex 命中假称完成 V4/V5 所要求的 compiler-frontend AST extractor。

本轮只处理小型合成 Git 仓库和 tracked source bytes；未读取 production bundle/HDF5/one-shot receipt，未运行 planner/tick/canary/preparation/GenCase/native/solver/worker/GPU/queue。F8 T1、完整可信 source/build/runtime closure 与 PLAN Core 完成条件仍未满足。

注：本报告记录 UPDATE-109 初版实现。后续只读复审发现其 Git 环境、HEAD 固定、根目录绑定和读取上限仍需加固；当前实现与修复测试以 [UPDATE-110](CORE-CONTINUATION-STATUS-2026-09-25-UPDATE-110.zh-CN.md) 为准。

## 后续依赖

下一步需提供并固定受支持的 C++ frontend 与精确 build feature/flags，再实现 source function-definition range、normalized AST 和 ordered call edge 重算；之后才可做 runtime/config topology 与 journal entry 的绑定。除此之外，event-source completeness、active-window/table provenance、outer evidence/attempt binding 和可信 consumer 仍未闭合。
