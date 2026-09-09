# L1 错误与覆盖范围图

本表把“运行完成”“证据可读”“验收通过”分开。`pass` 只表示对应的局部门，不表示 T1 自动通过。

| 门 / 分支 | 覆盖内容 | 结果 | 证据 | 未覆盖或阻塞 |
|---|---|---|---|---|
| W0 | 历史证据、输入 lineage、身份语义、资源和 GPU 策略 | pass | `L1-SCOPE-LOCK.json`、`OWNER-ADOPTION.md`、`L1-W00-INVENTORY.json` | 不修改 N4 历史 |
| W1 time | CFL 0.1 vs 0.05；h10/h11；21 时刻；完整保存轴 | pass | `audits/L1_W1_TIME_*.json` | 不等价于连续物理真值 |
| W1 space coarse/medium | 三高度、两分辨率、质量/分布/COM/front 比较 | 局部门 pass | `audits/L1_W1_SPACE_*coarse*`、`*medium*` | 不能单独构成 T1 |
| W1 space fine h09 | 完整轨迹、闭壁穿透、身份生命周期 | fail | `audits/L1_W1_SPACE_h09_fine_dp0p01_cfl005.json` | 1013 帧闭壁越界 |
| W1 space fine h10 | 完整轨迹、闭壁穿透、身份生命周期 | fail | `audits/L1_W1_SPACE_h10_fine_dp0p01_cfl005.json` | 871 帧闭壁越界 |
| W1 space fine h11 | 完整轨迹、闭壁穿透、身份/排除原因 | fail/unknown | `audits/L1_W1_SPACE_h11_fine_dp0p01_cfl005.json` | 352 native position exclusions；open top 无 absorber |
| W1 `.007` fallback | 预登记二阶梯 | 未执行 | `l1-f1-qualification.json` 的 `space_decision` | 无改善候选高度，条件门未满足 |
| W2-A mDBC | h11 fine 单点边界表示控制；显式五面法向；全时域 | fail/unknown | `l1-w2-boundary-control.json`、W2 full audit | 49,769 native position exclusions；不能扩展 |
| T1 | 至少一个高度的稳定参考 recipe、无穿透、身份/质量闭合、细化一致性 | blocked | `L1-RESULTS.json` | 没有合格高度 |
| T2 | 外部观测/实验对照 | not run | `L1-FINAL-REPORT.zh-CN.md` | 不从负 T1 推断 T2 |
| W4 | 参数内部点、批次 lineage | not applicable | `L1-RESULTS.json` | 需要 T1 |
| W5 | development tranche | blocked | `L1-RESULTS.json` | 需要 T1；attempt=0 |
| W6 | training dataset/model | blocked | `L1-RESULTS.json` | 需要 T1；training attempt=0 |
| F6/release | 本活动新 solver、正式发布、hidden test | 0 / false / false | `L1-RESULTS.json` | 按范围锁定 |

## 错误分类

- `finite_wall_or_obstacle_penetration`：保存轨迹中粒子越过声明的闭壁；不是转换工具可以忽略的异常。
- `initial_identities_missing_at_final_*`：h11 fine 的缺失身份与 native `position` 排除证据相符，但 open top 没有注册吸收面，所以不将其重新解释成合法出口。
- `resource_guard_failure`：外部作业回收显存时只终止 L1 solver；W1 两次 guard failure 已计数，未删除。
- `audit_failed_or_unknown`：求解器可以 return 0，但完整物理/身份门仍可失败；W2-A 正是此类。

## 覆盖边界

本轮覆盖了 F1 plain dam-break、h09/h10/h11、CFL 时间策略和首个空间阶梯，并对 reviewer 指定的 boundary/normal 方向做了一次可证伪控制。没有覆盖其他几何、材料、3D 外部实验、模型训练或正式 release；这些未执行项不能从本报告推断。
