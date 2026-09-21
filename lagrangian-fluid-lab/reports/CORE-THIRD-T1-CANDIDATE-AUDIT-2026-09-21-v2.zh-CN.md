# Core 第三个 T1 候选：独立只读审计与 root-review proposal gate（2026-09-21）

**状态：审计/提案门，不是资格完成。** 本文件只汇总共享工作区已有输入和证据；不增加 T1 credit，不改变 registry、ledger 或任何固定 matrix。审计期间没有启动 GenCase、native solver、GPU 或 queue。

## 结论先行

Core 当前登记的 T1 family 仍是 `F3/F4`，第三 family 尚未建立：`completion.json` 的 `three_t1_families=false`、`missing_t1_case_runs=288`、`can_finalize=false`。因此，旧报告中“F2 submerged-orifice v2 等待 root review/CPU preflight”的建议已经过时。v2、v3、v4 的 CPU/native 结果已经写入共享工作区，而且全部在硬输入门失败；它们都没有 solver/event 证据，也没有资格 credit。

按“当前可执行的最小下一步”排序，我给 Core 的选择是：

| 顺序 | 路线 | 机制是否真正不同 | 当前状态 | 最小下一步 |
|---|---|---|---|---|
| 1 | `F5_wave_runup_piston_scale` | 是：移动活塞、斜坡 run-up、回流 | 有独立 proposal；root 已只授权写一份全新的 Definition 和 scaled motion，尚未有 Core CPU/native、canary 或 T1 credit | 写 fresh Definition/motion 并提交第二次 root review；在第二次 review 前不做 CPU/native |
| 2（若 Core 必须选 F2） | **新的 F2 几何/法向假设**，身份待定 | 可以是：固定水库经 submerged aperture 的 underflow；现有 orifice 拓扑本身不同于 weir/旋转杯 | 现有 orifice v2/v3/v4 线已关闭；不能把 v2 重新标成 pending | 只写一份全新的 root-review-only 静态提案，绑定新 scope/case、几何/法向理由和 hash；当前不写 Definition、不运行 GenCase |
| 3 | F2 receiver/overflow-weir | 是：固定水库越过内部 crest | 15 行中仅 1 行执行，`hard=false`、`event=false`、`credit=0`；关闭，不同输入重跑 | 无；除非另立全新物理问题和新 scope |
| 4 | F1 suspended-obstacle gap G1 | 几何是新的，但仍属 F1 family | CPU/native 通过；实际完整 anchor `hard=false`，事件虽完成仍不能资格 | 关闭当前 G1 线；若要继续，另立 F1 新物理假设 |
| — | F4 tall-wall | 已是合格 F4 | `T1_numerical=true`、matrix/checks 完整 | 不作为第三 family 候选 |

所以，**当前授权下可以生成 root-review proposal，但只能是本审计所描述的全新假设的静态 proposal；不能再生成或恢复 submerged-orifice v2 proposal，也不能用 proposal 的存在代替 CPU、canary、完整事件窗或资格完成。** 若 Core 只接受 F2，最小可执行动作是先让 root 审查“全新 F2 几何/法向 construction contract”；审查通过后才可另行授权一次 fresh CPU/native preflight。

## Core gate 与现有 F1/F4 记录

`campaigns/core-v1/completion.json` 的当前摘要是：

- `t1_families=["F3","F4"]`，`three_t1_families=false`；
- `t1_denominator_complete=false`，仍缺 `288` 个 T1 case runs；
- `evidence_valid`、`causal_lineage_contracts`、`independent_reproduction` 为 true，但这不等于第三 family 已合格。

F1 的 `cfd/f1-qualification-evaluation.json` 明确为 `qualified=false`、`T1_numerical=false`；canary、hard mass/event 和 matrix checks 没有同时通过。F4 的 `cfd/f4-tallwall120-range-qualification-root-v2.json` 已有 `T1_numerical=true`、`matrix_complete=true` 及全部列出的 checks 通过。再增加 F4 运行不能增加“唯一 family”计数。

## F2 倾倒/接液路线审计

### 1. 动态 DBC duration / moving cup

