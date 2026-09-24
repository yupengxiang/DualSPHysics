# F8 R008 BI4 格式静态审计 v2（2026-09-24）

状态：保留 v1 的 `REVISE` 历史，并补入完整回执比较与 decoder 写路径安全门；本 v2 follow-up 待 Terra High 复核。机器回执：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/bi4-format-static-audit-v2/receipt.json`。审计与 Terra High review 未调用任何 native binary、decoder、GenCase、solver、worker 或 queue；审计单测只读取固定静态证据并在临时目录运行。

## v1 审查发现与处理

Terra High 对 v1 的结论为 `REVISE`：

1. v1 `verify_receipt()` 只比较了一部分 JSON；合同和 readiness 字段被篡改时仍可能返回通过。v1 原文件/回执保留，不回写。v2 `verify_receipt()` 改为与完整 canonical `build_receipt()` payload 作等值比较，并以负例测试覆盖 type-size、predecode gate、readiness、filesystem-policy 的篡改。
2. `bi4_dump.cpp` 将 BI4 文件内的 item/array 名直接拼接到 `mkdir`/文件路径，且未检查 stream 错误。恶意名称可能造成目标命名空间之外写入；事后 manifest 只能发现，不能阻止或撤销。**因此不得把当前 `bi4_dump` 用于任何新输入的解码。**

## 新增 predecode 安全门

任何 future decoder adapter 在首次文件系统写入前，必须先验证完整递归 item/array 名树；拒绝空名、`.`/`..`、分隔符、绝对/控制字符、超长和重复名。输出需在 approved parent 下 exclusive-create；每层以 held dirfd 配合 `openat`/`mkdirat`、`O_NOFOLLOW`、`O_EXCL` 创建；检查 regular file、`st_nlink==1`、资源尺寸/数量上限，以及 mkdir/open/write/flush/close 的每个返回值。之后仍需逐 BI4 输入的 XML-to-file exact recursive manifest、hash、dtype/count/byte-size 与原始输出对应验证。只有独立审查通过的安全 decoder 源码/构建，以及调用时绑定的 executable hash/build identity，才能进入未来资源/执行准入。

已经由 v1 静态源码/初态产物支持的 endian、元素类型宽度、metadata 与数组基本写入格式结论保持不变；R008 solver 帧完整数组集合仍未观察。历史 binary build-source linkage 仍 open。opaque hash pin 只能辨认 binary，不能使路径不安全的现有 decoder 变安全，也不能补造历史 invocation provenance。

## 边界

本 v2 只推进静态合同。没有编译/修复/运行 decoder，不重试 GenCase，不启动 solver/worker/GPU/queue。R008 仍 `readiness_pass=false`、零资格信用且无 solver 执行权限；T1 与 per-case provenance verifier 均未完成。
