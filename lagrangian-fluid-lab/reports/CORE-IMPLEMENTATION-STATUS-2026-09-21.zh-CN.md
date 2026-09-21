# Core 全流程实施状态（2026-09-21）

本记录是当前实现状态的集成快照；科学状态仍以
`campaigns/core-v1/completion.json` 和不可变 attempt 回执为准。

## 已落地

- 公共数据、状态更新、谱系、分割、材料和评测接口已经有版本化实现及
  regression tests。模型接口把位移和原生保存速度增量分开，参考 oracle
  复用同一 adapter、更新器和 evaluator。
- 单写者 runtime coordinator、GPU/CPU 资源预留、幂等回执、恢复和跨机
  reader reproduction 已接入；H200 与 Ada 的并发准入仍由实测显存、RAM、
  I/O 和外部占用决定。当前长期归档进程保持运行，不能覆盖或重复启动其
  attempt。
- F3 和 F4 各有一个通过 T1 数值资格的 scope；材料接口的 F4 membership
  resume/acceptance 完整性漏洞已修复，但 F3/F4 都尚未通过宏观 T2。
- F2 分布式 submerged-slot 新机制完成了一次全新 Definition/native CPU
  preflight 和一次允许的 normal-layer repair。两次均为固定零法向门的硬负例，
  route 已关闭，credit 为零，禁止 v3 和同输入重跑。
- 旧 F6 浮箱、入水和双浮体探针经只读审计确认是与 F1--F5 不同的自由刚体
  流固反馈机制，但只达到 structural probe。新的 F6 proposal 保持
  root-review-only，未进入 registry、ledger、matrix 或 T1 分母。
- F6 的新 zero-force/units/inertia static anchor 已通过 CPU static gate：
  新 Definition、body mass/inertia、body identity、sidecar 字段、边界间距和
  151-frame 事件窗合同均通过；这是接口准入证据，不是流体物理或 T1 资格，
  因为 `gravity=(0,0,0)` 且没有 runtime sidecar。
- F6 的 gravity/entry physical-anchor 路线保留了 v1 body mass/COM/inertia
  硬负例、v2 的 `rhopbody+massbody` GenCase schema 负例，以及 v3--v8 的流体
  离散质量／endpoint 诊断。全新的 v9 Definition 显式绑定 `massbody`、`center`
  和 `inertia`，并把 GenCase endpoint-safe drawbox（连续体积尺寸减一个 `dp`）
  与连续体积质量门写入 `fluid.sampling_contract`。v9 root review 通过后，
  一次 CPU/GenCase/native preflight 生成 fixed `11806`、floating `693`、fluid
  `15048`；流体质量相对误差 `4.44e-16`，body mass/COM/inertia 均通过硬门。
  该结果只使 v9 具备下一次独立 root 授权评审的条件，仍是
  `qualification_claim=none`、`T1=false`、credit 为零；没有启动 solver/GPU/queue，
  也未写 registry/ledger/matrix。
- 在独立 root 授权后，v9 protected CPU solver canary 已按 exact-one 合同执行一次。
  求解器返回 0，产生完整 301 帧；原生粒子身份、有限值、fixed/floating/fluid
  数量、接触时间、闭合面接触／穿透和开顶质量流均通过。但 DualSPHysics 的
  实际 `TimePart` 帧时间围绕 `0.005 s` 有自适应步进偏差（相邻帧约
  `0.0048089--0.0051873 s`），严格 cadence 门和按闭区间计数的
  `[1.0,1.5] s` 101 帧门未通过（实际区间内 100 帧，末帧为 `1.500144 s`）。
  因此该 canary 保留为 `solver_completed_hard_failure`，详见
  `reports/F6-PHYSICAL-ANCHOR-SOLVER-CANARY-V9-2026-09-21.zh-CN.md`；不重试、
  不恢复、不登记 F6 T1，科学 credit 仍为零。
  其中 sidecar 的 `settle_hold` 只是时间段标签；v9 没有证明物理平衡，后续
  revision 必须区分 observation hold 与预登记的 equilibrium threshold。
- v10 observation-axis 已完成全新 Definition/XML/BI4 的一次 CPU GenCase/native
  preflight。11,806 fixed、693 floating、15,048 fluid 粒子，连续体质量相对误差
  `4.44e-16`，刚体质量／COM／惯量门通过；实际时间轴和 `[1.0,1.5] s`
  observation hold 尚未有 solver 输出。该 receipt 仍是 `T1=false`、credit 为零，
  没有启动 solver/GPU/queue，也没有写 registry/ledger/matrix。
- 随后 v10 只执行了一次 CPU solver canary。301 帧的实际 `TimeStep` 轴最大间隔
  `0.0051873 s`、末帧 `1.50014446 s`，接触时间、闭合面接触／穿透、开顶质量流和
  body sidecar 全部通过；`[1.0,1.5] s` 只登记为 observation hold，明确没有
  equilibrium claim。该 canary 状态为 `solver_completed_sidecar_pass_pending_scientific_review`，
  仍然不计入 T1 或生产分母。
