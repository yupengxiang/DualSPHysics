# UPDATE-188：F4 局部仿射重建候选与一次性 CPU/native 预检

时间：2026-09-26（Asia/Shanghai）

## 新候选及静态证据

新增 proposal-only 候选 `f4_supportcap_local_affine_reconstruction_v4`：仍用可见邻域 k=32、Shepard 距离权重、`0.004 m` 正则项和 `0.03 m` 最大支持距离；唯一预测器变化是由加权局部仿射最小二乘在 query 处直接预测速度。有效样本数、几何秩、各向异性、重建残差与 affine-versus-Shepard disagreement 组成的 gate 公式和固定阈值与 v3 相同；所有 512 个源 seed 仍留在分母，right-censor 仍计 unknown。该算法仅是 array-only proposal，未接入正式 tracer。

对两个既有 held-out 解析场、`q={0.375,0.875}`、source/interface/destination 共 **5,632 个 query**做 CPU 合成筛查：v3 与 v4 的 gate 判定完全一致，均为 **5,632/5,632 pass**；这些点的 v4 真值误差最大为 `0.0386506 m/s`，低于固定 `0.0469814 m/s` 上限。场族之间存在明显 tradeoff：quintic shear RMSE 从 `0.0009615` 降至 `0.0004658 m/s`；Gaussian interface RMSE 从 `0.0028313` 升至 `0.0082449 m/s`，界面区最差点 `0.0386506 m/s`。这是有限制造场上的筛查，不证明 native 轨迹/事件成功，也不证明仿射法普遍更好。回执：[synthetic calibration](../campaigns/core-v1/material/evidence/f4-supportcap-local-affine-reconstruction-v4-synthetic-calibration-v1.json)；候选契约：[candidate card](../campaigns/core-v1/material/candidates/f4-supportcap-local-affine-reconstruction-v4/candidate-card-v1.json)。

R001 的失败仍归因为“t=0 seed 与较晚 frame 40 空间不匹配”的强支持证据；v4 不声称修复该 setup 错误。绑定的 R002 时间对齐配方要求 row 0 起步，推进至 row 40 后评估 40→41，但旧 v3 的 R002 preflight one-shot 已消费，不复用也不重试。

## 新候选 CPU/native 预检

按用户授权的唯一一次 F4 新候选 CPU/native preflight 执行；18 个静态输入哈希在执行前闭合，候选/预检专项 **15 passed**。结果为 `preflight_deferred_resource_gate_runtime_not_authorized`，阻塞项只有 1 分钟系统 load 高于本任务可用 CPU 数：`173.876 > 128`。RAM `223,478,771,712 bytes`、可用磁盘 `8,173,253,656,576 bytes` 均过门；没有活动 F3/F4 material worker。不可变 one-shot lock 与 receipt 位于 `campaigns/core-v1/material/candidates/f4-supportcap-local-affine-reconstruction-v4/cpu-native-preflight-v1/`。receipt 中 `input_preflight=null`：资源门短路，所以该 attempt 没有打开 HDF5 或读时间轴/粒子帧。预检只留下环境快照，不授权 runtime；同 scope retry 明确禁止。

证据边界：静态绑定准备时曾对 10,326,356,548-byte 源文件执行一次只读 `sha256sum`，得到既有绑定摘要 `91846866…7c096e`；这是文件字节流校验，不是 HDF5 dataset 打开或 native 帧读取。该读取发生在正式预检资源门之前，故单独如实记载，不把它归入本次 receipt 的 `input_preflight`。正式 one-shot receipt 仍是资源门 deferred；没有再 hash/open 源文件。

没有运行 v4 候选、tracer、material canary、solver、GPU 或 worker；没有队列、registry、ledger、T2 或资格写入。R001/R002 历史产物未改，T1/T2=false、资格 credit=0。该 one-shot 已消费，不得以同 scope 重试；进一步 CPU/native preflight 需要新的授权/独立 scope。没有调用 subagent，因此本报告不声称 Terra High 独立 reviewer verdict。
