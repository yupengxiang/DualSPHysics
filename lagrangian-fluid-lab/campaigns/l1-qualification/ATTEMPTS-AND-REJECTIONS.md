# Attempts and Rejections

失败、中断和重试都计入额度；它们没有被从机器报告中删除，也没有被后续成功 attempt 覆盖。完整 attempt JSON 位于各 case 的 `runs/` 目录（该目录按策略不进 Git），W1 汇总在 `l1-f1-qualification.json`，W2 汇总在 `l1-w2-boundary-control.json`。

## W1 rejected attempts

| case | attempt id | mode / GPU | return | reason | disposition |
|---|---|---|---:|---|---|
| h09 fine | `20260909T042347.054240Z-a6ac3161` | CPU | -2 | external/manual interruption | rejected; later GPU retry retained |
| h10 coarse | `20260909T043328.038191Z-d982ce4b` | CPU | -2 | external/manual interruption | rejected; later GPU retry retained |
| h10 fine | `20260909T044035.820631Z-62ca5e43` | GPU 4 | -12 | free VRAM guard | rejected; later GPU retry retained |
| h10 medium | `20260909T043409.133360Z-6d7161b8` | CPU | -15 | operator stop | rejected; later GPU retry retained |
| h11 coarse | `20260909T044521.562269Z-3e0e5c47` | GPU 4 | -15 | operator stop | rejected; later GPU retry retained |
| h11 medium | `20260909T051112.384184Z-e5746a08` | GPU 6 | -12 | free VRAM guard | rejected; later GPU retry retained |
| h11 time | `20260909T032521.202848Z-f93dec46` | GPU 6 | -2 | external GPU reclaim/interruption | rejected; later GPU retry retained |

W1 的 11 个最终完成 attempt 分别覆盖 h10/h11 time 和三高度 × 三分辨率 space；它们的完整审计仍在 `audits/`。成功运行不等于验收通过：三个 fine space case 的物理/身份门仍失败。

## W2-A

唯一 W2-A attempt 为 `20260909T084935.853746Z-e7b60fa5`，GPU 4，return 0，solver 完成但 full audit rejected：native `position` exclusions=49,769，闭壁越界=1371 帧，最终身份保留率=0.1713453213。它保留为负诊断证据，不作为新 baseline。

## 额度解释

总 qualification attempts=19；W1 的 guard stop=2，W2-A guard stop=0。没有删除、覆盖或重命名 N4 历史 attempt；F6 新 solver 和训练 attempt 均为 0。
