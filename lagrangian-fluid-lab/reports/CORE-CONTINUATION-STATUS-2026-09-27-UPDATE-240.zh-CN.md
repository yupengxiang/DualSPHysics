# Core continuation status — 2026-09-27 — UPDATE-240

## F3 real-case model profile: two-hop provenance blocker

在 UPDATE-239 的真实 F3 reader → material sidecar 端到端 smoke 之后，按同一真实案例做了一个有界的 `core_learning.py profile` 接口探测：`graph_raw`、seed `17`、`steps=2`、`hidden=16`、`chunk-size=256`、CPU。该动作不是正式训练，也没有创建 checkpoint；完整命令、源文件哈希和失败回执保存在 [`F3-MODEL-PROFILE-REAL-BLOCKED-2026-09-27.json`](F3-MODEL-PROFILE-REAL-BLOCKED-2026-09-27.json)。

profile 在第一个预测步骤前以 `ValueError: neighbor provenance is truncated for a required two-hop row` 退出，调用边界为 `neighbor_table(return_provenance=True) → two_hop_halo → validate_neighbor_provenance`。现有 formal graph 路径的默认 neighbor cap 为 `64`；validator 对请求中心及其 one-hop 行所需的 two-hop 来源采取 fail-closed 语义。该结果是一个真实输入接口阻塞的可复现诊断，不是物理或模型质量结论；没有通过降低约束、删去截断行或改写正式 cap 来绕过它。

下一步仅做 synthetic-only 的 cap/provenance 诊断，区分“提高诊断 cap 后 provenance 完整”和“无关行截断仍可保留”的边界；该诊断不会改变 `core_models.py`、训练准入、T1/T2、gate 或 credit。当前 profile 的 `formal_training=false`、`T1_numerical=false`、`native_integrity=false`、`gate_decision_eligible=false`、`qualification_credit=0`；未修改生产 HDF5、registry、ledger 或分母，也未启动 solver/worker/GPU/queue。
