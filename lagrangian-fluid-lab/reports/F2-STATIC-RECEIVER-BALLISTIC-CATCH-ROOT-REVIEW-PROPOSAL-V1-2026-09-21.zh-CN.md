# F2 静止接液盆弹道捕获路线：Root Review Proposal v1

**版本：** `v1`　**日期：** `2026-09-21`　**阶段：** `proposal_only_root_review_required`

## 判定

当前最有证据、且机制上真正独立的第三个 F2 T1 候选是
`F2_static_receiver_ballistic_catch_x_v1`。每个 case 都使用固定的外槽和固定的接液盆：一团有限液体从接液盆上方自由下落，接触后观察进入接液盆的质量与溢出质量。q 只改变接液盆在 y 方向的固定中心位置；它不驱动壁面、不使用旋转杯、不设置堰顶或水下孔口。

这份交付物只到 root review。它没有建立第三个 T1 家族，没有加入 qualification claim，没有写入 registry、ledger 或 matrix。固定分母为 **15 = 13 个空间设计格 + 2 个时间输出控制格**；当前 `executed=0`、`credit=0`，`qualification_claim=none`、`matrix_credit=0`。

## 现有 F2 资产审计

提案 JSON 绑定了 17 份只读证据，并在结构校验中逐一重算字节数和 SHA-256。关键结果如下。

| 已有路线或记录 | 已读结果 | 对新路线的约束 |
|---|---|---|
| `campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1` 下的 v2/v3/v4 失败记录 | v2 有 64899 个零 `BoundNor/NormalSize`，质量相对误差约 `+0.04718`；v3 有 83443 个零值，约 `-0.042075`；v4 的 29484 个 gate/normal 输入失败，质量约 `+0.0078125`，preflight 为 false | 只作负证据；新路线禁止复用 Definition、XML、BI4、normal、trajectory、output stem 或同输入重试 |
| `campaigns/core-v1/cfd/f2-side-wet-dynamic-v1-root-integration.json` | `missing_native_ids=13527`，`hard=false`，事件为 false | 不沿用 moving-cup/side-wet 输入 |
| `campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-matrix-v1.json` | planned 15，executed 1，passed 0，failed 1，event censored 1 | 不把堰顶越流换名后继续跑 |
| `reports/F2-H2-MDBC-STATIC-HOLD-NEGATIVE-AUDIT-2026-09-21.zh-CN.md` | 8/8 scientific checks failed，包含 static speed、kinetic 和 open-cup escape 问题 | 不采用 static-hold/mDBC 入口 |
| `reports/F2-STATIC-FULL-CUP-CPU-PREFLIGHT-2026-09-20.md` | 15/15 仅有 CPU/native closure，尚无 qualification | 不继承 static full-cup 的输入或资格 |
| `cases/F2/F2_airborne_slug_*` 与 `data/F2_airborne_slug_*.h5` | centered/offset/two-layer 的 identity 分别为 `0.9885714286`、`0.9942857143`、`1.0`；均为低于 500 粒子的 plumbing evidence | 只支持“弹道转移观察链可执行”的有限假设，不继承旧 Definition 或输出 |
| `campaigns/v0.1-candidate/W04-CONCLUSION.md` | 旧 airborne slug 的 pre-impact COM 误差为 `0.0186 dp`，结论限定为 limited-range | 仅作为重力/轨迹的先验，不能代替新接液盆验证 |

Core 当前 completion 仍只列出 `F3`、`F4`，第三个 T1 family 为 false，且有 288 个缺失 T1 case。上述现状没有被本交付物改变。

## 新机制与 fresh-input 边界

新候选的 mechanism class 是 `stationary_receiver_ballistic_slug_capture`。建议的几何契约如下；这些数值是 root review 输入，尚未被写成 Definition：

- 固定外槽低点为 `[0.0, -0.45, 0.0] m`，尺寸为 `[1.25, 0.90, 0.80] m`，底面和四个侧面闭合，顶部开放。
- 固定接液盆的 x 范围为 `[0.35, 0.85] m`，z 范围为 `[0.08, 0.58] m`，y 尺寸为 `0.36 m`，底面和四个侧面闭合、顶部开放；接液盆底与外槽底保留 `0.08 m` 间隔。
- 接液盆中心为 `y_center = -0.12 + 0.24*q m`，所以每个 case 的接液盆仍是静止的，q 只选定静止位置。
- 液体源为固定在 `[0.48,-0.09,0.65] m`、尺寸 `[0.24,0.18,0.18] m` 的有限液块，初速度为 `[0,0,-0.20] m/s`；初始状态与接液盆不重叠，质量使用 native `rho*dp^3`，不重标定。
- 预计使用 native DBC 的固定边界；没有 mDBC normal 文件、moving boundary、crest、submerged aperture 或受控壁面速度。

