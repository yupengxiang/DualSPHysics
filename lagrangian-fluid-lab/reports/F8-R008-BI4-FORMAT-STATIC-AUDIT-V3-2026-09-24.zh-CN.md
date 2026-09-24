# F8 R008 BI4 格式静态审计 v3（2026-09-24）

状态：保留 v1/v2 两次 `REVISE` 及其不可变回执；补充 pre-allocation 有界解析合同，待 Terra High v3 follow-up。机器回执：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v3/receipt.json`。审计/review 未运行 native binary、decoder、GenCase、solver、worker 或 queue；未编译程序。

## v2 finding 与具体修订

Terra High v2 follow-up 确认 v2 修复了回执完整比较和 decoder 路径逃逸授权边界，但指出不能在名称验证前调用 `LoadFile(..., true)`：该函数先分配全文件 buffer；如果恶意声明数量巨大，仍可能在任何 path guard 前造成资源耗尽。

v3 冻结强制顺序：

1. `openat`/`O_NOFOLLOW` 打开准确 raw BI4，验证 regular/single-link，基于同一 descriptor 绑定 SHA-256 与 pre/post `fstat` 身份。
2. 仅用固定小 buffer 检查 64-byte header、magic/filecode、byte order、R008 支持的非-si64 模式及 raw file 上限。
3. 有界流式 scan 同一 descriptor；在创建任何 tree/array/value 对象或 payload 前，验证递归深度、节点/数组/值数量、字符串/名称长度、type allowlist、乘法溢出、声明 payload 是否落在文件剩余区间，以及单数组与聚合上限、完整 EOF。
4. 校验完整 item/array name tree；此前不允许任何输出 filesystem mutation。
5. 通过后从同一稳定 input descriptor 第二遍流式解码，使用 held dirfd + `mkdirat/openat` + `O_NOFOLLOW/O_EXCL` 写入；逐项检查所有读写/flush/close 结果。
6. 最后核验完整 recursive XML-to-file manifest、全部 SHA/shape/dtype/byte size、no-follow、普通文件及 `st_nlink==1`。

R008 冻结初始总粒子数为 10,752，固定边界 4,096。按 JBinaryData 最大受支持固定元素宽度 24 B，单数组 payload 上限为 10,752×24=258,048 B；64 个数组的聚合上限为 16,515,072 B，低于 16 MiB。另冻结输入 BI4 最大 64 MiB、header 恰 64 B、最多 2 个 item 节点/深度 2、最多 64 个数组、每 item 最多 128 项 metadata、名称≤128 B、单 metadata 字符串≤4096 B、聚合 metadata≤2 MiB、每数组 count≤10,752、解码输出≤24 MiB、最多65个文件。unsupported text arrays、超过 R008 cohort 的数组、SI64 header、未知类型和越界都拒绝；若未来合法 frame 超限，需新审查提升合同，不能静默扩限。

上述限制来自已冻结的 R008 cohort 与官方 JBinaryData v5.4 的字段/size 编码。现有 `JBinaryData::LoadFile(memory=true)` 会先按全文件大小分配；`OpenFileStructure()` 虽不载入 array payload，仍会创建未受这些 R008 计数/深度/name caps 限制的元数据树，故两者均不能直接充当 adversarial preflight。下一阶段实现必须增加单独的 bounded streaming scanner，不能仅包装现有加载函数。

## 仍未完成

机器回执 v3 仅冻结合同，没有实现 scanner、安全输出 adapter 或运行时测试；旧 binary/build-source provenance 仍未闭合，也没有 R008 solver frame。v3 reviewer 未 PASS 前不进入 adapter 实现；之后实现仍需 Terra High 独立审查。无 decoder/GenCase/solver 执行授权；R008 保持 `readiness_pass=false`、零信用和无 T1 结果。
