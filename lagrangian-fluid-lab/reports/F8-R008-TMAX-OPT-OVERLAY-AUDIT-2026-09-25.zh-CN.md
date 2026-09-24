# F8 R008 `TimeMax`／OPT overlay 静态审计（2026-09-25）

## 结论

对标准 `src/source` 的运行配置 parser 只读追踪后，可确定静态覆盖顺序：**case XML 初始化 → 命令行及其递归 OPT token stream（按遇到顺序、depth-first inline）→ `LoadConfig` 对正值 cfg `TimeMax` 覆盖 XML → runtime `TERMINATE`（在 SaveData 后且仅非 multi-GPU 分支直接改 `TimeMax`）→ minimum-fluid stop 可能把 `TimeMax` 缩到当前已完成步**。`NstepsBreak` 是独立的按步停止，不改 `TimeMax`。

这不是 R008 某次 solver invocation 的最终配置证据：没有实际 argv、OPT 文件快照、cwd、OPT 文件 inode/hash 或最终 binary/source binding 与执行 attempt 相连。

## 静态解析语义

- `JCfgRunBase::LoadArgv()` 按 argv 顺序解析输入，最多 100 个配置 token；`-OPT file` 被 `JSphCfgRun::LoadOpts()` 在当前位置立即递归展开。
- `LoadFile()` 以当前进程工作目录调用 `ifstream.open(fname)`，逐空白读取 token，单文件最多 50 项；不会相对 parent OPT 目录解析，也不建立文件摘要/manifest。
- `LoadOpts()` 限制递归层级小于 10。进入 `-OPT` 后完成该文件的递归处理，再继续父 token stream。`-TMAX:x` 每遇一次即赋给 `TimeMax`，所以 expanded depth-first stream 中最后一次赋值有效；命令行位于外层 OPT 前后会改变覆盖顺序。
- `-TMAX` 拒绝负值，但允许零；后续 `JSph::LoadConfig()` 仅在 `cfg->TimeMax>0` 时覆盖 case XML，因此最终 cfg 值为零不会覆盖 XML。
- `JSph::LoadConfig()` 先从生成/输入 XML 的 `TimeMax` 读取值，再应用正值 cfg override。运行中 `TERMINATE` 与早停还会继续改变 effective horizon。

源码锚点：`JCfgRunBase.cpp:65-103`（argv 顺序与限制）、`:109-131`（OPT 文件读取/限制）、`JSphCfgRun.cpp:312-316`（最大递归深度）、`:486-489`（`TMAX` 赋值）、`:523`（递归点）、`JSph.cpp:786`（XML `TimeMax`）与 `:961-965`（cfg override）。

## 合同要求与缺口

生产 `configuration_audit` 不能只记录最终一个 `TimeMax`。至少需要绑定原始 argv 字节序列及其分词结果、cwd 身份、每个 OPT 打开时的路径解析结果/descriptor/file bytes/hash、递归展开后的 token stream、所有出现过的 TMAX 及最终赋值来源，并在 solver `exec` 前后检查无 TOCTOU 变化。禁止未登记的 OPT 子文件、环境注入、同名替换或隐式 cwd 变化。之后还要将这些输入与 XML `TimeMax`、运行时 `TERMINATE` journal、source/build/features、实际每个 accinput 查询事件绑定。

本静态审计没有实现 parser、读取任何 solver attempt OPT 或启动 solver。TMAX 最终 overlay 的实际真实性仍 open；R008 `control_no_extrapolation` 不可判 pass，`T1_numerical=false`、资格信用 0。

源码 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `src/source/JCfgRunBase.cpp` | `cc0ffda27854411af2dc0e52e054df46ef95bb850e613146367748e6150a2362` |
| `src/source/JSphCfgRun.cpp` | `51b8dc214181edc0518e4c7de42a71b9248dee891064de3efb74aa8b095a2c96` |
