# R3 G2 boundary/open-face semantic audit

状态：**结构语义通过；wall-visibility 仍为 candidate-only。**

机器可读结果：`r3-g2-boundary-semantics.json`。审计脚本：
`scripts/r3_g2_boundary_semantics.py`。

## 这次审计核对了什么

审计同时读取每个 W11 F1/F2/F3 案例的：

1. GenCase `*_Def.xml` 中的 `setmkbound`、`setmkvoid` 和 `boxfill`；
2. 生成 XML `<particles>` 中 `mkbound -> Mk` 以及 `fixed/moving` 的映射；
3. `MkCells.vtk` 中 boundary `Type`/`Mk` 和有限 polygon；
4. release manifest 链接的 sidecar，在 frame 0 与 VTK 几何（按 sidecar 的 fixed-first/moving-second 顺序）及 frame 轴之间的对应关系。

对每个逻辑 box face，脚本还计算生成 VTK polygon 在该面的投影 union coverage。coverage `>= 0.5` 只作为诊断上的“完整生成面”阈值；它不是物理容差或 CFD 收敛判据。

## 结果

| 项目 | 数量/结论 |
|---|---:|
| F1/F2/F3 sidecar | 12 |
| `mkbound -> VTK Mk/Type`、sidecar label、frame 0 geometry 一致 | 12/12 |
| fixed-only 案例 | 7 |
| prescribed moving 案例 | 5（均为 W06；moving `mkbound=0 -> Mk=17 -> Type=1`） |
| sidecar triangles | W06 为 40 fixed + 28 moving；F1/F3 全为 Type 0 |
| 明确声明的 wall face 均被生成几何覆盖 | 12/12 |
| wall-visibility 语义暂通过 | 9/12 |
| 含未声明的完整/近完整 cap、需要显式策略 | 3/12 |

### F1 与 F3

- 普通容器 `mkbound=0` 都声明 `bottom | left | right | front | back`，因此 **top 是逻辑开口**。VTK 仍带有沿顶边的窄 rim/edge cap；审计覆盖约为 `0.13`，不是完整 top 面，不能简单把这些 polygon 报成封闭顶盖。
- `F1_center_obstacle`、`F1_twin_obstacle` 的 obstacle box 在 XML 中先由 `setmkvoid` 定义，随后声明 `top | left | right | front | back`，因此 **bottom 没有被逻辑声明**。但生成 shell 在 bottom 处仍出现 coverage `0.73`、`0.84` 的 cap。它可能是 obstacle 坐落于 tank floor 上的隐式支撑闭合，也可能在独立悬空使用时改变可见性；当前不能自动接受。
- `F3_baffled_slosh` 的 baffle 同样由 `setmkvoid` 加 `top | left | right | front | back` 定义，但 bottom cap coverage 为 `1.0`。它很可能依赖底板形成支撑闭合，仍需要组件级 policy 才能作为 wall-aware material target。
- `F1_opposing_columns`、`F3_impulse_slosh`、`F3_transverse_slosh` 没有额外 obstacle/baffle，均为底板和四侧壁、开放顶部。

### F2 W06 rotating cup

- 所有五个 sidecar 的 `mkbound=0` 是 moving `Type=1/Mk=17`，generated XML 的 `refmotion=0` 与 sidecar frame-wise world transform 对应；`mkbound=1 -> Mk=18` 是 fixed receiver，`mkbound=2 -> Mk=19` 是 fixed floor。
- cup 与 receiver 都只声明 bottom 和四侧面，**top 是逻辑开口**；floor 只声明 bottom，其余方向均为开放/边缘壳层。
- 目前没有 manifest 级 outlet、destination region 或“穿过开口后如何计入目的地”的定义。sidecar 可驱动有限面 visibility，但不能单独产生材料去向标签。

## 对 wall-aware tracer 的含义

sidecar 已经解决了“把一面有限墙当成无限平面”的几何错误，也保留了 fixed/moving 与每帧世界坐标；它足以做候选数值探针。可是 sidecar 目前只有 triangle、Mk、Type，没有每个 logical face 的 `closed/open/rim/supporting` 语义。由于 GenCase boundary-particle shell 会在未声明面附近生成 rim 或 cap，wall-aware consumer 若只把全部三角形视为同一种 wall，就无法区分：

- 开口顶部的窄边缘 cap；
- obstacle/baffle 底部的隐式支撑 cap；
- 真正声明的封闭面。

因此报告中的 9/12 不是“9 个物理正确、3 个错误”，而是 9 个没有检测到未解释完整 cap 的候选几何；3 个需要人工/规则确认。

## 下一步执行约束

1. 在发布 wall-aware material target 前，为每个 boundary component 增加显式 `open_faces`、`rim_policy` 和 `supporting_component` 字段，或把同等信息链接到 release manifest；
2. 对 F1 obstacle、F3 baffle 明确写出“bottom cap 是否由 floor 支撑、是否允许独立使用”；若不允许，必须在 sidecar/visibility 中遮蔽该隐式 cap；
3. 对 F2 明确 cup/receiver 的 top opening 和 destination/outlet region，再重跑 tracer convergence；
4. 任何分辨率、boxfill、layers 或运动定义变化，都要重新运行该审计，不能复用旧 sidecar。

