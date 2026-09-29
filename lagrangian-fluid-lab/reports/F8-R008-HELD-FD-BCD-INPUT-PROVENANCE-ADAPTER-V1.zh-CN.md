# F8/R008 held-FD B/C/D 输入层 provenance adapter v1

本闭环补的是 `800ca22a` 之后仍缺失的输入层边界：它不做
solver-output→Core projection，而是只接收 caller 已经持有的 FD 和无路径
canonical descriptor，对 synthetic B/C/D receipt、manifest、C raw frame、D
decoded frame 做逐 FD 重算与交叉绑定。

实现固定使用 `fstat + pread`，不接受 pathname 字段，也不调用 pathname
re-open；每个 FD 必须是 bounded regular single-link file，所有 artifact 的
`(dev, ino)` 必须互不别名。B→C→D 的 `case_id`、`attempt_id`、`nonce`、
`source_sha256`、upstream receipt digest、binary64 time axis、raw frame digest
和 decoded frame digest 均必须闭合。symlink FD、hardlink、FD identity/size/bytes
变化及任何 source/attempt/case/time/frame digest drift 都 fail-closed。

专项 synthetic fixture 测试覆盖合法 B/C/D 链、pathname claim、8 类 identity/
digest drift、实际 frame bytes drift、hardlink 与 no-follow symlink FD。成功结果
只表示 diagnostic provenance bound：`diagnostic_only=true`、`readiness=false`、
`T1_numerical=false`、`qualification_credit=0`；不认证 producer、authority、
runtime、native integrity、terminal observation 或生产 bundle/HDF5/BI4。

本轮没有读取 production bundle/HDF5，没有运行 GenCase/native/solver/worker/GPU/
queue/特权 probe，也没有修改 PLAN、registry、ledger、denominator、gate、
completion 或历史 receipt。