`F2_dynamic_third_family_dbc_duration_x_v1` 只改变旋转持续时间，仍是 moving cup/DBC 倾倒路线，不能作为一个新的物理机制。q=.75、`dp=.0075` 的已有 5 s anchor 达到请求时长，`hard_integrity=true`，但 receiver contact 在约 `1.10002 s`、motion 在 `1.525 s` 结束，settled 未发生，`event_window_complete=false`；固定 15 行的 formal row 仍是 `not_started`，anchor 明确排除在 numerator 外，credit 为 0。记录要求停止该 duration scope，不扩展同一分母。

静态 full-cup 的 15 行 CPU/native pass 只是零运动输入门；H2 mDBC 静态运行已有 8/8 科学失败，不能替代动态 pouring/receiver event。open tray 和 closed-catchment moving-cup 记录还分别有 native ID 丢失或 closed-face/事件失败，均不建议同输入重跑。

### 2. Receiver/overflow-weir

这是和 rotating cup、orifice 不同的机制：stationary upstream reservoir 越过固定有限高度 crest 进入 receiver。CPU/native preflight 只证明输入合同：`474147` total、`245667` boundary、`228480` fluid、zero normal `0`、ID/finite 通过，native mass 相对误差 `-0.00390625`，且明确 `solver_invoked=false`、`gpu_invoked=false`。

但当前 terminal matrix 已经记录真实运行结果：固定分母 `planned=15, executed=1, passed=0, failed=1, event_censored=1, unattempted=14, credit=0`。q=.5、crest `.26 m`、`dp=.0075` 的唯一运行同时 `hard_integrity=false` 和 `event_window_complete=false`；runtime 记录有 `1,490,609` 次 chord crossing、74 个 endpoint violation frame，receiver contact 只到约 `1.01%` 质量。这个 route 已有可解释的负锚点，不能把 CPU preflight pass 当作资格或再作同输入 retry。

### 3. Submerged-orifice：机制不同，但现有 remediation 线已硬关闭

父 scope 的物理机制是固定水库在上方 gate slab 下通过 submerged aperture 向 downstream receiver underflow；没有 crest crossing、旋转杯运动或 F3 impulse。就科学问题而言，它确实和 F2 weir、moving cup、F1/F3 不同。但 `normal-remediation-v2/v3/v4` 是同一 F2 orifice scope 的静态修复版本，不能互相计为不同 family。

当前 CPU/native 证据如下（全部 `matrix_credit=0`、`solver_product_present=false`）：

| 版本 | 生成规模 | 主要硬失败 | 其他结果 |
|---|---:|---|---|
| v2 | `496104` total | `64899` 个 zero `BoundNor` 和 `64899` 个 zero `NormalSize`；mass relative `+0.04718017578125`，阈值为 `.025` | IDs、finite、gate/outer endpoints 通过；`preflight_pass=false` |
| v3 | `475631` total | `83443` 个 zero `BoundNor` 和 `83443` 个 zero `NormalSize`；mass relative `-0.04207502092633919` | IDs、finite、endpoints 通过；`preflight_pass=false` |
| v4 | `487074` total | `29484` 个 zero `BoundNor` 和 `29484` 个 zero `NormalSize` | mass relative `+0.0078125` 通过，但 v4 partition audit 显示 29484 个零值全在 `Mk=18` gate boundary，`Mk=17` outer boundary 为 0；仍 `preflight_pass=false` |

v4 的只读 partition audit 已把当前失败归因收敛到 gate normal construction，并明确 `no_route_authorization=true`、`same_input_retry=false`。因此，旧路线审计中的“v2 还没 CPU/native”不能继续作为现状；v2 已经有失败输入证据，v3/v4 也没有救回 hard zero-normal gate。orifice 目前还缺：

1. 全新且可证伪的 geometry/normal hypothesis、fresh Definition/case identity 及其 hash closure；
2. 新输入的 CPU/native preflight（zero normal/size、ID/finite、overlap/endpoints、mass gate）；
3. preflight 通过后的独立 root review 和一个 protected solver canary；
4. 达到注册的 `1.5 s` 完整事件窗、hard integrity、receiver contact/underflow crossing 及质量保持的证据；
5. 完整 15-cell fixed denominator，以及其后单独的 production denominator。当前没有任何 orifice solver trajectory、完整事件窗或 T1 credit。

