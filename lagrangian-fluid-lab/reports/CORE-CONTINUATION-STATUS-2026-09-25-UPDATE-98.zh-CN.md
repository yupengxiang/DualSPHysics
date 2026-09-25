# Core 计划续推状态 UPDATE-98

日期：2026-09-25（Asia/Shanghai）

## 本次推进：legacy CoreDataset 不再可晋升为正式资格

按 UPDATE-97 指出的旧 `CoreDataset` Mapping/path 资格旁路，收紧现有读取与 learning 入口：

- `CoreDataset` 的 strict 模式仍执行数据完整性校验，但 `formal_release: true` 不再令 `formal_eligible` 成立。Mapping 与 JSON 路径入口行为一致。
- learning 端 `_manifest_formal_release()` 在 V13 verified-reader capability 尚未实现期间 fail closed。因此旧 reader 的训练验证资格为 false；`evaluate_checkpoints()` 的正式模式在读取 checkpoint 文件前拒绝；`evaluate()` 的回执保持 diagnostic，即使 manifest 声称 formal。
- 回归覆盖 strict Mapping/path 两种入口、formal manifest 不能授权训练验证/模型选择，以及 CLI 全 test 与单 case 范围都只生成 diagnostic 回执。`formal_evaluation_gate()` 的纯策略检查保留，但它本身不构成可信 reader 或正式入口。

定向测试结果：`tests/test_core_contract.py` 与 `tests/test_core_learning.py` 共 71 passed；`tests/test_core_campaign.py` 与 `tests/test_core_package.py` 共 55 passed。使用仓库 `.venv`；系统 Python 的 h5py/NumPy ABI 不兼容，未改依赖。`py_compile` 与 `git diff --check` 通过。

## 状态边界与后续

该改动关闭的是“旧 reader 因 manifest 布尔值而获得正式资格”的入口，不实现 V13 snapshot/broker/worker identity capability。legacy reader 的二次 pathname HDF5 open 与同 FD/snapshot 绑定缺口仍在，但其正式资格被关闭；`core_formal_planner` 任意 Mapping/path ingress 与 F4 connector ingress 是独立路径，尚未处理。不能把 strict hash、诊断评分或本轮测试计为 F8 T1、Core T1/T2 或生产资格信用。

未读取受保护生产 bundle/frame/one-shot 文件；未运行 planner、collector、preparation、GenCase、native decoder、solver、worker、GPU 或 queue；未读取或改写 F3/F4 一次性授权材料。只运行本地合成回归测试。R008 readiness/T1 状态与零信用不变。

本项已提交并推送后才算仓库历史记录完成；PLAN 中的其它未完成路径继续保留待办。
