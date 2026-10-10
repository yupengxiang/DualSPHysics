# DS DATA 02 历史引用哈希差异补充核对

完整元数据包沿关键证据展开两层引用，共收集 9,795 项元数据或源码文件。对形如 `path/sha256` 和 `report/report_sha256` 的记录做字节 SHA 对照后，发现 **80 次历史或上下文引用差异**，详细 expected、当前 bundled SHA、referrer 和 path 见 `REFERENCE_HASH_AUDIT.json` 及完整包 `EVIDENCE_INDEX.json`。

| 引用种类 | 差异次数 | 解释范围 |
|---|---:|---|
| 动态共享 resource ledger | 15 | 旧 checkpoint 记录的是当时账本 SHA，当前路径为截止时账本；旧快照的不可访问性不能由当前账冒充解决 |
| Stage1 F4 的两份执行收据 | 2 | 旧记录预期 SHA 与当前可读取收据不同；本次未改这些收据，需检查原恢复/终结谱系 |
| 历史 source/control JSON | 61 | 需分别检查 byte SHA、canonical JSON SHA、版本修补和路径复用，不应概括为 61 个损坏文件 |
| 历史 source Python | 2 | 当前字节与旧记录不同，需要实际启动代码快照，不能以当前 HEAD 替代 |

这不是 80 个科学数据损坏案例，亦不是 80 个独立文件的损坏证明。同一路径可以被多次引用；本次没有读取或重新 hash 原始科学数组。引用哈希口径未逐条判定，保持待审阅，不擅自把原 expected SHA 改成当前 SHA。

本次 `CLOSEOUT_VALIDATION.json` 对近期 78 个字段扫描、ROOT711–717 原生关联、ROOT709/710 和 ROOT371 的 request、actual receipt、report、terminal CPU 证据和记录哈希一致性单独核对，通过。历史上下文差异不自动否定这组核对，也不被这组通过结果抹去。

请审阅者进一步区分：可预期的 live-ledger 变化、正确记录的 canonical 摘要、需要 snapshot 的源码漂移、无法证明的收据变化。完整 raw replay、完整历史 immutable source closure 仍不能作出。精简包只保留关键证据及必要运行记录，未展开的深层上下文可以在完整包中核查。

最终总报告为 `FINAL_REPORT_ZH.md`，是在原 `SUMMARY_REPORT_ZH.md` 保留字节的基础上追加本发现的新副本。初版 ZIP 和原汇总不覆盖；最终完整包和精简包另用 V2 和 COMPACT 文件名保存。