## F1 对照：静态通过不等于可运行资格

G1 suspended-obstacle 的确改变了连续体几何：障碍物由贴底 `[0,.34] m` 提到 `[.06,.40] m`，形成真实底部 fluid corridor。因此它是新的 F1 几何假设，但不是新 family。其 CPU/native preflight 通过：`120658` fluid、`142446` boundary、zero normal `0`、overlap `0`、面向检查通过、mass relative `0.01707548`。

已有完整 G1 anchor 随后给出相反的运行结论：请求 horizon 到达且事件窗 `complete=true`，但 `hard_integrity=false`，包括 `84` 个 closed-wall endpoint particle frames、`615` 个 obstacle-penetration particle frames、`1700` 个 finite-geometry chord crossings、`lifecycle:closed_transition`，初末有效粒子为 `120658/120577`。因此 G1 的静态 pass 没有资格意义，当前线关闭且 credit 为 0。这个证据也说明 F2 新候选必须把 CPU/native gate 与 full event hard gate 分开验收。

## root-review proposal 的最小合同

本审计不创建新的 Definition、XML、BI4、trajectory 或 job。若 root 选择继续 F2，proposal 必须至少绑定以下项目后才可审查：

1. 新 `scope_id`/`case_id` 和新 output stem；清楚说明 aperture/crest/normal construction 哪一项改变了物理或离散拓扑；
2. 新 Definition、源几何和法向生成方法的 hash 计划；禁止复用 v2/v3/v4 的 generated XML、BI4、BoundNor、trajectory 或只改标签；
3. 固定 15 行分母、q/dp mapping、observer 和失败保留规则；CPU/native 只能给 `0` credit；
4. root 先批准**一次** fresh CPU/native preflight，且这份批准不包含 solver、GPU、queue、ledger、registry 或 matrix mutation；
5. preflight 必须同时满足：zero `BoundNor`/`NormalSize`，ID 与 XML 一致且唯一，数组 finite，fluid/boundary 不重叠，gate/outer endpoints/chord gate 通过，native mass source error ≤ `.025`；
6. 只有 fresh preflight 全通过且取得第二次 root review 后，才可提交一个 protected anchor。anchor 必须完整观察 1.5 s；只有 hard pass 后才允许合同规定的一次 whole-scope extension 到 3.0 s，event censoring 仍留在固定分母；
7. anchor hard/event pass 后才可 materialize 15-row matrix。即使全部通过，也还需要独立 production denominator 和 Core evaluator，不能由这份报告晋级。

对 F5，现有 root review 已明确允许的动作更窄：只写 q=.5、`dp=.0075` 的 fresh literal Definition 和 scaled motion，然后再次 root review；当前仍禁止 CPU/native、solver、GPU、queue、ledger、registry 和 matrix。F5 的 R3 probes 只有 candidate-only 外部 gauge 支持，不能当作 Core T1 evidence。

## 资源估算（只用于规划，不是预留）

下表把已测 runtime 和尚未能测量的部分分开；本轮没有提交任何资源。

| 项目 | 已有测量/估算 | 解释 |
|---|---|---|
| F2 weir terminal anchor | `313.262 s` wall、`0.087017 GPU-h`、peak GPU `558 MiB`、max RSS `2133.6 MiB` | 已完成的负证据；不能据此授权下一次运行 |
| F2 dynamic DBC q=.75 anchor | `364.697 s` wall、`0.101305 GPU-h`、peak GPU `606 MiB`、max RSS `1857.9 MiB` | 已完成的 event-censored 负证据 |
| F2 orifice 新 hypothesis | **规划估计**：CPU/native 不需 GPU；protected anchor 约 `0.10–0.20 GPU-h`、`5–10 min` wall；15 行约 `1.5–4 GPU-h` 粗估 | 只按同 dp、约 0.49M 粒子的 weir 负锚点作保守比例；必须等新 preflight 后重估，不能提交 |
| F1 G1 anchor | `134.321 s` wall、`0.037311 GPU-h`、peak GPU `514 MiB`、max RSS `368.1 MiB` | 已完成的 hard-negative anchor；当前路线关闭 |
| F5 Core | R3 外部 probe 在 `dp=.03/.025/.02` 的 solver wall 为约 `57.7/103.1/150.3 s`；Core `.01/.0075/.005` **尚无可靠 estimate** | 只能在 fresh Definition、CPU/native 和 source/output contract 完成后估算，不能把 R3 数字当 Core 预算 |

