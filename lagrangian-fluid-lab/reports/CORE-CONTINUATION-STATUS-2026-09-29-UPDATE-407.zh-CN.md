# Core continuation status — UPDATE-407

日期：2026-09-29

本轮只收口测试收集边界，不改变任何科学门禁。仓库根目录此前没有 pytest 配置，默认发现会递归进入 `lagrangian-fluid-lab/campaigns/core-v1/runtime/snapshots` 的归档链接树；`6172c87a` 新增 root/lab 两层 pytest 配置，明确测试路径并排除 `snapshots`。

## 已提交的可交付单元

- `6172c87a`：新增根目录和 lab 目录 pytest collection 配置，以及诊断报告。root-level `--collect-only` 得到 `5,324` 个测试，约 `4.06 s`；显式 `lagrangian-fluid-lab/tests` 也得到同一 `5,324` 个 node，nodeid 集合一致，snapshot 路径收集命中为 `0`。已有 runtime snapshot 文件 `26,980` 个均保留，未删除或改写。

## 回归与执行边界

这次只验证 collection boundary，没有宣称全量测试已完成；此前从错误根目录启动的全量 pytest 已按 UPDATE-406 记录为 collection 失败，不再重跑。显式 raw/residual/MLP/F4/F8/A8 回归的最新通过数仍为 `339/187/158/236/34/35`。本轮没有启动 production workload/Popen/GPU，没有读取 production data，没有停止或重启已有进程，也没有修改 registry、ledger、denominator、gate 或 completion。

当前 GPU0–7 各约 `48,497 MiB` free。显存可用仍只表示资源条件满足候选使用，不替代 scheduler trust anchor、runtime identity、terminal receipt、外部 root/host attestation 或 formal gate。

## Core 门禁

Core 状态不变：`can_finalize=false`，T1 families=`F3/F4`，macro T2=`0/2`，formal training=`0/9`，T1 case-run 缺 `288`、material case-run 缺 `288`，independent reproduction=false，credit=`0`。下一步可以安全使用 root-level pytest 做受控专项/分组回归；正式训练与资格证据仍等待真实外部 authority、terminal 和 reproduction evidence。
