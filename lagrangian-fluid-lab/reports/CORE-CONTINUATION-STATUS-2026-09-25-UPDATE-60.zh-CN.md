# UPDATE-60：F8 CLI、restart 与 `TERMINATE` startup namespace 静态审计

日期：2026-09-25（Asia/Shanghai）

只读追踪标准 `src/source` 启动链，补齐此前 C-execution review 提出的 `DsphConfig.xml`、完整 argv allowlist、`PARTBEGIN` 和实际 output namespace 语义。确认 `DsphConfig.xml` 位于 `argv[0]` canonical path 的父目录；CLI/OPT、case/restart/output 路径具有不同的解析根；`PARTBEGIN` 能导入多 piece restart state 与保存时间；CLI 有可覆盖求解器/边界/数值时间设置的 options，不能仅 allow 一条最终 `TimeMax`。

新发现的关键时序事实：CPU/GPU 单卡运行器在主 loop 前执行初始化 `SaveData()`，基础 `JSph::SaveData()` 随后轮询 `DirOut/TERMINATE`。所以运行开始前已有该文件时，就可能在首个积分之前把 `TimeMax` 缩到当前恢复/初始时刻；运行中写入也只能在后续保存点轮询。任何 R008 attempt 的 `TERMINATE` 初始缺席、目录 inode/命名空间和运行期间事件完整性都必须闭合。

详见[静态审计](F8-R008-CLI-RESTART-TERMINATE-STATIC-AUDIT-2026-09-25.zh-CN.md)。未运行测试或任何 solver/native/GenCase/worker/GPU/queue，未改代码、scope、阈值、分母、registry 或账本。R008 production execution gate 仍 open、`T1_numerical=false`、零资格信用。
