# Core continuation status — 2026-09-24 UPDATE-34

## Outcome

新增 F8 R008 native-fluid-table v2 的单案例指标适配器与 B/C/D 持有描述符编排层。既有 v1 table reader/verifier 未修改；v2 指标消费不再重开表路径，也不调用 v1 中绑定 GenCase 回执的高层 reader/evaluator。

- `scripts/f8_r008_t1_metric_adapter_v2.py` 在 table-v2 语义验证完成后，从同一只读 D-table FD 读取完整时间轴、fluid ID、初始 z、经上游验证为不变的质量，以及闭合观测窗中的速度行；先验 verifier 对 density、valid 和所有 raw frame 的验证是强制条件。
- `scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py` 复核 B/C/D 与冻结 Definition/control/参数来源，持有 single-link 表 FD，执行语义验证和指标计算，再重闭合 B/C/D；末尾以 no-follow 安全打开 D 表路径，检查其仍指向开始时的同一 inode、保持 single-link，且 SHA-256 未变。
- 编排层严格校验 metric 返回合同，包括 frozen native time grid、profile planes、Uref、所有 gate 数值及布尔结果；不接受 solver timestep、native-integrity、T1 或资格信用声明。v2 helper 依赖也绑定到源码 SHA，并在使用前验证既有 v1 Terra High 不可变 review receipt。
- 指标只覆盖单案例的固定频率谐波系数、三周期共享 seam 通量、横向速度 RMS 与冻结阈值；此实现不是 15-case adjudicator。

## 独立审查与验证

Terra High（`gpt-5.6-terra`, high；agent `01a0d2ed-c88b-76c0-9ec5-38077fa80a7a`）经两轮 `REVISE` 修订后，对最终 held-FD v2 实现只读复核为 `PASS`。不可变机器回执：`campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-review-v2/receipt.json`。回执绑定 v2 编排器、适配器、复用的 v1 helper 源码及测试哈希。

最终定向 synthetic-only suite 由父代理与 Terra High 各运行一次，均为 14 passed；既有 v1 metric/table、B/C/D 和 review/archive 回归为 68 passed。`py_compile` 与 `git diff --check` 通过。

## 明确边界与剩余工作

仅用临时合成 HDF5、BI4 与 B/C/D bundle。未读取生产 bundle 或 solver frame；未运行 GenCase/native decoder/solver/worker/GPU/queue；没有 registry/ledger 写入。

这不是正式资格：`native_integrity_evaluated=false`、`readiness_pass=false`、`T1_numerical=false`、qualification credit 为 0。尚缺可接入真实 C 原始帧的独立 v2 table producer、15-case / 8 项空间比较及 timestep/cadence matrix adjudicator、solver timestep audit 和 native-integrity gates；生产 solver frames 也尚不存在于本次范围。调用方授权/审查真实性与运行时 loaded-module 身份不由该实现认证，输出会明确标示相应边界。
