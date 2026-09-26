# UPDATE-179：F8 R008 终止时刻与 CPU 末帧输出路径审计

时间：2026-09-26（Asia/Shanghai）

## 冻结输入的输出格点核对

对 `definition-control-pack-v1/receipt.json`（SHA-256 `d5b657db398e0c0b102cdb84de8fe0a302c22c85d4bbf16bc0b6e6bf16065fcb`）所列 15 份 qualification Definition 逐一重算 SHA-256 并解析 `TimeMax`、`TimeOut`。15 份文件摘要均匹配 receipt，按 receipt 预测的 native row count 也都等于舍入 tick `k+1`。以 binary64 运算比较 `TimeMax` 与源码调度表达式 `k*TimeOut`：

| Qualification 组 | tick k | 数量 | binary64 端点关系 |
|---|---:|---:|---|
| spatial q=0 | 320 | 3 | 完全相等 |
| spatial q=0.5 | 702 | 3 | 完全相等 |
| spatial q=1 | 1496 | 3 | 完全相等 |
| internal q=0.25 | 442 | 2 | `TimeMax` 晚 1 ULP（`+1.7763568394002505e-15 s`） |
| internal q=0.75 | 1053 | 2 | `TimeMax` 早 1 ULP（`-1.7763568394002505e-15 s`） |
| time q=0.5 | 702 | 1 | 完全相等 |
| cadence q=0.5，T/128 | 1404 | 1 | 完全相等 |

15 份 XML 均未配置 `execution.special.timeout`，也没有 solver 保存模式键；调度因此使用普通 `TimeOut` 格点。receipt 的 row-count 合同将每个端点按整数 tick 计入，但 `internal-q0p75` 的最后计划 tick 在 `TimeMax` 之后 1 ULP。数值差远小于正常流体时间步，但本轮不以“正常时间步必定跨过”代替执行证据。

## 当前 CPU 源码的端点保存语义

在本地 v5.4.355 CPU 源码中：

- `JSphCpuSingle::Run` 初始化时写 PART 0；循环条件为 `TimeStep < TimeMax`。每步先将 `TimeStep += stepdt`，只有 `TimeStep >= TimePartNext` 或 `minfluidstopped` 时才调用 `SaveData`，随后以当前实际 `TimeStep` 计算下一个输出时刻（`JSphCpuSingle.cpp:1171–1230`）。
- `JDsOutputTime` 的普通模式从 `n*TimeOut` 推进，并返回严格大于当前时间的下一格点；配置 XML 没有 special timeout 时由 `TimeOut` 建立该模式（`JDsOutputTime.cpp:76–101,165–204`）。
- `JSphCpu::DtVariable` 计算 CFL/物理步长并可用 `FixedDt` 替换，但该函数不把时间步截断到 `TimeMax` 或 `TimePartNext`（`:2035–2077`）。因此输出帧记录的是越过预定格点后的实际 solver 时间，不是插值回格点的状态。
- CPU `FinishRun` 输出 summary，并在 Info 模式写 `RunPARTs.csv` footer；它没有无条件调用 `SaveData`（`JSphCpuSingle.cpp:1329–1342`）。每次 `SaveData` 才会调用 `DataBi4->SaveFilePart()`/`SaveFileInfo()`。这意味着静态源码不能单独证明正常结束时最后一个格点已被越过并持久写入。
- XML 没有锁定 solver CLI 保存开关。`JSphCfgRun` 默认开启 Binx/Info、关闭 VTK/CSV，但 `-sv:none` 等命令行选项可改变它；未来 invocation 必须绑定实际命令及输出模式（`JSphCfgRun.cpp:75–80,441–450`；`JSph.cpp:576–583`）。

上述是调用路径静态证据，不是任何一次 solver run 的完成或落盘证据。尤其对于 `internal-q0p75` 两例，必须从实际 run 证明正常走到 `TimeMax` 后，最后一次实际时间步也满足末计划 `TimePartNext`，且最终 native PART 存在、时间/人口/身份与 manifest 及矩阵合同一致。否则不能由 `RunPARTs` footer、预测 row count 或 receipt 中的 `TimeMax` 声明补足。

源码哈希绑定：`JSphCpuSingle.cpp` `a261620354e4970f99e8314ddfede1349acef5de236af32e9921af324c021608`；`JSph.cpp` `206e4486a3a0d304e02da1a73d2e7c7ed96354d559ce481275d09f5245b8c9e7`；`JDsOutputTime.cpp` `a68c0a17b96d328415580b18ecbda34f64a3e4f04d0700f42de9b9084d5d7b17`；`JSphCpu.cpp` `7c7c01b3a5e6809b8f6f5129f30c8aac0a4b35f1bff2e1776af4a11e8442a617`；`JSphCfgRun.cpp` `51b8dc214181edc0518e4c7de42a71b9248dee891064de3efb74aa8b095a2c96`；`JPartDataBi4.cpp` `5aeb4f25c173aabe1fca4de8b253ade789be1ba3db1f2e0eb9fa57fb67c6a544`；`JBinaryData.cpp` `29b39fe132795fe941d83c7ade8a842d2b47da281a3dc7855003c2ddb2f899e1`；`main.cpp` `43ce552b8177dad089148f7f552bc44f9467220eb0da6503964f6bfd6c888b4c`（含 v5.4.355 版本标记）。

## 状态与边界

这是冻结输入和 CPU 源码的静态核验；没有改写 Definition/receipt，没有运行 GenCase、solver、worker、GPU 或队列，也没有创建正式 admission。R008 的 solver 执行、正常终止、native end-frame 持久性与 T1 仍未验证；readiness/资格信用不变。

## 结论

输入窗的整数 tick 与既有 row-count 预测整体相容，但 4/15 个端点在 binary64 层面并非完全相等，且 CPU 完成函数没有强制末帧写出。后续实际执行合同需验证末计划输出 tick 是否被越过以及末帧真实落盘；当前不能把静态“按计划应写”升级为 T_end/final-flush PASS。
