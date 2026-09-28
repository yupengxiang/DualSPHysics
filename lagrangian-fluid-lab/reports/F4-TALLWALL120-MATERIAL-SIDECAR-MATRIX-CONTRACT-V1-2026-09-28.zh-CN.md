# F4 Tallwall120 material sidecar matrix contract V1

日期：2026-09-28

## 结论

该报告冻结 F4 Tallwall120 的 32-case material sidecar matrix 接口，当前状态为 `blocked_fail_closed`。它是 diagnostic / proposal / contract-only 产物，不是执行授权，也不产生 T1、T2、qualification 或任何 credit。

固定矩阵为：

- scope：`F4_resting_pool_laminar_tallwall120_x_v1`
- case 数：32
- split：`train=16`、`validation=4`、`id_test=6`、`ood_test=6`
- 每个 case 必须有唯一的 `core.material.f4.tallwall120.material_sidecar.v1`
- 每个 sidecar 必须绑定 fresh、不可覆盖的独立 output namespace

## 必需 material markers

每个 sidecar 必须提供完整 event-window terminal 证据：

- event window 至少 `8.68 s`，并且 terminal execution 完整；
- mass closure error 不超过 `1e-12`；
- unknown fraction 不超过 `0.01`；
- reliable coverage 至少 `1.0`；
- `right_censor_status` 必须为 `not_right_censored`。

partial terminal、right-censored / unresolved、缺 marker、source 不匹配、重复或缺失 case 均 fail-closed；不允许事件插值或 partial credit。

## 当前阻塞

- collection case trajectory 仍使用 `archives-v1`，而 DEV_07 proposal 的 fresh source 使用 `archives-v2`；
- DEV_07 collection source path 与 proposal source path 不一致；
- reader smoke 记录的 collection manifest SHA 与当前 manifest SHA 不一致；
- receipt consistency audit 仍报告 archives-v1/v2 path drift；
- 32 个 material sidecar 均尚未提供，不能把 native CFD collection 或旧 DEV_07 diagnostic 当作 material sidecar；
- 当前 DEV_07 material evidence 仍缺 fresh terminal evidence，并保留 right-censored / unresolved、unknown fraction 与 reliable coverage 阻塞。

## 边界与授权

本 contract 只读取 bounded JSON 和小文件 metadata。trajectory HDF5 仅保留 path / declared SHA / filesystem metadata，不打开、不读取内容、不重新哈希。没有启动或控制 solver、worker、GPU、queue，也没有写入 registry、ledger、denominator、gate、completion 或 production HDF5。

输出固定为 `formal=false`、`formal_eligible=false`、`qualification=false`、`T1=false`、`T2=false`、`credit=0`、`qualification_credit=0`，fresh namespace 也不等同于执行授权。

机器可读结果见同名 JSON；实现与专项测试分别位于 `scripts/f4_tallwall120_material_sidecar_matrix_contract_v1.py` 和 `tests/test_f4_tallwall120_material_sidecar_matrix_contract_v1.py`。专项测试覆盖固定 denominator、duplicate/missing case、split drift、archives/reader drift、partial/right-censor、wrong source、formal/credit claim 与 report binding。
