# F3 native-volume MLS 8192-seed high-quadrature bounded canary（2026-09-28）

本报告是 `F3_DEV_00_a0p903125` 的 diagnostic-only 材料数据集诊断，不是 formal acceptance。运行严格使用现有 native-volume MLS high-seed wrapper；没有扩展运行窗口，没有修改 gate、PLAN、production HDF5、manifest、registry、ledger 或 denominator。

## 输入与命令

- source：`campaigns/l1-resume/data/continuation/F3_DEV_00_a0p903125.h5`
  - SHA256：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`
- prepared：`campaigns/l1-resume/continuation/F3_DEV_00_a0p903125-PREPARED.json`
  - SHA256：`9d6af616764163a7796763f061d3f2c7468640eb3b0924ee768f26aa9c7969b9`
- 参数：`--seeds 8192 --substeps 4 --stop-after 4`
- recovery 故障注入：`--kill-after-h5-append 2`；随后同一输出使用 `--resume` 完成。

输出前缀为 `/tmp/f3-native-volume-mls-high8192-canary-20260928-a0p903125`。完整 machine receipt 已保存在同目录 JSON 报告中对应的 `/tmp` receipt provenance 下。

## 几何、source binding 与 trace 完整性

| 项目 | 结果 |
|---|---:|
| high-seed 规则 | 64 × 16 × 8 tensor-product midpoint |
| seed 总数 / source 0 / source 1 | 8192 / 4096 / 4096 |
| source box | `[-0.45,-0.09,0.0]`，size `[0.9,0.18,0.09]` m |
| source geometry SHA256 | `8f281c79fc0fd1622493c26d587f94394a2373555273891bd61c515ba9c18020` |
| seed points + labels SHA256 | `2a0345d0c11aacd4619e9c8443369e3702cdfc0bb9abf4dc6bac8f55424bdd4b` |
| source frames / particles | 836 / 34560 |
| trace frames / transitions | 5 / 4 |
| trace time | `0`–`0.04001995862593706` s，严格递增 |
| frame policy | 当前 native frame；无插值、禁止 future velocity/density |
| position shape | `[5,8192,3]` |
| physical/gate arrays finite | 通过 |
| native mass | `14.580000378191471` kg，所有 trace frame 恒定 |
| seed mass closure 最大绝对误差 | `0.0` kg |
| reliable false / permanent unknown | `0 / 0` |

`first_passage` 与 `return_time` 各有 `40960` 个 NaN，这是本次短 canary 没有发生 crossing/return 时的预期 right-censored event timestamp，不是 position、time、mass 或 gate 数值非有限。两侧均未观察到 first-passage、return 或 opposite-source residence 事件。

## candidate/original gate 诊断

| 诊断 | 结果 |
|---|---:|
| candidate support gate false samples | 0；全部通过 |
| candidate support count 最小值 | 43 |
| candidate effective sample size 最小值 | 12.188258496915166 |
| candidate geometry rank 最小值 | 4 |
| candidate condition number 最大值 | 2.8538937210025743 |
| original F3 gate comparison false samples | 0；本短窗口全部通过 |
| reconstruction error 最大值 / original limit | `0.00910835133416617 / 0.04698137929009748` m/s |
| anisotropy 最小值 | 0.5197600974410083 |
| wall rejected 最大值 | 0 |

这些 gate 结果只适用于 4-transition bounded canary；不能外推为 full-window 材料资格或 T1/T2 acceptance。

## Checkpoint / recovery

故障注入后，未 checkpoint 的 HDF5 行仍在，但 durable manifest 保持在 frame 1：`manifest_committed_frame=1`、HDF5 `committed=2`、time 行数为 3。`--resume` 按最后 manifest generation 恢复并截断该多余行，随后提交 frame 2、3、4。

恢复完成后的证据为：manifest/HDF5 均指向 frame 4，time 行数 5，checkpoint generation 数 5；最终 generation 文件 hash 与 manifest 匹配，state hash 校验通过。该结果证明 bounded checkpoint/recovery 路径可用，不代表 scientific qualification。

## 结论与未解决问题

- `diagnostic_only=true`；`qualification=false`、`formal_eligible=false`、`T1=false`、`T2=false`、`credit=0`。
- 本次只覆盖 `0.04001995862593706 s`，远短于 source 的 `8.350012828223477 s` full horizon；事件/CDF 证据因此被 censor，不能作为 formal acceptance。
- candidate 与 original gate 在这个短窗口均通过，但不改变既有 gate、registry、ledger、denominator 或 PLAN 状态。

machine receipt：`F3-NATIVE-VOLUME-MLS-HIGH8192-CANARY-2026-09-28.json`。
