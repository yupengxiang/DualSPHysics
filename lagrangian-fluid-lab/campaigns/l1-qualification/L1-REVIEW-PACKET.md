# L1 Reviewer Handoff Packet

给云端 reviewer 的交接摘要（2026-09-09）。交付分支：`codex/lagrangian-fluid-exploration`。本 packet 是 reviewer 输入，不是新的 owner 授权。

## 一句话结论

W1 time gate 选定 CFL=0.05，但 W1 space 的三个高度都没有形成 T1；按 reviewer 规划做的一个 W2-A（h11 fine、mDBC、显式五面法向）solver 虽然返回 0，仍有 49,769/60,060 native `position` exclusions 和 1371 帧闭壁越界。因此当前 `T1=false`、`development=false`、`training=0`、`F6 new solver=0`、`formal_release=false`。

## 已执行范围

1. W0：锁定历史/N4 不变、输入 lineage、身份与 open-top 语义。
2. W1 time：h10/h11，CFL 0.1 vs 0.05，完整保存轴和 21 个登记时刻；两例通过。
3. W1 space：h09/h10/h11 × coarse/medium/fine，CFL=0.05；fine 的边界/身份门失败，未跑 `.007`。
4. W2-A：固定 h11 fine 物理和数值设置，只切换 `Boundary=2` 并添加 `GeometryForNormals`；结果为负。

附件计划只作为用户采纳的一次性范围模板；不代表结果、签名或 reviewer 回写。附件哈希和语义边界见 `OWNER-ADOPTION.md`。

## Reviewer 应优先核查

- W2 XML 中 `GeometryForNormals` 的五面实际几何、`[CaseName]_hdp_Actual.vtk`、`distanceh=2.0` 和 `svshapes=true` 是否符合 solver 期望；生成文件确实为 5 polygons。
- `Run.out` 的 `Boundary="mDBC"`、`RunPARTs.csv` 的 `position:49769` 与 full audit 的身份分类是否一致；当前一致。
- open top 被声明为非吸收面；没有 absorber 时，缺失身份不应被自动当作合法出口。
- 是否授权 W2 额度内剩余的一个单一受控假设（例如官方 mDBC/template 法向构造）；在此之前不扩展、不做训练。

## 关键数值

| 项目 | 数值 |
|---|---:|
| W1 time h10/h11 max TV | 0.0018382353 / 0.0040485830 |
| W1 space medium→fine TV h09/h10/h11 | 0.0556495 / 0.0611363 / 0.0686456 |
| W2-A initial/final valid particles | 60060 / 10291 |
| W2-A native position exclusions | 49769 |
| W2-A first penetration | frame 130, t=0.130014 s |
| W2-A penetration frames / max outside mass | 1371 / 18.3140009 kg |

## 审阅文件

- 结论：`L1-FINAL-REPORT.zh-CN.md`、`L1-RESULTS.json`
- W1 原始机器报告：`l1-f1-qualification.json`
- W2 原始机器报告：`l1-w2-boundary-control.json`
- W2 全量审计：`audits/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005.json`
- W2 输入/法向：`cases/L1_W2_A_BOUNDARY_MDBC_h11_fine_dp0p01_cfl005/` 与 `artifacts/W2-A-boundary-mdbc/`
- 错误覆盖：`ERROR-AND-COVERAGE-MAP.zh-CN.md`
- 资源：`RESOURCE-LEDGER.json`
- 哈希/大文件说明：`DATA-MANIFEST.json`
- 复现：`REPRODUCTION.md`

原始运行目录和归一化 HDF5 仍在运行节点，按 `.gitignore` 不进入 Git；manifest 保留相对路径、大小和 SHA-256。
