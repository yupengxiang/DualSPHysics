# UPDATE-189：F3 model-material v2 RK4 首失败 stage 诊断

时间：2026-09-26（Asia/Shanghai）

## 发现与修复

复核 UPDATE-185 留下的闭壁 RK stage 失败边界时，确认 v3 RK4 的积分门要求 `k1`–`k4` 全部可靠；任一 stage 失败后位置保持原值且 tracer 永久进入 unknown。可是既有状态诊断只取 `k4.failure_reason`：若 `k1`/`k2`/`k3` 失败而 `k4` 恢复可靠，保存原因会错误显示 `reliable`。model-material v2 的 row serializer 还直接取 `k4` 原因，而不是状态中的首次失败原因。

在独立的 model-material v2 中增加 RK4 helper：保持原 stage 查询时刻、速度组合、位置更新、事件、永久 unknown 和 failure counter 语义不变；逐 seed 记录活动路径上最早不可靠的 RK stage 原因，已 unknown 的 seed 保留其既有首次原因。如果四个 stage 均通过但最终 candidate 非有限，则记录 `nonfinite_rk4_candidate`。trace row 改为序列化该状态原因。temporal-v3/v1 实现及历史收据未改写，正常可用轨迹的 dataset parity 继续由原测试验证。

## 验证与边界

- 新增合成测试覆盖 k1 失败而 k4 恢复、较晚 stage 失败不能覆盖更早原因、既有 unknown 原因保持不变，以及 trace row 写入状态原因。
- model-material v2、temporal-v3、v1 与 model-material comparison 四个相邻 suite：**23 passed**。另以完整合成 trace 验证 failure reason、永久 unknown 与冻结位置一并写入 HDF5。
- `py_compile` 与 `git diff --check` 通过。
- 仅合成输入；未打开生产 HDF5、未运行 GenCase/native decoder、solver、worker、GPU、queue 或训练，未写 registry/ledger，也不产生 T2 或资格信用。

## 仍未完成

UPDATE-185 提出的阶段性能剖析尚未进行；应先以合成数据分别测量 provider/frame 读取、MLS 重建、RK4 与 hash-chained HDF5 append 的成本，不据此直接修改资源上限或声称生产时长。真实材料运行仍需要新的 root resource decision 和独立 worker-launch authorization；row30 v5 one-shot 已消费，不能重试。全局 Core/T1/T2 目标仍未完成。
