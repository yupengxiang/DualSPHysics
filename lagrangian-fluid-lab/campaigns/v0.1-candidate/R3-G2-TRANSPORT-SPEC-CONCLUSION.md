# R3 G2 结论：材料输运 destination specification 审计

状态：**candidate contract only；当前开发 release 没有任何链接的 destination specification，因此 T2 material transport 仍为 0 个可执行案例。**

## 已验证

- `transport-regions.schema.json` 现在要求显式生命周期、坐标系和至少一个 destination，并按 `aabb`、`halfspace`、`sphere` 约束几何参数。
- 运行时 validator 拒绝缺少 half-space side、零法向量、反向 AABB、非正 sphere 半径、重复名称和非显式 lifecycle/frame。
- 两个协议示例通过运行时契约检查（2/2）。

## 当前 release 覆盖

| 项目 | 数量 |
|---|---:|
| release cases | 13 |
| linked destination specs | 0 |
| valid linked specs | 0 |
| existing boundary sidecars | 12 |
| `wall_visibility=true` | 0 |
| complete T2 contract | 0 |

边界 sidecar 只说明有限三角面和候选可见性，不能替代 destination 语义。当前报告因此保留 `formal_ready=false`，没有把现有 `captured/retained/spilled` 代理分类升级成正式任务标签。

机器可读明细见 `r3-g2-transport-spec-audit.json`；协议 schema 见 `protocol/transport-regions.schema.json`。
