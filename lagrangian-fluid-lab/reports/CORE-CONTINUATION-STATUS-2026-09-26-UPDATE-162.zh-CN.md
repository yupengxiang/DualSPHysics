# UPDATE-162：F8 R008 post-run 单案例桥接与 split/发布安全修正

时间：2026-09-26（Asia/Shanghai）

## 本轮实现

新增 `scripts/f8_r008_postrun_case_worker_v1.py`，将现有 B/C/D + metric v2 verifier 与 Core trajectory adapter 串成单案例、纯 post-run 流程。它只接受冻结 R008 qualification case ID 和精确 B/C/D roots；轨迹物化前后都完整复核 v2 链，绑定前后 receipt/manifest 摘要、D table bytes/SHA 与 case metrics，并从 held D-table FD 和经校验的 C raw frames 构建 Core HDF5。函数不启动 solver/worker/scheduler，也不写正式 receipt、registry、ledger 或分母。

审查发现 qualification HDF5 可能被仅改 manifest 的 split 重标进入训练。`core_dataset.py` 现在在首次打开和复用缓存 HDF5 handle 时核对文件内 `split` 属性与 manifest 行；F8 qualification 轨迹因此不能只靠改 manifest 行进入 `training_transition`。属性缺失的旧 HDF5 仍按兼容路径处理；本轮 F8 adapter 强制写出 `split="qualification"`。

审查还发现按路径 `stat` 后 `unlink` 的竞态，以及临时源文件名在发布前可被替换。trajectory adapter 已改为匿名 `O_TMPFILE` inode：在同一 held FD 上完成写入和复验，通过 `/proc/self/fd/<fd>` 只读重开核对同一 inode，再由 `linkat(..., AT_SYMLINK_FOLLOW)` 直接从该 FD 原子 no-replace 发布；不再创建临时源文件名，也没有失败路径按名删除。目标名在预检后被并发创建时，内核拒绝覆盖。未安装 O_TMPFILE、procfs FD 重开或 FD-link 发布能力时 fail-closed，不降级为 pathname 写入。

失败语义：发布前失败时匿名 inode 在 FD 关闭后消失；发布后若最终复核/目录同步失败，函数抛错但保留最终文件供核查。调用方不能把此类异常直接当成“未发布”重试，必须先检查固定输出名。CoreDataset 的属性缺失兼容仍不是对所有历史 HDF5 的通用 split 保证。

## 独立审查与验证

- GPT-6 Luna Max 只读 follow-up **PASS**，无 P0–P2。其残余 P3 为：旧格式缺少 HDF5 split 属性时仍允许 manifest split；以及发布后异常保留文件，调用方需先检查再重试。该审查无密码学模型身份 attestation。
- 最终目标合成回归：adapter、post-run bridge、CoreDataset compact 三个 suite，**17 passed**；`py_compile` 与 `git diff --check` 通过。
- 本机临时目录 syscall 探测确认无 sudo 时 O_TMPFILE + proc-fd `linkat` 可用。用法符合 Linux man-pages 的 [open(2)](https://www.man7.org/linux/man-pages/man2/open.2.html) 与 [link(2)](https://man7.org/linux/man-pages/man2/link.2.html) 说明。
- 仅使用 `tmp_path` synthetic B/C/D、HDF5 和文件名竞态；未读取生产输入或运行 GenCase、native decoder、solver、worker、GPU、queue；未改变 qualification credit（仍为 0）。

关键 SHA-256：

- `scripts/core_dataset.py`：`62161e913cfbdd14af96705d36b370616022485cf10b8f8b5851931ae62977a7`
- `scripts/f8_r008_core_trajectory_adapter_v1.py`：`8beaf9f40ef717a64942909f6bef04039ac174ee3a7700c6200ab6d08dbd987a`
- `scripts/f8_r008_postrun_case_worker_v1.py`：`420a3af2ba14a1dc014a304792346deeab4957aee40e0913e68cf9743a32ad97`
- `tests/test_f8_r008_core_trajectory_adapter_v1.py`：`9b51811596c26d45f877fb367002628e7eb35c8e48d9137ba5e89ae34c34d89f`
- `tests/test_f8_r008_postrun_case_worker_v1.py`：`93aa506fb3c511ce7124d568ae39f111f984eb4b2a14c1c7f0fd290a899329eb`

## 总体计划状态

只读 `core_campaign.py status` 仍为 `can_finalize=false`：T1 家族 F3/F4 为 2/3，宏观 T2 为 0/2，正式训练为 0/9；固定 T1 目标分母缺 432（其中 144 尚未登记），材料分母缺 288；独立复现仍未通过。因果谱系和证据结构检查为 true，`issues=[]`，不表示目标完成。

修改 `core_dataset.py` 后，引用其旧哈希的 formal source-closure / readiness 快照不再覆盖当前代码；本轮未重写或注册这些快照。正式训练继续保持 fail-closed，需在后续 source-closure 审计中更新并复核后才能申请正式执行。F8 readiness v6、R008 真实来源验证的 15-case 结果、native integrity/完成与有效 timestep 裁定仍未完成；本轮不改变 T1/T2、readiness 或资格信用。
