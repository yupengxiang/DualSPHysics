# Core 计划续推状态 UPDATE-113

日期：2026-09-25（Asia/Shanghai）

## 本次推进：planner 有界输入闭合与 legacy formal-train fail-closed

只读复核 UPDATE-112 时发现 bounded JSON reader 的两个可复现缺口：FIFO 在 `open()` 阻塞，且 planner 解析完一份 raw JSON 后会重新按路径计算引用摘要，文件被并发替换时可能出现“按 A 内容审计、却记录 B 摘要”，二次摘要读取也绕过 64 MiB 界限。本次修复：

- JSON 文件通过 `O_NONBLOCK | O_NOFOLLOW` 打开；不支持 no-follow 的平台 fail closed，读后仍核对同 FD 的 regular-file 类型、大小、字节数及 `(dev,inode,size,mtime_ns,ctime_ns)`。路径解析保留最终目录项，以便 `O_NOFOLLOW` 真正拒绝最终 symlink；FIFO 不会阻塞后续类型检查。
- path-backed manifest、evidence、profile、environment 和 referenced audit 的 SHA-256 来自传给 parser 的同一份 bounded raw bytes；不再二次打开输入路径。source-snapshot JSON 同样走 bounded reader。引用报告绑定消费到的字节摘要，即使读取完成后路径被替换也不会错配。
- `train_model()` 在读取 case/帧、计算 normalization、初始化模型/optimizer 前检查 reader 可见的 `formal_release=true` 声明。当前 V13 verified-reader capability 未实现，故旧 Mapping/path reader 立即拒绝 formal training；非 formal diagnostic training 保持原行为。CLI 与直接 Python API 共用此门。

回归覆盖 FIFO 非阻塞拒绝、symlink 拒绝、读后路径内容替换时 manifest 引用仍绑定已解析 bytes，以及 legacy formal reader 在任何 frame read/输出文件前拒绝。仓库 `.venv` 下 planner + admission-readiness suites **34 passed**，learning suite **47 passed**；`py_compile`、`git diff --check` 通过。没有读取生产 HDF5/one-shot，没有创建 formal specs、scheduler/worker 或训练任务。

## 复核边界与剩余工作

复核未发现当前公共 `inspect_inputs/build_plan` 路径能产生正向 formal admission：trusted-capability hold 仍固定存在，0 formal jobs/specs，launch false。私有 `_build_job()` 中遗留的 `launch_allowed_by_planner=true` 字段不能作为 admission capability 或独立授权凭证；当前公共路径不可达。该字段与未来 capability-only API 的关系仍应在正式 ingress 实现时审计。

本轮只补 strict-serialization/input-binding 与 legacy training ingress 防线，不实现 trusted root、producer/supervisor、descriptor snapshot/broker、fs-verity、same-FD HDF5 worker 或 source/build/runtime identity closure；不 mint capability，不改变 F8 T1/T2 或 Core T1/T2 信用。整体 PLAN 尚未完成。