## 验收结论与未完成项

- **第三 family：未建立。** `qualification_credit_added=0`，`core_gate_changed=false`。
- **F2 v2：不能再作为最小下一步。** v2/v3/v4 的硬失败输入证据是当前阻塞；最小动作是新假设的 root-review-only proposal。
- **最小可执行选择：** 若允许切换 family，按 F5 的 fresh Definition/motion → 第二次 root review → CPU/native → protected full-window anchor 顺序推进；若必须 F2，先完成新 geometry/normal contract 的 root review，停在静态提案层。
- **缺失证据：** F2 新 orifice 没有 fresh static pass、CPU/native canary、solver canary 或完整事件窗；F5 没有 Core Definition/motion hash closure、CPU/native 或 Core event；F1 G1/F2 weir 已有完整负证据，不能靠报告重开。
- **本文件不构成完成：** 不改变现有 registry、ledger、matrix 或 denominator，也不授权任何运行。

## 审计输入 SHA-256

| 输入 | SHA-256 |
|---|---|
| `campaigns/core-v1/completion.json` | `eb25d9878ce8b005a1e6fe6c481671ad4c223beafb3f1104601a8a3dc67311e0` |
| `campaigns/core-v1/registry.json` | `1ddfeda5b2d3eb142f94be4bb2cbc6f1b65271d6b77efc8b65c829b94e66b38d` |
| `campaigns/core-v1/cfd/f1-qualification-evaluation.json` | `a88578e9e661f80cece90412ca7fb69c6add437f33742ec6ac731399e3121027` |
| `campaigns/core-v1/cfd/f4-tallwall120-range-qualification-root-v2.json` | `88bf903dbf2345dff9d0c9ac507ea3d9cef1387ba6fdcbd4ea8168f9828c770d` |
| `campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json` | `d9bd24ead4064b1e4f87aa8194be668370b0a3648835309791399ae3194a37e2` |
| `campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json` | `0bba913c75b2a716b0756154239e11595feb753b428e2b4745563c5da3ff841d` |
| `campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/cpu-native-preflight-v1.json` | `b1507eca9120d85a6ea620d7be2c42321b3eff3deb29267be25f6fcc00d45127` |
| `campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-matrix-v1.json` | `8089ceb988ee8ed0e51bfb135939affe237741478f368cf7d6acc4f1367e12e4` |
| `campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/candidate-card-v1.json` | `0726648a24db7b0889870b7c35f852503dca42288cf88cd780408eb1167fac1d` |
| `.../normal-remediation-v2/preflight-v4/preflight.json` | `90123f1c0ab3b776a306729c92d1d5dbb6281190e19511245a724f83036e1113` |
| `.../normal-remediation-v3/preflight-v3/preflight.json` | `90b8c460262ad1424aab42dbc0046f1bf3b511478ddc0b5e240fd83b87485dd7` |
| `.../normal-remediation-v4/preflight-v4/preflight.json` | `db18863a97cb0a6d17a2cbb877e7b3df94368c96be4176728bd7b15b8a698685` |
| `.../normal-remediation-v4/v4-current-failure-partition-audit-v1.json` | `74d7395e697db199d05e70b2795540812fae8170c2e69247f26258c1e2141bdd` |
| `campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json` | `2a72700b40c08c4a11ac38b55cccb40a85b7fecf940f612bc974dd88fc3a3760` |
| `campaigns/core-v1/cfd/f5-wave-runup-root-review-v1.json` | `c47481f9700543a238a44f13c9aa64b21862ced4a813d78d720eaa1cec741d16` |
