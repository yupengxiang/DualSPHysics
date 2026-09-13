# L2 远程审阅入口

本目录是 `L2_MULTI_FAMILY_QUALIFICATION` 的可提交审阅面。它保留：

- 审阅者计划原包及 SHA-256；
- A0/A1/B1/B2/C0/C1/C2/C3/D0/E0 的机器报告和 Markdown 摘要；
- `state.json`、`queue.json`、`ledger.json`；
- L2 canary 的输入定义、控制文件、读者、执行脚本和测试；
- 原始归档、HDF5/BI4/CSV/VTK 的路径、大小和哈希证据。

普通 Git 提交不包含数 GB 的原始求解轨迹。对应输出由
`lagrangian-fluid-lab/.gitignore` 明确排除；这不是把它们当作已上传，而是
保留可审阅的 provenance、哈希和失败/通过结果。没有真实对象存储地址时，
不能把本机路径伪装成远程数据链接。

## 审阅顺序

1. 阅读 `reports/e0-campaign-closeout.json` 和 `reports/e0-campaign-closeout.md`。
2. 用 `state.json`、`queue.json`、`ledger.json` 核对机器状态和资源账。
3. 按 A0→A1/B1/B2→C0→C1/C2/C3→D0 的报告顺序查看证据。
4. 查看 `scripts/l2_*.py`、`scripts/l2_reader.py` 和 `tests/test_l2_campaign.py`，复核执行与审计逻辑。

## 本次结论边界

- 32 个旧 F3 案例仍是 registered numerical development asset，不是本轮新家族资格。
- C3 的 F4 仅为通过结构 canary；F5 失败，F6 只冻结设计。
- D0 因没有新晋 T1 recipe 保持 blocked；没有启动生产批次。
- B2 的两条三种子结果是 candidate-only 开发诊断；没有模型物理资格化。
- `public_release_authorized=false`、`hidden_test_generation_authorized=false`，旧 L1 保持只读。

## 本地验证

```text
lagrangian-fluid-lab/.venv/bin/python scripts/l2_campaign.py status
lagrangian-fluid-lab/.venv/bin/python -m pytest -q tests/test_l2_campaign.py
```

原始轨迹若要在另一环境重放，需要由所有者提供获准的数据 bundle 或对象存储；
本提交不声称该外部可访问性已经配置。
