# F1/F2 第三 T1 路线关闭收据（2026-09-21）

本轮在 Luna Max 审计环境中只读核验 F1/F2 的 Definition 谱系、硬失败、事件删失和固定分母。结论是：当前没有能够通过审计的新物理 Definition 假设，F1/F2 第三 T1 搜索关闭。`new_physical_definition_found=false`、`qualification_credit=0`、`registry/ledger/T1/T2 mutation=0`。这份关闭决定不授权 Definition、GenCase、native decode、solver、GPU 或 queue。

## 路线结论

| 路线 | 当前证据 | 决定 |
|---|---|---|
| F1 H1/H2/H3/H4 | H1/H2 repair lineage 已停止；F1 qualification `qualified=false`、`T1_numerical=false` | 关闭；禁止同类输入重试 |
| F1 suspended-obstacle gap G1 | 完整事件窗到达，但 hard integrity=false；84 个 closed-wall endpoint frame、615 个 obstacle-penetration frame、1700 个 saved-chord crossing；credit=0 | 关闭；静态 CPU/native pass 不能覆盖运行时硬失败 |
| F2 dynamic DBC duration | hard integrity=true，但 5 s event window 未完成，settled 未发生；anchor 在固定 15 行 numerator 外，credit=0 | 关闭该 duration scope；要求未来全新物理假设 |
| F2 receiver/overflow-weir | 15 行中 `executed=1, failed=1, event_censored=1, unattempted=14`；hard=false、event=false；credit=0 | 关闭；保留失败分母 |
| F2 receiver/ballistic v1/v2 | v1 运行硬失败，排除 64 个粒子；release-speed v2 CPU/native 发现 3840 个外壁端点越界，preflight=false | 关闭；禁止重命名或同输入重试 |
| F2 distributed-slot v1/v2 | zero BoundNor/NormalSize 从 124608 降至 76095，仍未通过零值硬门；normal hypotheses exhausted | 关闭；不进入 v3 |
| F2 submerged-orifice normal-remediation v2/v3/v4 | zero BoundNor 分别为 64899、83443、29484；三次 `preflight_pass=false`，v4 partition 明确 `no_route_authorization=true` | 关闭；不再重复 v2/v3/v4 |
| F2 H2 static-hold | 8/8 scientific checks 失败；static-hold route closed，credit=0 | 关闭；不把静态输入门当作动态资格 |

因此，receiver/ballistic、submerged-orifice normal-remediation v2/v3/v4、F1 H1-H4 及其 G1 延伸、DBC duration、weir、distributed-slot 和 H2 static-hold 都不能提供一个尚未关闭的物理 Definition。仅有 root-review-only 的 proposal 不足以构成新路线；缺少 literal Definition、独立 hash closure 或静态/运行时硬门通过的 proposal 也不会被擅自物化。

## root-review-only 决定

候选卡 [f1-f2-third-t1-route-closed-v2.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json) 的状态为 `route_closed_no_new_hypothesis`；路线收据 [f1-f2-third-t1-route-decision-receipt-v2.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v2.json) 保留以下边界：

- 当前 Core family 仍为 `F3/F4`，`three_t1_families=false`；所有已有失败仍在原分母中。
- 本轮不写 Definition，不运行 CPU/Native preflight；即使未来有新 preflight，也只能在新的 root review 授权后执行一次且为 zero credit。
- 不修改阈值，不删粒子，不延长事件窗，不做 survivor renormalization，不生成新的 queue/job/registry/ledger/T1/T2 记录。
- 只有一个与上述所有关闭 lineage 独立、可证伪且绑定新 scope/case/output namespace 的物理 Definition，经过新的 root review，才允许重新打开搜索。

## 回归与 hash

只运行了候选收据脚本的 `--check` 和定向回归测试；没有读取 trajectory/HDF5 大场，也没有启动 solver/GPU/queue。

```text
.venv/bin/pytest -q tests/test_f1_f2_third_t1_route_closed_v2.py
4 passed in 0.10s
```

交付物 SHA-256：

- `campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json`: `ba789b300d7e977e8c845c2215721fc081637d5c0a382d4d9f6d640c8db58b67`
- `campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v2.json`: `6f8e84a0d31d27db4f3ba38907a8a8e8020be41adc5c8a159b3ab6d1a4b1b8cf`
- `scripts/f1_f2_third_t1_route_closed_v2.py`: `4254787df11d90a5daff6816980db862127717602760b76cab60be5150355954`
- `tests/test_f1_f2_third_t1_route_closed_v2.py`: `1bf94726dc4e3961eb211187405549c788152a28bfc91a9993f7c6682c1cfb4a`

报告本身只记录决定和已存在证据的 hash-bound 路径；它不构成资格、运行授权或分母变更。
