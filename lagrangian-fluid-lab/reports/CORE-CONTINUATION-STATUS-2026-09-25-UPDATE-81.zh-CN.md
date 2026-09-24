# Core 计划续推状态 UPDATE-81

日期：2026-09-25（Asia/Shanghai）

## 本次完成

对 `scripts/core_formal_planner.py` 做只读静态调用路径盘点，并由指定 Terra High/high 做范围内复核。当前可达路径如下：

- `_load_json()` 接受任意内存 `Mapping`，普通路径则用 `json.loads(path.read_text())`；因此此入口没有 raw-byte duplicate-key 检查或 root-bound reader。
- `_iter_rows()` 接受多种 legacy collection/family/nested manifest 形状；formal manifest schema 未在遍历 case/family 字段前精确校验。
- per-case T1 与 hard-audit marker 可直接从 row 或 inline audit evidence 进入判定；外部 evidence schema 也没有 exact allowlist。synthetic Diagnostic schema 未被 planner 显式拒绝；bare payload 可能因缺 case collection 而失败，但带可接受 row/gate-shaped fields 的对象仍可到达 T1/audit 分支。
- 当没有 hold 时，`build_plan()` 构造 9 个 jobs 并报告 `launch_allowed=true`；可选 spec 输出绑定原 manifest，而非 V12 要求的 strict、sanitized `core.dataset.v2` projection。

## 复核与验证

- Terra High/high 只读静态复核与源码发现相符；无独立 model/effort identity attestation，不记作可审计 reviewer 身份证明。
- 本轮没有运行 `inspect_inputs()`、`build_plan()`、CLI、planner pytest 或 source-closure/训练流程；没有生成 job spec，也未读取生产训练 artifact、solver frame 或 bundle。
- 仅完成源码只读检查与调用路径比对；未改动 planner 代码。

## 明确未完成与状态边界

V11/V12 要求的 exact `core.formal_training_manifest.v1` ingress、strict recursive dataset projection、duplicate-key/raw-byte validation、descriptor/root-bound asset reader、外置 qualification/audit capability、KnownInputs contract hash 重算及确定性 projection 均未实现。Terra review 认为只补 `schema == ...` 字符串比较仍不足以安全开放规划；缺少 trusted launcher/root capability 时，planner ingress 应继续 fail-closed，而不能将 schema 标签当作来源认证。

因此 V8/V12 Core formal planner consumer gate 仍 BLOCKED。没有创建 formal job specs，没有启动训练、solver、worker、GPU、queue、native 或 GenCase；R008 仍为 `T1_numerical=false`、资格信用为零。F3/F4 已消耗的一次性授权与回执未触碰。
