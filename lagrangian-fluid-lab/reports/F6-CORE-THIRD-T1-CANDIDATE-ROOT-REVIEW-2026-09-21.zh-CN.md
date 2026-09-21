# F6 第三 T1 家族候选 root review（只读）

审查身份：`F6_fluid_rigid_body_root_review_only_20260921`。本审查只读取
`reports/runtime`、三份 F6 Definition、三份归一化 HDF5、运行日志和已有
F6 blocker contract；没有启动 solver、GPU、queue，也没有写入 registry、
ledger 或 matrix。

## 结论

F6 在机制上可以作为 Core 第三 T1 家族候选：它把自由刚体的位姿、速度、
质量/惯量和接触状态作为动态状态，并让流体力反馈到刚体。F1 是固定障碍物
拓扑，F2 是规定的杯体/接收器运动，F3 是规定的晃荡激励，F4 是流体流束
碰撞，F5 是规定波浪、爬升和越顶；这些家族没有 F6 的独立自由刚体动力学
反馈。`F6_floating_box`、`F6_heavy_box_entry` 和 `F6_twin_floaters`
分别覆盖浮力升沉漂移、入水动量交换和多刚体流体介导耦合，但它们是同一
F6 家族的三个机制探针，不应拆成三个家族。

候选只适合进入新的 root-review-only proposal，当前证据不足以进入 T1。
机器可读 proposal 是
[`f6-fluid-rigid-body-root-review-only-proposal-v1-20260921.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f6-fluid-rigid-body-root-review-only-proposal-v1-20260921.json)。

## 旧资产的真实性和结构完整性

三份 Definition 都有对应的 GenCase 产物；`reports/runtime/run-summary.json`
记录历史 solver 返回码为 0，且三例日志均记录 `Excluded particles: 0`。
这证明旧探针确实生成并运行过，不能把它解释为物理验收。归一化 HDF5
的身份、时间和字段检查结果如下：

| 探针 | `dp` / 目标时长 | 帧数 / 终止时刻 | 粒子数 | ID 保留 | 密度范围 kg/m³ |
|---|---:|---:|---:|---:|---:|
| `F6_floating_box` | 0.04 / 0.8 s | 17 / 0.800281 s | 2121 | 1.0 | 998.74–1005.17 |
| `F6_heavy_box_entry` | 0.04 / 0.6 s | 13 / 0.600442 s | 1914 | 1.0 | 982.27–1066.30 |
| `F6_twin_floaters` | 0.04 / 0.8 s | 17 / 0.800301 s | 2196 | 1.0 | 998.61–1009.86 |

三份 HDF5 都是 `schema_version=2`，含有限的 position、velocity、density、
pressure、mass、type、mk、valid、particle ID、particle zone 和严格递增
的时间轴；保存间隔约 0.05 s。单体使用 `mk=22`，双体使用 `mk=22/23`，
数值粒子 ID 在首尾帧全部保留。runtime quality gate 的 `usable_probe` 只
覆盖这些宽松的结构检查，不能替代 F6 的 body-level 物理门禁。

## 阻塞项

**事件窗不完整。** 旧窗口分别只有 0.6 s 和 0.8 s，没有事件定义、力/力矩
时间序列或 settling/return 完成条件。入水体在 0.600442 s 仍有约
`+0.123 m/s` 的平均竖直速度；浮箱和双浮体也没有声明后冲击完整窗口。因此
“文件达到目标时刻”不能等价为“刚体事件已完成”。

**质量和惯量没有绑定。** HDF5 的 `mass` 是粒子字段，不是 body-level
质量/惯量合同。浮箱 body 粒子质量和为 11.2 kg，而 Definition 中
`rho_body * volume = 500 * (0.24*0.16*0.16) = 3.072 kg`；重箱分别为
9.6 kg 与 7.168 kg；双浮体两个 body 都为 9.6 kg，而按声明密度和体积应为
3.072 kg、4.096 kg。这个差异说明旧 HDF5 没有把刚体物理质量绑定进证据，
不等于历史求解器执行虚假。

**边界和接触没有闭合。** Definition 声明底、左、右、前、后 tank 面并保留
顶部开口，但归一化 HDF5 没有 boundary normals、wall penetration/contact
flags 或 open-face flux ledger。`Excluded particles=0` 只能说明没有粒子被
solver 排除。已有
`campaigns/l2-multifamily/resume-c6b28c8/f6r-blocker-audit.json` 进一步
指出 nominal floating mDBC 的 normal completeness、matched transformed-
Float1 force gauge 和 Chrono/contact semantics 均未闭合；radius-offset
zero-normal 诊断和 fixed-box DBC/mDBC 控制不能代替 F6 目标证据。

**材料身份语义有限。** 数值 particle ID 保留是好的结构证据，但 HDF5 自己
声明 `trajectory_semantics` 为 numerical SPH identity/material fidelity
pending audit；没有独立 body ID、body pose/inertia provenance 或 fluid-to-body
force mapping。因此它只能作为历史 structural probe。

## 最小静态/CPU gate

后续任何 runtime 授权前，root review 至少应在 CPU 上完成：

1. 对新的 Definition 绑定流体密度、body 密度、尺寸、质心、惯量、初速度、
   tank 面和全部输入 hash。
2. 从声明几何和 `rho_body` 计算 body volume/mass，并提供显式 inertia tensor
   及独立 body identity。
3. 对输出检查有限数组、严格递增时间、声明 cadence、完整目标窗口、稳定
   numerical IDs、mk/body mapping 和零 unexplained exclusion。
4. 要求 body-state sidecar 记录每个 body 的位置、线/角速度、力、力矩、
   contact/penetration 状态和 mass/inertia provenance。
5. 要求 boundary-normal 完整性以及 wall/open-face accounting；事件完成必须
   与 trajectory structural integrity 分开判定。

未来若获另行授权，最小 canary 应先是单刚体、无接触、静态/单位/惯量控制，
   单一明确分辨率和足够长的 static-balance/no-contact 窗口。这个 proposal
   本身没有授予该 canary。

## 明确禁止

- 不把三个旧 F6 HDF5、`O6_floating_box` 或 Test14 产物计入 Core T1 分母。
- 不复用旧 XML、BI4/OBI4、CSV、HDF5 或 trajectory 作为新 qualification 输入；
  只允许保存 hash 作为只读 provenance。
- 不把 radius-offset normals、fixed-box force gauge 或 solver return code 0
  当成 F6 物理通过。
- 不把动态 Chrono/contact 实验混入 fixed-body hydrostatic gate。
- 不启动 solver/GPU/queue，不修改 registry/ledger/matrix，不宣称 T1。

因此本次 disposition 是：**机制候选成立；root-review-only proposal 允许；
T1 admission 拒绝，等待 body mass/inertia、force/boundary 和完整事件窗合同。**
