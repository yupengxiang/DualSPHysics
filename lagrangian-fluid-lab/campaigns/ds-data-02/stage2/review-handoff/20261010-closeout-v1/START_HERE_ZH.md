# DS DATA 02 第二阶段审阅包阅读入口

本包用于评估长时间执行后的成果、失败和下一步方向。当前科学资格目标尚未完成，实际执行已按用户要求收尾；没有后台扫描或 solver 继续推进。

建议阅读顺序：

1. `SUMMARY_REPORT_ZH.md`：总报告，含七项目标、14 哨点、资源、失败、执行效率和未完成范围。
2. `REVIEW_REQUEST_ZH.md`：本轮希望审阅者回答的问题及所需输出。
3. `EVIDENCE_INDEX.json`：E001–E057 的关键证据和全部包内路径、大小、SHA256；excluded 列表说明没有随包提供的 payload 或不可访问引用。
4. `repo/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-handoff/20261010-closeout-v1/CLOSEOUT_VALIDATION.json`：78 字段扫描、七个新关联批次等收据/哈希/计费元数据复核。
5. 同目录 `RESOURCE_SUMMARY.json`、`RESOURCE_LEDGER_SNAPSHOT.json`、`EXECUTION_CUTOFF.json` 和 `CLOSEOUT_TESTS.log`：资源、历史未完全终结行、停止 waiter 和十项源码测试。

在另一台机器上可以只验证 ZIP 完整性，不访问任何原始绝对路径：

```bash
python3 verify_bundle.py DS_DATA_02_STAGE2_REVIEW_20261010_V1.zip
```

该命令验证 CRC、文件长度和 SHA256，不重放原始流体、不验证物理精度。`repo/` 放仓库源码和小证据，`local-data/` 放实际运行的有界报告与收据，其他前缀放旧源码或原审阅附件。原文件中的 producer 路径不改写，阅读时用 `EVIDENCE_INDEX.json` 映射到包内 member。

本包不含 H5、BI4、JSONL、科学 CSV/DAT 或全粒子关键事件窗口，**不是 minimum raw replay bundle**。它能支持元数据/执行事实审阅，不能支持完整科学数组独立重算。仍缺的原始重放材料应由审阅者具体指定范围，后续单独打包。

旧文档中的持续执行、试验计划和资源软规划均属于历史材料，不能覆盖最新用户收尾要求。ROOT718/719/720/721 的源码或请求是 source-only，未获执行信用。不要执行包中旧启动命令或自动恢复依赖等待链。

远程代码入口：`https://github.com/yupengxiang/DualSPHysics/tree/codex/ds-data-02-stage2`。实际推送版本以外部发布收据和最终 Git HEAD 为准；如果没有推送成功记录，不能只凭此 URL 声称已发布。