- v10 observation-axis 的 13+2 候选资格矩阵经历了三轮输入相位修正。v1--v3 的
  失败 preflight 证据保留：先后发现 `dp=0.015/0.025` 的粒子越过连续盒边界，
  以及修正后 `dp=0.025` 的连续质量闭合失败；没有放宽硬门或覆盖失败分母。最终
  v4 以新 scope `F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3` 和
  revision `F6_observation_axis_13plus2_v4` 冻结连续盒 `[0.175,0.050,0.040]--
  [1.315,0.515,0.280] m`。
- v4 的 3 个空间锚点、2 个独立内点、三档分辨率、内部时间推进和原生输出 cadence
  对照共 15 个单元，均完成 fresh Definition/XML/BI4 的 exact-one CPU/native
  preflight；聚合审计通过。每格仍是 `qualification_only`、`T1=false`、credit 为零，
  尚未启动 solver，不能由初态 preflight 推导 F6 T1。
- v4 已为 8 个代表格生成独立 CPU solver canary root review/job：选择了三个空间锚点、
  中心细档、两个独立内点和内部时间／原生 cadence 对照。8 格已全部完成并审计：
  7 格通过全部硬门；cell-08（`q=1`、细档）产生 301 帧但末端少 1 个流体粒子，
  `excluded_particles_zero`、`native_identity_fixed`、`fluid_group_count_fixed` 失败，
  保留为科学硬失败。cell-04 首次 worker 的回执字段缺失被记录为基础设施失败，并从
  同一已完成输出只读恢复，未再次启动 solver；cell-14 的原生 cadence 对照为 601 帧。
  aggregate audit 为 `all_selected_canaries_audited`、`scientific_pass_count=7/8`，
  所有结果仍是 qualification-only，没有写入 Core 分母或 T1 credit。
- v4 回执审计又发现 7 个正常 worker 的 `native-frame-audit` hash 因写入顺序暂时为
  `null`。worker 已修正；对既有完成 attempt 只做一次 metadata-only repair，保留
  原回执 SHA-256，并将新 hash 与 `solver_reinvoked=false` 写入 repair manifest。
  最终 `receipt_binding_failure_counts={}`，不改变任何科学字段、hard gate 或资格分母。
- 材料修复后的实现哈希已重新绑定到只读预检证据；同时把评测和 rollout 的
  frame denominator 收紧为真实整数语义，拒绝 fractional/bool 计数。新鲜 v5
  源闭包、root-admission 回执和 full-field halo oracle 已重新生成并通过哈希
  验证；此前完整 Core 回归为 `444 passed`，本次 F6/F4 定向回归另有 `16 passed`，
  不改变任何 T2 分母或资格状态。
- F4 tallwall120 的只读 T2 admission/acceptance gap audit 已登记为独立证据：6/6
  保留案例未知质量门失败（最大 `1.0 > 0.01`），6/6 事件窗 right-censored，
  没有 F4 CDF 容差、residence/event acceptance 或正式逐例 acceptance receipt；
  33 行材料矩阵中仍有 24 个 resolution/substep 和 5 个 seed-density overlay
  待执行。该审计没有修改 T2 分母，也没有授权 ESS32 或启动材料作业。

## 当前门状态

最近的 `core_campaign.py status` 为：

| 门 | 当前 |
|---|---:|
| T1 家族 | F3、F4（需要 3） |
| 宏观 T2 家族 | 0（需要 2） |
| 正式训练 | 0/9 |
| 缺失 T1 case-run | 288/432 |
| 缺失材料 case-run | 288/288 |
| 独立 reproduction | 通过 |
| 因果／谱系契约 | 通过 |

因此 `can_finalize=false` 是预期结果。失败的 solver、材料或模型运行可以
作为负结果进入分母，但未注册、未执行和缺少参考证据不能被算作完成。

## 下一步准入顺序

1. F6 v9 canary 的 solver 产物已经完整保留，但严格 cadence 合同未通过。v10
   v4 已完成 15 格 fresh native preflight，8 格 solver canary 已完整审计（7/8 通过，
   cell-08 保留科学硬失败）。新的 root review 必须先决定该 scope 是否关闭并转向 F2
   或其它替补家族；不得授权剩余 7 格、对 cell-08 同输入重跑，或把 v9/v1--v3 失败证据
   改判为通过。
2. F2 第三家族候选和 F3 宏观 T2 资格正在做独立只读审计；在第三个 T1 家族
   通过并完成32例注册前，formal planner 不得生成9个训练作业。F4 的 T2 工作须先
   解决未知质量、完整事件窗、F4 专用容差和 acceptance 接口，再执行剩余矩阵。
3. 任一家族取得 T1 后，按固定 8→32 生产规则注册案例；材料侧在已取得 T1 的
   两个家族分别完成完整宏观矩阵，不能用旧 diagnostic trace 代替 T2。
4. 每个阶段都继续使用 `verify → inspect → train → rollout → evaluate →
   reproduce` 入口和固定失败分母；正式 Core 完成判据保持不变。

代理配置记录在 `campaigns/core-v1/agent-policy.json`：subagent 使用
`gpt-5.6-luna` / Max，主 agent 请求 `gpt-6-astra` / Low。该配置只约束
执行角色，不把任何代理名称或一次运行自动解释为科学资格。
