# UPDATE-58：F8 `TimeMax` 与递归 OPT 覆盖顺序

日期：2026-09-25（Asia/Shanghai）

在 UPDATE-57 控制查询源码链基础上，继续只读追踪 `JCfgRunBase`/`JSphCfgRun`：命令行参数按顺序解析；`-OPT` 在其出现位置立即 depth-first 递归展开；文件按 cwd 解析、每文件最多 50 个 token、最多 10 层配置递归；反复的 `TMAX` 按 expanded token stream 后值覆盖前值。完成 parser 后，正值 cfg `TimeMax` 覆盖 XML 值；运行中的 `TERMINATE`/minimum-fluid stop 还能继续改 horizon，`NstepsBreak` 独立提前退出。

故 execution contract 必须冻结完整 argv、cwd、所有递归 OPT 文件原始字节/hash 与展开顺序，而不能只记录最终 `TimeMax`。尚无任何 R008 solver attempt 与 OPT/executable/runtime horizon 的绑定；本审计不实现、不运行任何东西。真实 control gate 仍 open。详见[静态审计](F8-R008-TMAX-OPT-OVERLAY-AUDIT-2026-09-25.zh-CN.md)。
