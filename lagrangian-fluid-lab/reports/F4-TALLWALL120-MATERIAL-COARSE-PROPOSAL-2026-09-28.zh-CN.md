# F4 Tallwall120 DEV_07 coarse material proposal（静态、fail-closed）

本报告只登记一个新的 source-bound coarse material proposal，不执行 material tracer。机器报告为 `F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json`，schema 为 `core.material.f4.tallwall120.coarse_proposal.v1`。

## 固定绑定

- case：`F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`
- source：`campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/f4-tallwall120-production-dev-07/product/trajectory.h5`
- source SHA-256：`6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae`
- native shape：218 frames、217 transitions、`time_end=4.340002980805959` s、217485 particles
- 直接 source manifest：v2 `archive.json`，SHA-256 `49412fb74e488628ccb0fa15ce0aa808c1e723fb8821196e79b646a3121513e5`；其 `product/trajectory.h5` output 与目标 source SHA/bytes 完全绑定。
- Core collection manifest：`collection-refresh-terminal32-formal-v1.json`，SHA-256 `808fe201c4df28f2be9b48a514f338689c38bcb96db0b0c0590946b79fb9ad09`。
- known-input contract：`core.inputs.v1`，重建 SHA-256 `7d3c28ae71e165ecb679545c78a9d7c2fc087593d41157a7fd0a214e97c14724`，contract 校验通过。
- prepared 参数：`q=0.23437500000000008`、`drop_left_x_m=0.3015625`、`dp_m=0.0075`；不继承 qualification。

代码快照使用 canonical path+file-SHA256 列表，`code_snapshot_sha256=5351b95e863b2f50353f9dc6080f374a49345fdb824fff14dba1bd9c286eab7e`。报告逐项列出 `core_material.py`、F4 tracer、diagnosis、Core contract/dataset/adapter、neighbor/passive helper 和本 proposal planner 的 SHA。

## 固定执行契约（当前不执行）

coarse 参数固定为 baseline24、512 seeds、substeps=2、217 stop-after frame；argv 及 diagnosis argv 已逐项写入 JSON。计划输出 namespace 为：

`campaigns/core-v1/material/proposals/f4-tallwall120-production-dev-07/coarse-baseline24-s2-r001-source-6ae8ca70`

该 namespace 当前不存在，禁止 overwrite/resume，也禁止复用历史 `/tmp` trace 或 qualification-cell-14 trace。完整 material source 只有 4.340002980805959 s；若事件 right-censored，不能伪造 8.68 s extension，必须另行取得授权的 native source。

## 当前阻塞

1. Core collection 的 DEV_07 行仍声明 `archives-v1` 路径，而 proposal 目标是 `archives-v2`；虽然行内 source SHA 相同，但路径不相等，已 fail-closed，不能当作别名自动继承。
2. 缺 fresh root/material-definition review、fresh resource admission、runtime authorization 和 namespace reservation。
3. 本 proposal 没有 material trace/diagnosis，不能制造 material labels；one-shot authorization 保持未消费。
4. trusted Core reader formal gate 仍为 false；manifest 内 `formal_eligible=true` 的声明不能覆盖 trusted reader/admission evidence。

因此机器状态固定为 `blocked_fail_closed`、`proposal_only=true`、`diagnostic_only=true`、`formal_eligible=false`、`T1=false`、`T2=false`、`credit=0`。本次未启动 solver、worker、native、GenCase、GPU 或 queue，未修改 PLAN、registry、completion、ledger、denominator 或 gate。
