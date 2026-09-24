# Core 计划续推状态 UPDATE-82

日期：2026-09-25（Asia/Shanghai）

## 本次完成

`core_formal_admission_audit._evidence_rows()` 不再从任意 raw evidence Mapping 的 `cases`/`rows` 中提取 per-case hard/structural markers。当前没有注册的 case-audit-set schema 或 source-bound capability，因此 `by_case` 固定为空；版本化 F3 adapters 仍由 `_bound_adapter_cases()` 单独处理，逐案 manifest audit reference 仍由 `_load_bound_json()` 单独处理。global T1 则保持仅接受 exact builtin string `core.qualification.v1` 的既有 discriminator。

新增端到端临时合成测试：构造带 V8 Diagnostic schema、附 gate-shaped per-case audit row 的 rewrap，断言它不增加 hard/structural bound counts，T1 保持 false，formal job count 为零。测试全程只用内存 Mapping 与 `tmp_path` manifest。

## 复核与验证

- `tests/test_core_formal_admission_audit.py` 两个定向 synthetic nodes：2 passed。
- `py_compile` 与 `git diff --check` 通过。
- 指定 Terra High/high 只读复核未发现本次 `by_case` 隔离路径问题；复核指出的 residual risks 保留如下。无独立 reviewer identity/effort attestation，不作为资格或可验证身份证明。

## 明确未完成与状态边界

此处仅关闭“任意 raw row collection 进入 per-case evidence channel”的旁路，不构成 producer/source 认证。精确 `core.qualification.v1` 仍可由任意 Mapping/JSON 自述；schema 只是分类，不是身份。legacy hard adapter 逐案绑定仍弱于 structural adapter；manifest 引用 audit 尚无专用 exact receipt schema、可信 raw-byte/root reader 或 runtime identity。V8/V12 overall consumer gate 继续 BLOCKED。

无 planner 或 job spec 生成，无训练、solver、worker、GPU、queue、native、GenCase 执行；未读取生产收据、bundle 或 solver frame。R008 `T1_numerical=false`、资格信用为零，F3/F4 已消耗的一次性授权和历史回执未改写或重试。
