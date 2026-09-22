# F3 native MLS acceptance adapter/receipt bridge（2026-09-21）

结论：本次只读 bridge 为 `blocked（zero credit）`。formal receipt 状态为 `blocked`、credit=`0`；始终保持 `T2_macro=false`、`T2_path=false`、`qualification_claim=none`。

本脚本只读取上游 gap JSON 和源码文本/哈希；没有打开 HDF5（包括 source/trace/checkpoint 文件），没有启动 solver、GPU 或 queue，也没有修改 registry、ledger、matrix、T1/T2 分母、固定阈值或旧 evidence。

机器回执：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f3-native-mls-acceptance-bridge-v2-20260922.json`；SHA-256：`9826c1b543a861226b38e941b214bdd45f03a353bdf390f87f9b4778449160f3`。

## 固定门与桥接结果

| 门 | 固定规则 | bridge 结果 |
|---|---:|---|
| trace/checkpoint schema | 允许 v1/v2/temporal-v3 的成对 schema | `true` |
| source-window 完整性 | 质量、hash、reader、mass、checkpoint 绑定 | `true` |
| native cadence | `.002 s`，source tolerance `5e-05` s，direct every-fifth 无插值 | `true` |
| 逐 source unknown | `<= 0.01` | `false`；最大 `0.015625` |
| first-passage / return / residence CDF | 每 source、全分母、sup `<= 0.02` | `false`；最大 `0.06103515625` |
| right-censored event | right-censor 不计 acceptance | `false` |
| full event window | `8.35` s 且无 right-censor | `false` |
| formal matrix receipts | `33` 行均须独立 receipt | `false`；当前 `0` |

## 证据绑定

当前上游 source-window 行数为 `2`。每行保留 trace schema、checkpoint schema、frame/time-end 和 full-window 判断；source/trace HDF5 的路径和 hash 由 gap audit 的 JSON closure 继承，bridge 不重新打开或重新 hash HDF5。

unknown 逐 source 保留 denominator、unknown count/fraction、首次失败 frame/time 和 reason counts；unknown 不能被 aggregate 数字隐藏。三类 CDF 均保留 source-level sup bound，并按全 source 分母计算。

event contract 固定 first-passage、return、residence 定义；permanent unknown 和未观察事件属于 right-censor，bounded native cadence canary 当前 full-window=`false`、right-censored=`true`，因此 acceptance credit 为 0。

## 33-row diagnostic 边界

注册矩阵为 `33` 行（`0-23 resolution_substep; 24-27 cadence; 28-32 seed_density`）；当前 diagnostic terminal rows 为 `16`，formal acceptance receipt 为 `0`。diagnostic row 完成、terminal trace、matched-decimation view 或 source 可用都不能升级 T2。

## 阻塞原因

1. per-source unknown gate fails: maximum 0.015625 > 0.01
2. first-passage/return/residence CDF gate fails: maximum 0.06103515625 > 0.02
3. bounded native-cadence canary is right-censored or shorter than the full registered event window; it has zero acceptance credit
4. the registered 33-row overlay contains diagnostic rows only; diagnostic completion cannot promote a row to T2

## 输入哈希

- `t2_gap_audit`：`campaigns/core-v1/material/evidence/f3-t2-admission-acceptance-gap-audit-20260921.json` — `6a62d5b5857cd1512e33d557c87a96b51adb98ad1b336e5067e2c73e43e68f1a`
- `native_mls_v1`：`scripts/f3_native_volume_mls.py` — `e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9`
- `native_mls_v2`：`scripts/f3_native_volume_mls_v2.py` — `cd1c050757df7b0d5832181464d446cf6e8c678e2b150aa07bae0ddb0ee3b5f9`
- `native_mls_temporal_v3`：`scripts/f3_native_volume_mls_temporal_v3.py` — `30ea09d28bcf1edf2a4dfbab5ff314c593e26cc942ab125bbcacad854568d395`
- `native_mls_compare`：`scripts/f3_native_volume_mls_compare.py` — `d4fc40b0b0057b4b0fc2487560d709f01c95068109a028e2664bc9f6fdf44acb`
- `native_cadence_adapter`：`scripts/f3_native_cadence_adapter_v1.py` — `746477383578df5edcef927e72aaff706d8a2621ff01f435cb9d65fd425dd42e`
- `core_material_acceptance`：`scripts/core_material_acceptance.py` — `b9cb49cacf19590356bda4f32d32ef3d2255b9c97a8afa29a920e5a38bd6c4a7`
- `bridge_implementation`：`scripts/f3_native_mls_acceptance_bridge_v1.py` — `10832aeffeb9a06a994a56056849df34c646b54711747832e6de298b357cc14d`
