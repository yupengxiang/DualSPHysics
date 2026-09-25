# UPDATE-163：F8 R008 固定 15-case post-run 编排

时间：2026-09-26（Asia/Shanghai）

## 本轮实现

新增 `scripts/f8_r008_postrun_matrix_worker_v1.py`，将已审阅的单案例 post-run bridge 与 T1 metric matrix adapter v5 串接为固定 15-case 诊断流程。调用者不能直接提供一组可伪造的矩阵案例行：编排器按冻结行顺序处理每个 case，先调用单案例 bridge，再独立重新执行完整 B/C/D + metric v2 verifier，并只把该 verifier 的完整原始结果交给 matrix-v5。

编排器逐例核对 bridge 与新鲜 v2 结果中的 `case_metrics`、B/C/D receipt 与 manifest SHA、D-table bytes/SHA，再比对 matrix-v5 重算产生的 15 个 `metric_result_sha256` 及对应摘要绑定。RunPARTs/runtime/timestep 仍只作为 matrix-v5 规定的未认证诊断输入；所有最终资格/信任边界继续 false，资格信用恒为 0。

开始写轨迹前会检查精确的 15-case 输入键集、矩阵共享输入形状、每例独立的 current-user-owned output directory FD、15 个不同目录 inode，以及固定输出名不存在。每例发布后和矩阵返回前，使用 held dirfd、no-follow、single-link、bytes/SHA 校验轨迹，并要求最终路径仍指向同一 inode。若中途失败，已发布文件不会自动删除，也不会重试；调用者必须先检查固定输出名。该批次不是 15 例全局原子事务。

完整 v2 表链会在单案例 bridge 内前后复核，随后再取一次完整 v2 结果供矩阵使用；这会增加后处理 I/O，本轮没有用生产数据测量其成本。

本实现是静态 post-run 接线，不启动 solver、GenCase、native decoder、worker、GPU 或 queue；不写 receipt、registry、ledger 或分母，也不声称 HDF5 trajectory 获得独立来源认证。

## 独立审查与验证

- Terra High（`gpt-5.6-terra`, high）首轮代码审查为 `REVISE`，提出两个 P2（矩阵子边界需 exact false/zero；批处理中轨迹路径有复验间隙）及一个 P3 测试覆盖缺口。修正后 follow-up `PASS`，再将 P3 测试改为同内容新 inode 经 dirfd `os.replace` 覆盖早期产物；最终 follow-up `PASS`，无 P0–P3。review 无密码学模型身份 attestation。
- 新编排专项测试在最终测试情形下 **19 passed**，覆盖完整 15 行合成组合、缺行/目录 inode alias、每个 v5 嵌套边界的正向篡改、错误轨迹 SHA、同内容 inode 替换与保留已发布文件。
- 单案例 bridge + matrix-v5 + 新编排层联合回归 **52 passed**（最终单独专项重跑也验证了之后加强的 same-content inode 测试）。`py_compile` 与 `git diff --check` 通过。
- 仅用临时合成 fixture；未读取生产 bundle、HDF5 或 solver frame，未运行任何 native/solver/worker/GPU/queue workload。

## 总体计划状态

该提交补齐了“单案例 trajectory bridge 与冻结 15-case metric diagnostics 尚未统一编排”的静态工程缺口；它不是可信生产 worker、source/runtime attestation、native-integrity adjudicator 或正式 T1 决策器。R008 仍无 provenance-verified 生产 15-case 结果，readiness、T1 与资格信用不变。

Core 总账仍为 `can_finalize=false`：T1 家族 F3/F4 为 2/3，宏观 T2 为 0/2，正式训练为 0/9；固定 T1 case-run 缺 432（144 尚未登记），材料 case-run 缺 288，异机复现未通过。F8 execution/readiness 与 source/runtime identity、native integrity、完成与 timestep 可信裁定仍未闭合。