因此它和既有失败路线的物理事件不同：事件是“下落源接触固定盆后，在盆内保留与外槽残余之间形成质量分配”，而不是 moving-cup settling、side-wet、堰顶越流或水下孔口转移。候选 JSON 同时列出旧 scope 的 forbidden sources；旧 generated/native/trajectory 不会进入新 namespace，也不允许把同一输入改名重试。

## 冻结设计与观察契约

15 个固定 rows 的空间部分是 9 个 qualification q（`0.0, 0.5, 1.0`）与三个 `dp`（`0.010, 0.0075, 0.005 m`）的组合，加上 4 个 held-out q（`0.25, 0.75`）与中、细两个 `dp`。剩余两行在 `q=0.5, dp=0.0075 m` 固定几何上分别检查 `internal_time` 和 `native_output` 控制。注册时间窗为 `1.5 s`，最长可延长到 `3.0 s`，输出间隔为 `0.005 s`；任何延长都不能先于 hard pass 和 root review。

每一行都留在分母中。CPU/native preflight、root anchor、solver 失败、hard-integrity 失败、事件 censor 或缺输出都记为零 credit；不允许 same-input retry、阈值放宽、提前延长或 survivor renormalization。

拟定的 hard integrity 包括：达到 `1.5 s` horizon；fluid ID 唯一且无 active ID 缺失；位置、速度、密度和质量有限；外槽和接液盆闭合面无 endpoint/chord crossing；无粒子出 runtime domain；native 初始质量与全窗质量变化满足固定门槛。事件需要下落源进入接液盆高度带、至少 1% 初始质量进入一 dp-clear 的盆内区域，并在接触后至少 `0.20 s` 保持接液盆/外槽质量分配总和达到 95%；未完成的事件按 right-censored 失败行处理。

## Root review 依赖与硬 blocker

当前没有 fresh Definition、native preflight、solver trajectory 或 event audit，因此不能把这份 proposal 当作 qualification evidence。旧 airborne 证据粒子数低于 500，只能证明有限的 plumbing/弹道先验。接液盆与外槽的边界所有权、`0.08 m` 间隔、q 两端的 partial-capture 语义，都需要 root 审阅 literal Definition 后才能冻结。

若 root 接受机制，后续依赖必须按以下顺序执行：

1. root 审阅机制差异和本提案的全部绑定；
2. 另写一份 literal new Definition 和全新的 output namespace，随后由 root 单独授权一次 CPU/native preflight；
3. 先审阅新 Definition hash 与 preflight receipt；任何 hard input failure 都停止该 scope，并保留全部 15 个分母格；
4. 只有 fresh CPU/native pass 加第二次 root review 后，才可授权 `q=0.5, dp=0.0075` 的 protected solver canary；该 canary 仍为零 credit；
5. 只有 protected evidence 充分时，root 才能决定是否物化冻结的 15-row 计划；完整 hard/event 结果和 Core evaluation 仍是任何 T1 claim 的前置条件。

本阶段所有执行边界均为只读：没有调用 GenCase、native decoder、solver、GPU 或 queue；没有写 ledger、registry 或 matrix；没有启动作业。授权主机字段保留为当前已授权的 `Luna Max`，但本阶段未使用运行时入口。

## 交付物与校验

| 产物 | SHA-256 | 字节数 |
|---|---|---:|
| `campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-proposal-v1.json` | `e2f69380cdecf5952ec8d7d2d69aec43481d421b245e212395df42aa47ed28c9` | 22805 |
| `scripts/f2_static_receiver_ballistic_catch_proposal_v1.py` | `3cd20870daa5a01ffa2a37e99985b538ab93747f70ac291d7206bbe2d3e919f6` | 5990 |
| `tests/test_f2_static_receiver_ballistic_catch_proposal_v1.py` | `a63f6346344a57c3e7d8f48001584c44f01cb2a101acca5c849d69639749f456` | 4816 |

只运行了以下两项本地只读校验：

```text
.venv/bin/python scripts/f2_static_receiver_ballistic_catch_proposal_v1.py
status=ok, binding_count=17, planned_denominator=15,
runtime_calls={gencase:false, native_decode:false, solver:false, gpu:false, queue:0}

.venv/bin/pytest -q tests/test_f2_static_receiver_ballistic_catch_proposal_v1.py
5 passed in 3.30s
```

本报告自身的 SHA-256 随 root 回传清单给出；其余三项产物的实现绑定和 SHA 已在上表及 proposal validator 中固定。主报告没有修改。
