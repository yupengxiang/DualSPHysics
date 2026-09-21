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
- 材料修复后的实现哈希已重新绑定到只读预检证据；完整 Core 回归为
  `442 passed`，不改变任何 T2 分母或资格状态。

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

1. 由 root 单独审查 hash-bound v9 Definition 和 CPU/native receipt，若批准，
   只执行一次 protected solver canary；canary 必须保留 body-state/force/torque
   sidecar、完整事件窗和闭合边界硬门，不能把这次 native pass 直接登记为 T1。
2. 若 v9 canary 通过，再按固定范围资格矩阵与 8→32 生产规则登记 F6；任何
   事件窗、body identity、边界穿透或 sidecar 失败都保留 zero credit，禁止同一
   科学输入重跑。
3. F6 取得 T1 后，按固定 8→32 生产规则注册案例，再开启正式 9 个模型/种子
   训练。材料侧先在已取得 T1 的两个家族分别完成完整宏观矩阵，不能用旧
   diagnostic trace 代替 T2。
4. 每个阶段都继续使用 `verify → inspect → train → rollout → evaluate →
   reproduce` 入口和固定失败分母；正式 Core 完成判据保持不变。

代理配置记录在 `campaigns/core-v1/agent-policy.json`：subagent 使用
`gpt-5.6-luna` / Max，主 agent 请求 `gpt-6-astra` / Low。该配置只约束
执行角色，不把任何代理名称或一次运行自动解释为科学资格。
