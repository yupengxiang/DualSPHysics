# R3 G2 boundary component policy contract

状态：**契约审计通过；wall-aware 物理接纳仍为 0/12。**

机器可读文件：

- `release/v0.1-development/boundary-component-policy.json`：逐案例、逐 `mkbound` 的候选策略；
- `r3-g2-boundary-policy-audit.json`：策略与 release manifest、`r3-g2-boundary-semantics.json` 的一致性审计；
- `protocol/boundary-component-policy.schema.json`：最小结构约束；
- `scripts/r3_g2_boundary_policy.py`：可重复审计入口。

审计入口会逐层拒绝 policy 对象中未在 schema 声明的字段（等价于各对象分支
`additionalProperties=false`），因此报告通过不仅表示案例内容一致，也表示当前
候选 policy 的字段拓扑没有静默扩展。语义报告中的 `F3_baffled_slosh` 隐式
bottom cap 现在明确标记为 `baffle`，不再误标为 `solid_obstacle`；这只修正
语义标签，不改变 candidate-only 或 wall-aware 接纳结论。

## 契约字段

每个 boundary component 必须显式记录：

| 字段 | 约束 |
|---|---|
| `component_id` / `mkbound` | 使用稳定的 `mkbound:<整数>` 标识，并与生成 XML 映射一致 |
| `role` | `container`、`solid_obstacle`、`baffle`、`moving_cup`、`receiver` 或 `floor` |
| `open_faces` | 必须逐字对应 `boxfill` 中省略的逻辑面；省略面不是封闭壁面 |
| `rim_policy` | 普通开放面使用 `exclude_open_face_rim`；隐式完整 cap 使用 `review_required_implicit_cap` |
| `supporting_component` | 无支撑关系时为 `null`；候选支撑关系必须给出 component、关系和状态 |
| `review_status` | 普通组件也保持 `candidate_unresolved`；隐式 cap 为 `pending_human_or_rule_confirmation` |

`supporting_component.status=unconfirmed` 是刻意的安全闸门。它记录“障碍物/挡板底部 cap 可能由容器底板支撑”的假设，但不把几何重合当作物理事实。

## 审计结果

| 项目 | 结果 |
|---|---:|
| manifest、语义审计、policy 的案例集合一致 | 12/12 |
| policy contract 通过 | 12/12 |
| 语义审计中的 wall-visibility pass（原值） | 9/12 |
| 标记为需人工/规则确认的案例 | 3 |
| 正式 wall-aware 物理接纳 | 0/12 |

需确认的三个案例为：

- `F1_center_obstacle`：`mkbound:1` 的未声明 bottom cap，投影覆盖约 0.733；
- `F1_twin_obstacle`：`mkbound:1`、`mkbound:2` 的未声明 bottom cap，投影覆盖约 0.840；
- `F3_baffled_slosh`：`mkbound:1` 的未声明 bottom cap，投影覆盖 1.000。

三者当前均使用：

```json
{
  "rim_policy": "review_required_implicit_cap",
  "supporting_component": {
    "component_id": "mkbound:0",
    "relationship": "floor_support_candidate",
    "status": "unconfirmed"
  },
  "review_status": "pending_human_or_rule_confirmation"
}
```

其余 9 个案例只记录“未检测到完整未声明 cap”的候选规则，组件仍是 `candidate_unresolved`；这不是“9 个物理正确案例”。同样，当前 policy 不提供 fluid-wall 接触、泄漏、出口/目的地或实验验证，因此不能把任何案例直接用于正式 material target。

## 下一步解除条件

1. 明确 `F1` obstacle 与 `F3` baffle 是否确实坐落并受支撑于 `mkbound:0` 底板；若是，给出可重复的几何/规则判据并更新 policy 版本；若否，从 wall visibility 中遮蔽对应 cap。
2. 为 `F2` cup/receiver 定义 opening 与 destination/outlet region；`open_faces` 只解决边界组件语义，不产生材料去向标签。
3. 任何 boxfill、layers、分辨率、运动定义或 sidecar 变化，都必须重新运行几何语义和本 policy 审计。
4. 在上述条件完成前，保留 `acceptance_status=candidate_policy_contract_only` 与 `formal_wall_visibility_admission_count=0`。
