# F3 row30 R003 无滑移约束首失效区间只读回放（2026-09-24）

## 范围与复现绑定

对 R003 的 40 个最终 `wall_occluded` seed，逐个从 trace 的首个 unknown 输出行回到该 source interval 的起始 tracer 位置，用原注册 backend 重放最多四个原始 RK 子步，确认其首个失败 stage；随后只对该失败子步起至**下一个 native 输出帧**的短区间，测试单最近闭壁零速约束 MLS 与 stage-safe RK4。没有重算 8.35 s 轨迹，没有改写 trace 或其他历史产物，也没有启动 worker、solver、GPU 或队列。

可复现脚本 [`f3_r003_noslip_constrained_first_failure_replay_v1.py`](../scripts/f3_r003_noslip_constrained_first_failure_replay_v1.py) 对 source、trace 和注册 backend 做 SHA-256 锁定：

| 输入 | SHA-256 |
|---|---|
| CFD source HDF5 | `fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4` |
| R003 trace HDF5 | `10e5219d6821d8963a82e068135f078a696a5a111fbd79f598408508c3799366` |
| 注册 `f3_native_volume_mls.py` | `e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9` |

复现命令：

```text
./.venv/bin/python -m scripts.f3_r003_noslip_constrained_first_failure_replay_v1
```

脚本默认仅输出汇总；`--include-records` 可打印逐 seed 明细。脚本读取历史 source frame，使用与原实现相同的有限墙可见性、Wendland 质量/密度权和 `2h` 支持，并在到最近**单个**闭壁面的投影点施加三分量零速 KKT 约束。约束只在闭壁距查询不超过 `2h` 时启用；顶部仍按开放面处理。候选 trial 的 RK 查询和终点均须处于登记闭域内，且受约束求解继续复用原 candidate support gate。此实现不是注册 backend。

## 结果

- 40 个 seed 分布于 35 个 native source frame；原始首失效 stage 与此前回放完全吻合：k2 `17` 个、k4 `23` 个。首失效面分布为 xmin `14`、xmax `10`、ymin `8`、ymax `8`。
- 在其余单帧区间上，40/40 的**支持门控 RK 数值积分**均在登记域内到达该输出帧；接受步数分布为 1 步 8 个、2 步 14 个、3 步 9 个、4 步 9 个。该反事实总计 396 次受约束近壁 stage 求值，没有额外拒绝步。受约束前的无约束 MLS 重算与注册 backend 的最大速度差仅 `5.56e-16 m/s`，用于核对复现没有更换原始基线。
- 这并非科学质量通过：396 次拟合中 **140 次**的 weighted reconstruction residual 超过原 F3 residual 对照上限 `0.0469813793 m/s`，涉及 **16/40** 个 seed；受约束 residual 最大 `0.22401854 m/s`。原始无约束拟合的 residual 最大为 `0.07387975 m/s`。因此即使支持门控的短区间积分能够完成，仍有明显的局部重建误差风险；本回放不将 residual 另行降格或忽略。
- 另有 **116/396** 个已接受的内部查询仍具有指向最近闭壁的正法向速度。硬约束保证的是投影墙点的零壁速，不是整个近壁层中法向速度处处非正；本次短剩余区间没有越界，不证明后续时域不会再次失败。

## 判断

结果比纯解析场测试更具体：对这些 R003 真实 source frame，单墙 no-slip 约束确实足以让这 40 条 seed 通过同一 native interval 的剩余积分部分，但**不能据此修复 row30**。短窗成功由支持门控给出；16/40 seed 的部分查询超过原 F3 residual 上限，116 个 stage 仍存在外向近壁速度，而且没有重算之后的 native intervals、未知率、CDF、驻留或事件量。因此 R003 仍为未接受、T2 credit 为 0，既有 43 个 unknown seed 和 1% 门槛均未改变。

若未来另立候选，下一道离线门应是在边界层／时间步细化和壁速一致性检查下追踪这些已受约束的 seed；所有 residual、支持、CDF 与驻留门必须原样保留，任何失败仍计 unknown。任何新的 row30 attempt 还需要新的 root decision 以及独立资源与 worker 授权。本次回放未授予或使用这些权限。

回看上一份 [R003 stage replay](F3-MATERIAL-ROW30-R003-STAGE-REPLAY-2026-09-24.zh-CN.md) 时，发现其中 `code_sha256` 有一位抄录笔误；该行已按 trace summary 与当前注册文件更正为上表 hash。没有改动 trace、source 或其收据。
