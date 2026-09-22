# F2 第三家族动态候选交付：native DBC 旋转时长轴

本交付选择 `F2_dynamic_third_family_dbc_duration_x_v1` 作为第三家族候选。它研究有限接液槽中的满杯液体在规定旋转杯壁驱动下进入 receiver/catchment 的动态过程，边界机制为 native DBC `Boundary=1`。零运动 static hold 被明确排除，不能为该候选提供第三机制资格。

现有动态证据给出的选择依据如下：开放托盘动态记录了 `16,038` 个 native fluid position loss；移动杯 mDBC 记录了 4 个 `NpOutRho` 排除并有 full-vector closed-face contact 失败；native DBC 的 2.5 s/5 s canary 均通过 hard identity/geometry integrity，但 5 s 内没有 settled frame。q=.75、`dp=.0075 m` 是一个新的独立输入，旋转时长为 `1.025 s`，目标角 `-105°` 在 `1.525 s` 到达并保持到 5 s；它不是对 q=.5 或 q=1.0 失败 canary 的同输入重试。

这次 lineage 修订明确区分两个比较层次：static v3 是 full-cup native lattice 和固定体积的源输入；动态 closed-catchment 配方相对 static v3 确实新增固定 `mkbound=3` 的四面 catchment side walls，因此 `physical_geometry_changed=true`。候选的 single-change 语义比较既有 q=.5/q=1.0 native-DBC closed-catchment 动态基线；相对于这两个基线，杯、receiver、tray floor、catchment walls、runtime domain、DBC 和初态均冻结，q=.75 只改变 `rotation_duration_s`，故 `physical_geometry_changed=false`。

CPU/native preflight 已完成：GenCase、native decode、初始 native ID/有限性、零初始流速、full-cup source lattice 等价、native mass gate 和 motion target/hold 均通过。生成目录只有 CPU 输入和 native 预检资产，没有 `trajectory.h5`、`result.json`、`audit.json` 或 `observations.json`；solver、GPU、queue、ledger、registry 均未调用。

固定资格设计为 15 行：9 个 q=`0/.5/1` × 三个 `dp` 空间锚点，4 个 q=`.25/.75` held-out 行，以及 q=.5、`dp=.0075` 的 internal-time/native-output 两个 temporal comparator。交付时分母为 `15`、执行 `0`、通过 `0`、未执行 `15`。q=.75 preflight 只证明输入可执行，matrix credit 为 `0`。

所有动态行都必须通过 native identity、有限值、质量、closed-wall endpoint、saved-chord、运行域和完整 5 s event-window 门槛；settled 要求 `speed_p95 <= 0.10 m/s` 且 kinetic fraction `<= 0.05` 连续 `0.20 s`，并保存 `0.35 s` 后续输出。右删失保留为失败，不延长 horizon，不放宽阈值，不做 survivor renormalization。基础设施失败、科学 hard failure 和 event censor 都留在固定分母；历史 canary 不得替换或缩小 15 行。

候选卡、固定矩阵、失败分母、lineage clarification 和待 root 审查草案分别为：

- `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-candidate-card-v1.json` — SHA-256 `bf7ee6e0fe4c45f597e65ba66d4b5ebbdea0772c5d73ecf532cad45a3199814c`
- `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-matrix-v1.json` — SHA-256 `cf356f1cf7d0b02474ce7e6d215a9ff07eea0d6293aca5c87799014367c5dcf1`
- `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-failure-denominator-v1.json` — SHA-256 `037b22e8148c3c0f8f72f1b47550fd808072a5e3ce9810fadd0fda9fd04eda1b`
- `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-lineage-clarification-v1.json` — SHA-256 `abed3b35ea5459f725814cad574e636d2f6dd31ec51775f1c4cb6daeb70ab6b3`
- `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-root-review-draft-v1.json` — SHA-256 `bf06c26697e8b0b0c75af5ba2802fec87ce47f5b9ed8347aa0157e5ecd9489cf`

CPU/preflight 实现和独立 q=.75 prepared manifest 为：

- `scripts/f2_dynamic_third_family_dbc_duration_preflight_v1.py` — SHA-256 `eaa881580541f8f167ff0c50ab73433021b3ea579bae7fb9ed84fed82f6064e5`
- `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-q0p75-preflight-v1/prepared.json` — SHA-256 `0e20f0a1931f069b0b049a7f33b9b9e27bbc6293cd706708c9619d83e723ff9d`

新增 contract test 文件为 `tests/test_f2_dynamic_third_family_dbc_duration_contract_v1.py`，SHA-256 `b2543a38419dab51875a593b5df33b582a1158c3a9d642a06031feaaf2b01abc`，覆盖候选卡 hash/动态边界、15 行身份和映射、失败分母及历史负结果、root-review 禁止权限、prepared manifest 输入闭合、static/dynamic lineage clarification 六项契约；该文件 **6 passed**。本次只运行 CPU/只读定向检查，没有启动 solver/GPU/queue。

下一步准入条件是 root 先审查上述新 JSON、lineage clarification 和 prepared manifest 的 hash，确认 scope/case 不与旧 F2/H2 v4 证据重叠；通过后才可按 root-review 草案 CPU-prep 其余 14 行，每行必须重新生成并绑定自己的 Definition、motion、GenCase/native preflight 和输入 hash。任何 solver/GPU/queue 运行都需要另一个明确的 root approval，首个科学行应将 q=.75、`dp=.0075` 作为独立 matrix row，并同时取得 execution receipt、完整轨迹和 hard/event audit。只有 15/15 独立行同时满足 hard integrity 和 event-window complete，才允许进入后续 T1 资格讨论。
