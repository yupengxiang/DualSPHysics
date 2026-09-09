# L1-R continuation checkpoint

先读 [中文交接](L1R-CONTINUATION-HANDOFF.zh-CN.md) 和 [机器状态](EXECUTION-STATE.json)。这是阶段交接，活动未关闭；F3 输入修复已完成，六次重跑的子额度调剂尚待所有者确认。原六次初始化失败保留且计数。

## Evidence map

| 内容 | 文件 |
|---|---|
| 官方 601 帧身份/排除/质量与几何验收 | `Q1-ACCEPTANCE.json`, `Q1-FINAL-GEOMETRY-FRAMES.json` |
| 原生 BI4 读取器与 PartVTK 核对 | `Q1-NATIVE-READER-VALIDATION.json` |
| 官方外部水位/压力观察 | `Q1-OBSERVABLES.json`, `Q1-ELEVATION-COMPARISON.png`, `q1-measure/` |
| 旧 Q2 逐身份轨迹及容差过程 | `Q2-TRAJECTORIES.json` |
| 实际模块上的 reviewer 探针 | `REVIEWER-PROBE-ACTUAL.json` |
| 旧 Q0 十例重评 | `q0-final/SUMMARY.json` |
| 配方差异与初态/normal/ghost | `RECIPE-DIFFERENCES.md`, `RECIPE-DIFFERENCES.json`, `GEOMETRY-AND-INITIAL-STATE.json` |
| 新 F1 候选实际结果 | `Q2C3_*-AUDIT.json`, `Q2C4_*-AUDIT.json`, `F1_OFFICIAL_*-AUDIT.json` |
| F3 初始化失败及已验证修复 | `EXECUTION-STATE.json`, `F3-INPUT-REPAIR-READY.json`, `*_INPUTFIX-INPUT-PREFLIGHT.json` |
| 累计预算 | `RESOURCE-LEDGER.json`, `RESOURCE-PREFLIGHT.json`, `HISTORICAL-CPU-RESERVE.json` |
| 测试 | `pytest-final.txt` |

大体积原始 BI4/HDF5 留在本地并保留摘要，不加入 Git 或审阅 ZIP。

## Reproduce read-only checks

从仓库根目录编译两个薄适配器；输出位于被忽略的 artifacts 目录，上游源码不变：

```sh
g++ -std=c++14 -O2 -Isrc/source lagrangian-fluid-lab/scripts/native/bi4_dump.cpp src/source/JBinaryData.cpp src/source/JObject.cpp src/source/JException.cpp src/source/Functions.cpp -o lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump
g++ -std=c++14 -O2 -Isrc/source lagrangian-fluid-lab/scripts/native/check_acc_input.cpp src/source/JReadDatafile.cpp src/source/JObject.cpp src/source/JException.cpp src/source/Functions.cpp -o lagrangian-fluid-lab/campaigns/l1-resume/artifacts/check_acc_input
```

然后在 `lagrangian-fluid-lab` 目录中：

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.l1r_continuation_evidence ledger
.venv/bin/python -m scripts.l1r_continuation_evidence q2
.venv/bin/python -m scripts.l1r_q1_native
.venv/bin/python -m scripts.l1r_q1_reconcile
.venv/bin/python -m scripts.l1r_repair_f3_inputs
```

Q1 native 已完成时直接复用，不重复 CFD。重评脚本只读原始轨迹并写补充审计；`*-PREVIOUS.json` 保留前版差异。全部动态启动仍必须经过共享预算、UUID/显存及输入预检。`l1r_branch_runner f3` 不会自动放宽已用尽的六次 F3 子上限。

`l1r_q1_stream.py` 是本轮使用过的 CSV 分块参考实现，原生读取器为推荐入口。`l1r_f3_metrics.py` 只为存在真实、完整轨迹的后备矩阵评分；当前没有 F3 动态轨迹，不能执行出物理资格结论。
