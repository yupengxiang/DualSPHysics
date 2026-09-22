# F2 H2 mDBC v5：8-cell batch root-review 就绪审查

日期：2026-09-20（Asia/Shanghai）  
范围：`F2_H2_mdbc_static_range_qualification_v5`  及其 F2 dynamic DBC 第三家族候选  
执行边界：只做只读审查、admission、job-spec 草案和证据收集器验证；本次没有启动 solver、GPU、queue，也没有修改 Core registry 或 ledger。

## 决定

static H2 v5 可以进入 **root review**，但当前不能进入可执行的 8-cell solver batch。现有 v5 root review v2 只授权 cell 11 的单 cell runtime smoke；其 `authorized_cell_indices=[11]`，决定为 `approved_for_runtime_smoke`，没有授权前 8 行。因此本次不提交 job、不启动 solver。

v5 CPU/native closure 是完整的：固定 15 行均已通过 GenCase/native decode，15/15，失败分母仍为 15，所有行 `qualification_credit=false`。cell 11 的正 runtime canary 只证明 hard-integrity/runtime 可读性，`matrix_credit=0`，静止 hold 的 event window 为 `not_assessed`；它不能替代 15 行资格执行，也不能建立 T1 或第三动态机制。

“8→32”是 Core production 的批处理规则，不能改写本 scope 的固定 15 行 qualification denominator。本次草案因此明确标记为 `first_8_of_fixed_15`，并写入 `fixed_8_to_32_compatible=false`；剩余 qualification 行是 8..14，不能按 32 行 survivor 分母处理。

## 新增交付物

独立适配器 [f2_h2_mdbc_static_range_v5_batch.py](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_h2_mdbc_static_range_v5_batch.py) 完成三项只写本地文件的功能：

- 校验 candidate、15-row matrix、cell 11 zero-credit canary 和 forbidden mutation，输出 `root_review_ready` admission；
- 固定登记顺序的 0..7 八个 cell，生成带 source/matrix/candidate/adapter hash 的 **不可提交 job-spec 草案**；job `argv=[]`，全部 `solver/gpu/job_spec/queue` 权限为 false，ledger/registry 权限为 false；
- 读取未来 attempt 的 receipt、prepared、result、audit、trajectory，区分 `infrastructure_failed`、`scientific_failed`、`event_censored` 和 `passed_zero_credit`，并始终重建 15 行分母。任何 batch pass 仍是 zero credit，不能触发 T1。

生成的 root-review-ready 目录为 [f2-h2-mdbc-static-range-qualification-v5-batch8-root-review-v1](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-batch8-root-review-v1)：

- [admission.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-batch8-root-review-v1/admission.json)：15-row denominator、0..7 batch、`qualification_only=true`、T1/ledger/registry 全部关闭；SHA-256 `c328698e0f3b886bb1dc9c2a50eecd2db1bd351bb48b7228ceca8364ff7bc12a`。
- [batch-job-specs.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-batch8-root-review-v1/jobs/batch-job-specs.json)：8 个 cell job spec manifest，状态 `root_review_ready_not_submitted`；SHA-256 `28599c7a263fba4e2c50a81a4a870cdf33f7e10dc2baea309567e856c8b938f8`。
- 8 个 job spec 位于同一 `jobs/` 目录，cell indices 为 `0,1,2,3,4,5,6,7`；每个 spec 都显式保留 registered denominator `15` 和 `qualification_only=true`。
- 逐项 job-spec SHA-256：cell00 `ad92f9e6e6398290a7af95fd5689d51d365a95ff7fd26bc240b37b148b5adab9`，cell01 `e76f72746ef5f1623af7c924ad47b913724675caa45a30a9d9fc98017695afbd`，cell02 `c3d2d19d19d0a0034bc2664fba1a3c76a61e404c57fa7307e74a4a274f4e709b`，cell03 `fb1cf617d7c2d002e7f41a0fc163cf8f29f206651ec32c3a60fd0f1ae9c8ecc3`，cell04 `54234f5b03ddd189cf60c9706fe6c9d3115bb3d5c50b8a3146f2eddb2404bbf2`，cell05 `8100e0a52e873b6916d1683a4849f5b849e04873885e1ea098f96e790934a9dd`，cell06 `edb4213ad43a8a36b2722390c3963bf8d05e1994f42452b970861246410c4136`，cell07 `e41e034676284f484981c1a6d17d31f5523e472560bef44cf8fa399dc9928679`。
- [execution-evidence-empty-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-batch8-root-review-v1/execution-evidence-empty-v1.json)：在没有 attempt 的安全 dry collection 中记录 15/15 `unattempted`、batch attempted `0`、matrix credit `0`；SHA-256 `c7f3f737a65d1af20b06aabadfb4b8c202fa63639c86d2654fd9741a6e659bf6`。

Admission/collector 代码 SHA-256 为 `ad8a01fb749b0ca9e451a076466cdb06c169e254a5246ed5c788ef7997fc96ba`；对应 contract tests [test_f2_h2_mdbc_static_range_v5_batch.py](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_h2_mdbc_static_range_v5_batch.py) SHA-256 为 `50d9bb64bc1fdeef30839aede085ea1875f2c71f2bd3dbacbd60083448895558`。

