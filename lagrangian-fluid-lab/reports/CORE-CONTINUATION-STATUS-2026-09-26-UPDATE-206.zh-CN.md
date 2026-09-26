# UPDATE-206：F8 R008 terminal completion contract v1 复核与 v2 修订

时间：2026-09-26（Asia/Shanghai）

## v1 只读 review

对 [terminal completion evidence contract v1](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V1-2026-09-26.zh-CN.md) 的 CPU 官方源码复核为 `REVISE`。步数 telescoping 和同次 RunPARTs/BI4 PART metadata 联结在无重启、同一 writer、严格 parse 条件下成立；但发现：

- **P1 fresh-run false pass：** `PARTBEGIN:12:0:<dir>` 可加载旧 PART，而内部 `PartIni=0`、`TimeStepIni=0` 仍成立。必须校验实际 loaded source 与冻结 GenCase 初态同源、并拒绝 restart/append，不能只检查这两个零值。
- **P2 格式不足以互操作：** receipt exact schema 的所有 key/type、规范化 bytes/签名 payload 未固定；RunPARTs 16 位时间文本与 BI4 binary64 的映射规则亦须逐字定义。
- **P3 durability 措辞：** CSV writer 做 stream flush/error check；BI4 writer 关闭前检查 stream，但未见 `fsync` 或 close error check。应将保证限定为进程退出后 reopen 可见并完整 parse/hash，而非掉电持久化。

新增 [terminal completion/artifact-visibility contract v2](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V2-2026-09-26.zh-CN.md)：明确 fresh source、exact-field wire schema、UTF-8 canonical JSON 与 domain-separated Ed25519 签名 bytes；规定 RunPARTs 时间文本按 SHA-pinned 官方 `RealStr(16)` 精确对照；把 durability 保证限为 post-exit 文件可见性/复验。它仍待独立只读复核，且缺可信 supervisor/trust registry，不能接入 qualification gate。

## 边界

源码核验了 `JSphCfgRun.cpp` PARTBEGIN 解析、`JSph.cpp` 重启加载/PartIni/TimeStepIni 赋值、RunPARTs 与 BI4 保存路径、`JPartDataBi4.cpp` Part metadata、CSV/BI4 writer。只读，没有测试、生产数据或 workload；没有修改 solver、scope、registry、ledger、分母、资格信用或执行权限。
