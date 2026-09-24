# Core continuation status — UPDATE-92

日期：2026-09-25

## F4 material preflight 静态复核

只读检查 `f4_tallwall120_material_preflight_v1.inspect_source()` 调用顺序：普通 JSON `read_json()` 载入多份输入后，先由 `_archive_trajectory_sha()` 读取 archive outputs，再验证 archive schema；audit/result pass markers 和 completion `scope_studies[].T1_numerical` 会在相应 completion schema gate 前被访问；range-root 则直接读取 `T1_numerical`/`matrix_complete`，代码没有定义或验证其 exact schema。随后函数会打开固定的终端 trajectory HDF5。

## 处置与边界

- 未调用 `inspect_source()` 或对应会碰固定路径/HDF5 的测试；未读 preflight receipt/one-shot authorization，也未打开大型 HDF5。
- 本轮无代码变更、无 pytest；这是一个仍 BLOCKED 的 V9 consumer。因 range-root schema/source producer 尚未定义、缺 trusted raw-byte/root capability，不能凭猜测增加 schema 接纳规则；该 preflight generator 属历史单次链，不重写、不重跑。
- completion/archive/audit 的前置 schema 次序、range-root capability、duplicate-key/raw-byte 解析和 runtime/source identity 均未闭合；F4 T1/T2 与既有授权状态不变。Terra High/high 外部复核因 agent thread limit 未启动，不记 PASS。
