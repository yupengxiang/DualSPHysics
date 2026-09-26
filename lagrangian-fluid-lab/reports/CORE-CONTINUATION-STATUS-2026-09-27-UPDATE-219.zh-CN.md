# UPDATE-219：F4 v5 CPU/native preflight 安全合同加固

时间：2026-09-27（Asia/Shanghai）

本轮仅准备并审查 F4 v5 的一次 CPU/native 输入与环境预检；用户授权不包含实际 canary、predictor、tracer、solver、GPU、worker、queue、T2 或资格登记。

首轮 Terra High 配置只读审查发现 P1：静态摘要校验前会导入候选模块，且授权/候选卡缺少固定信任锚；另发现 scope 目录替换可能隐藏目录内 one-shot lock。修订后预检入口不再导入任何项目候选模块；候选卡 SHA-256 固定为 `25acdfb39c98cf64293454e51237d91bf1ea91217020d7e15a547cefedaca653`，静态验证先校验该摘要，再校验 22 项候选输入和合计 25 项授权闭包。授权 schema、source identity、执行范围、禁止项和绑定字段均精确闭合。

one-shot 消费标记写入 `/home/jade/.local` 中 owner-only 的固定文件，要求状态目录由当前 UID 所有且无 group/other 权限；使用 no-follow/exclusive 创建并 fsync。scope 仍写入 lock/receipt。运行前、源访问前后均复核私有状态目录、scope 与输出父目录的 device/inode；测试覆盖 scope/state 替换，确保 source probe 不会越过路径变化。安全结论采用单用户本地信任模型：不声称抵御同 UID 恶意进程修改运行中代码或替换自身可写状态，也不依赖 root/sudo。

先前发现 P1/P2 的 Terra High 配置复核后续审查确认：在上述信任边界内无 P0–P2 阻断；仅保留同 UID 主动篡改与本地 Python 依赖信任为范围外限制。配置为 `gpt-5.6-terra` / high；reviewer 身份未 attested。审查未执行测试、预检、候选模块，也未访问生产 HDF5/BI4。

验证：专项测试 **14 passed**；脚本和测试 `py_compile` 通过；`git diff --check` 通过。候选卡 22 项输入、授权 JSON 25 项静态闭包匹配。上述测试仅用临时目录模拟资源与路径变化。

截至本记录的资源快照，1/5/15 分钟 load 为 `136.29/131.43/128.53`，高于 128 个 process-visible CPU 的 1 分钟门限；可用 RAM 为 `226,242,666,496` bytes，文件系统可用空间为 `8,169,333,694,464` bytes，未发现 F3/F4 材料 worker。故未启动预检。用户私有 one-shot 标记、scope lock、preflight receipt 均不存在；未哈希或打开生产 trajectory HDF5，未启动任何 workload，资格/credit/registry/ledger 均未改变。只有在实时负载门通过时才继续这次已授权的预检；若不通过则在 durable marker 前 defer，不消费 one-shot。
