# Core 材料 T2 候选只读审计（2026-09-28）

结论：`blocked_negative`。现有 F3/F4 材料候选没有一条能在当前授权下进入 T2；本轮没有启动 solver、worker、queue、native 或特权 workload，也没有修改阈值、registry、ledger、denominator、gate。

- F3 baseline24、h2_k48、h1_affine_bound 和 native-volume MLS v2 均有完整 `836 frames / 835 transitions`；前 3 个因 unknown gate 失败，MLS v2 虽 unknown=0 且 candidate gate 通过，但原 F3 gate 仍有 `441` 个失败样本。
- F4 DEV_07 baseline24 为 `218/217`，unknown=`1.0`、coverage=`0`、事件窗 right-censored；历史 cell-14 native004 trace 只有 `101/1086` frames 且 source 未绑定 DEV_07。
- F3 high8192 只有 `5/4` frames、结束时间 `0.04001995862593706 s`，只是短 canary，不是材料资格证据。
- bridge/decision synthetic tests `19 passed`，material contract tests `24 passed`；历史 hash-closure probe 为 `24 passed, 1 failed`，失败是旧 receipt 的源码 byte count 过期，不是正向 T2 证据。

因此 F3/F4 T2 与 credit 均保持 false/0。下一步必须获得明确授权并建立 exact-source-bound formal overlay/acceptance receipt；不能把本审计转成 solver/worker/native 运行。
