# Core 计划续推状态 UPDATE-97

日期：2026-09-25（Asia/Shanghai）

## 本次推进：F8 R008 synthetic-only 合同复核与修订

围绕 UPDATE-96 的审查结论，完成 V13 control harness、C-execution V5 与 per-case bundle verifier V2 三份**设计草案**的交叉修订。GPT 6 Luna Max 做了首轮与多次 focused follow-up 只读复核；首轮总体为 `REVISE`，最后一轮确认新增的 V2 process-root/ref/seq 偏序及 V5 无 `poll_end` cache 规则在文本层面闭合，未发现该窄范围残余 P1/P2。V13 的 vector 和类型规则也已明确。该文本结论不覆盖实现，也不认证 supervisor/runtime trust。

- V5：统一 journal 顺序、绑定 invocation/root 与当前 solver image；`poll_begin/poll_end` 区分返回、异常和中断；缓存按源码的单槽生命周期重放，正常成功还要求每个参与 driver loop 有且仅有一个终止 false guard。exception 或无 terminal end 的查询都不能成为同时间 cache hit 的有效值来源，attempt 保持 nonpassing/open。
- V13：资格 admission 对象分离 raw/canonical digest，加入 exact serialization golden vector；HDF5 通过同一 fs-verity snapshot FD 计算大小/hash、broker/worker 传递与消费，并逐项绑定 device/inode/mount/verity measurement；`hdf5_size_bytes` 排除 bool。旧 Mapping/path 与 `CoreDataset.formal_eligible` 被限定为 diagnostic，正式入口必须 fail closed。
- Per-case V2：定义 attempt result、15-row aggregate 与 append-only ledger exact schema；阶段 refs、case/attempt ID、nonce、ledger event seq 及 C V5 invocation/root 做交叉绑定；ledger 缺少受信完整性证明时不得推导 `missing`；保留所有 retry/failure history，并把 accounting completeness 与 qualification success 分开；明确未来 T1 正向谓词及 frozen failure-denominator/retry 约束。

## 未闭合项与状态边界

这些文本不是实现、执行证据或资格结果。当前正式 consumer 尚未实现 V13 capability-only API；`core_dataset.py` 仍有 Mapping/path 与二次 pathname open 路径，F4 connector 仍有普通 Mapping 和 preparation ingress。trusted root/supervisor、out-of-band key activation、完整 event source、loaded-runtime/source closure、V5/per-case parser 与 F8 T1 producer 仍缺失。文档约束不代表旧入口已被封闭，后续实现与独立审查仍是阻塞。

R008 `readiness_pass=false`、`T1_numerical=false`、资格信用为零；没有生成 15-case T1 结果。F3 row30 与 F4 supportcap 已消费的一次性预检未重试；没有启动 worker、solver、GPU 或 queue，也未读 `campaigns/.../f8...r008` 生产 bundle/solver-frame/one-shot 材料。

本轮只做文档变更和 `git diff --check` / staged diff check；未运行 pytest、planner、collector、preparation、GenCase、native decoder 或任何执行链。为固定 V13 文本中的 SHA-256 golden vector，做了一次无文件 I/O 的 Python 3 内存哈希计算；它不是仓库测试或 producer 实现。独立 reviewer 没有重算该 digest；该数值仅由本会话的内存计算给出。UPDATE-97 与 PLAN 历史记录记录的是本次静态设计推进，计划中的实现、独立代码审查与 R008 T1 仍未完成。