## 输入和既有 root 规则

本次 admission 重新绑定以下只读输入：

- v5 candidate card：`campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json`，SHA-256 `b0b1691aa24f2db3b5ee886a6fea917a63fd2784219e33d983393f8607433f33`；`qualification_only=true`、`qualified=false`、`T1_numerical=false`、ledger/registry mutation 为 0。
- 15-row CPU/native matrix：`.../f2-h2-mdbc-static-range-qualification-v5/prepared-20260920-v5-all/matrix-preparation.json`，SHA-256 `d82e019cd59d26dbed6846912371062206b6e6ef4b83568537d822a9fa8f0495`；15/15 preflight pass、15 行 zero credit。
- cell 11 runtime evidence：`.../runtime-canary-evidence-cell11-v1.json`，SHA-256 `28bb42c91cc00c293a0be7d17570cf39c6e080e66c37f86447fe5a8cbe792735`；hard integrity pass、event `not_assessed`、matrix credit 0、ledger/registry 0。
- 现有 cell 11 root review：`f2-h2-mdbc-static-range-qualification-v5-runtime-root-review-cell11-v2.json`，SHA-256 `e1411397f1dfe97da5feb8c5c8953ca90e09f07c90a43b0479b0e094ddf75e75`；只授权 `[11]` 的 solver/GPU/queue smoke，且禁止 ledger/registry。把它传入 batch admission 会被拒绝，防止单 cell authorization 被误当成八 cell authorization。

本次保留 `parent_v4_failed_cell_11_retained=true` 及 v4 cell 11 的 source error `0.02806106870228997`；v5 修复后的第三层 error `0.004152671755724757` 只属于 CPU/native sampling closure，不是 runtime 或资格分子 credit。

## dynamic DBC 第三家族审查

dynamic DBC candidate `F2_dynamic_third_family_dbc_duration_x_v1` 不适合作为本次无 ledger 的 8-cell 路径：

- 它也是固定 15 行设计，q=.75/dp=.0075 anchor 的 CPU/native preflight 通过，但实际 anchor canary 在 5 s 达到 horizon 后 `hard_integrity_pass=true`、`event_window_complete=false`，分类为 `scientific_event_censor`，matrix credit 0；negative evidence 为 [f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json)，其 SHA-256 `0bba913c75b2a716b0756154239e11595feb753b428e2b4745563c5da3ff841d`。
- dynamic root review `f2-dynamic-third-family-dbc-duration-root-review-first-row-v1.json` 只覆盖 matrix index 11/anchor first row，并且历史 first-row job spec 明确带有 `ledger_mutation_authorized=true`；negative evidence 的 `execution_controls` 记录 `ledger_mutation=1`、`queue_mutation=1`。这违反本次“禁止 ledger/registry mutation”的新 batch 边界，不能复用为 8-cell authorization。
- dynamic failure denominator 仍固定 15，formal held-out row 11 还是 `not_started`；anchor 不是 formal matrix row，不能把 event-censored anchor 当资格 pass。现有规则要求停止同输入 retry、禁止 horizon/threshold 放宽，也不能据此宣布第三 T1 family。

因此 static v5 只提交为独立 qualification-only root-review-ready artifact；dynamic DBC 留在 negative evidence/blocked dependency，待 Core root 另行决定是否提出全新的物理 hypothesis 和全新授权。static H2 positive canary 也不被解释为 dynamic mechanism 或 Core third T1。

## 验证和下一步依赖

定向测试：

```text
./.venv/bin/python -m pytest -q \
  tests/test_f2_h2_mdbc_static_range_v5_batch.py \
  tests/test_f2_h2_mdbc_static_range_v5_prepare.py \
  tests/test_f2_h2_mdbc_static_range_v5_runtime.py
12 passed
```

下一步必须按以下顺序执行：

1. root 审查 admission、8 个 job spec 的逐项 hash，并新发一个明确覆盖 `authorized_cell_indices=[0..7]` 的 review；该 review 必须允许 solver/GPU/job/queue，同时明确禁止 ledger、registry、material/model training，并保持 `qualification_claim=none`。
2. 获得上述新 review 前，不得使用现有 cell 11 review 生成 runtime view、提交 queue 或启动 solver。获得 review 后仍需逐 cell 生成新的 hash-bound runtime prepared view；本次草案不会自动转为可执行 spec。
3. 每个 attempt 必须收集 execution receipt、prepared、result、audit、trajectory，并要求 hard integrity、完整 registered horizon 和 event window 同时通过；任何基础设施失败、hard failure 或 event censor 都保留在 15 行分母，禁止同输入 retry、survivor renormalization 和 horizon extension。
4. 八行完成后仍只得到 8/15 的中间执行证据；必须继续处理固定剩余行 8..14，并由 Core qualification evaluator 独立审查 15/15，之后才讨论任何 T1。Core registry 和 ledger 在整个路径中保持不变。

本报告本身只记录审查和新草案，未产生 registry/ledger mutation；solver/GPU/queue invocation 均为 0。
