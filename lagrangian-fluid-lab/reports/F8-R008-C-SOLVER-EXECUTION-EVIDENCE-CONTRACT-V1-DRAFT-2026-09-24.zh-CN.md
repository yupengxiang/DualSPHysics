# F8 R008 C 阶段 solver-execution evidence contract v1（审查草案）

状态：草案，待 Terra High 只读设计复核。一次 reviewer 身份未 attested 的只读检查给出 `REVISE`；该结果不记作 Terra High。本文不冻结 schema、不改变 R008 范围，也不授权或启动 solver；现有 C v1 receipt/verifier 保持不变。

## 发现的源码事实

- `src/source/JLinearValue.cpp` 的 `GetValue3d3d()` 在输入时刻晚于最后一个控制采样点时返回末行值，即端点保持（零阶保持），而非报错。故“没有线性外推”不等价于“没有越过源表时间域”。
- `src/source/JDsAccInput.cpp` 的 accinput 时间窗默认是 `start=0, end=DBL_MAX`；窗外才关闭该项输入。冻结 XML 未显式将 `end` 绑定到控制 CSV 末端。因此即使 CSV 精确覆盖 `[0,T_end]`，若运行继续超过 `T_end`，solver 仍会保持最后一行控制值。
- solver 从 XML 读取 `TimeMax`，但命令行配置可覆盖 `TimeMax`、`TimeOut`/`TimeOutExtra`，并可用 `NstepsBreak` 在正常时限前结束（`JSphCfgRun.cpp`、`JSph.cpp`）。`-OPT <file>` 还会递归载入最多 10 层配置文件，故只检查顶层 argv 不足以排除隐藏 override。`TERMINATE` 文件在 CPU path 可运行时改写 `TimeMax`；当前源码对 GPU path 的处理不同，因此 solver 变体必须冻结，不能跨变体推断。
- CPU/GPU 主循环可能因 minimum-fluid 条件缩短 `TimeMax`；CPU/GPU finish path 将该情形记为 interrupted，但 `NstepsBreak` 路径并不把同一标志传给 finish routine。因此只查退出码、`Simulation finished` 字样或完整原生帧轴都不够。
- 当前 B generated-XML parser 只抽取/核对 `<particles>` cohort 与 raw initial BI4 身份，没有验证 GenCase 输出 XML 中 solver 实际读取的 `TimeMax`、`TimeOut` 或 `accinput` control reference。C verifier 只检查 raw manifest 与冻结预期轴及输出文件绑定；它未验证 `solver_execution` 内容。冻结 B Definition/control 源文件字节只能证明静态输入，不证明 GenCase 输出或 solver 实际读取了哪个 horizon/control。

## 候选闭合条件

未来 additive C-execution verifier 至少需把以下独立证据闭合后，才允许派生 `control_no_extrapolation=defined_pass`：

1. C 授权信封中 exact solver executable、wrapper、argv、输入绑定及资源限制由调用方信任门独立认证；receipt/sidecar 的每个值逐项匹配授权。输入须闭合到同一 B attempt 的完整 materialized tree、solver 实际读取的 generated XML 和控制 CSV，并以有界 parser 核对 generated XML 的 `TimeMax`、`TimeOut`、控制文件引用及相应源 hash；不能只校验 GenCase 前的 Definition/control。
2. solver-execution attestation 为一个有界、exact-field schema：单次 invocation；真实 child argv/可执行文件身份与授权相同；零退出码、无 signal/timeout；process tree 清洁；cgroup-v2 上限/峰值/events 与授权一致且无 OOM/压力事件。日志及 attestation sidecar 均须位于 C exact output manifest 内，记录 bytes/SHA 并由固定解析器读取。
3. 执行见证必须来自单独定义并经复核的可信 supervisor/measurement boundary，而非 receipt 中 executor 自报的布尔量。它至少绑定实际 `execve`、PID/process tree、cwd、environment、executable inode/hash、interpreter/dynamic-loaded code identity，以及 solver 实际打开的输入 inode/bytes/hash；从输入核验至 solver 打开期间须以只读不可变 snapshot/mount 或同等级机制消除 TOCTOU。若该信任根、测量源或 supervisor 不可用，gate 保持 `open`。
4. solver 的配置来源须完整展开并 hash-bind argv、所有递归 `OPT` 文件（最多 10 层），以及启用时的 `DsphConfig.xml`/相关外部配置；按 DualSPHysics 实际 parser 与覆盖顺序作规范化解析。采用严格的 reviewed allowlist，拒绝未知/重复选项、CPU/GPU 变体不符、`TMAX`/`TOUT`/`TOUTX`/`NSTEPS` 改写、`PARTBEGIN`/restart、未授权 case/output 路径覆盖（包括 `DIROUT`/`DIRDATAOUT`）。B generated XML 还须有界解析并核对 solver 实际读取的 `TimeMax`、`TimeOut`、`accinput` control reference；不能只验证 GenCase 前的 Definition/control。
5. 对固定且 source-to-binary 身份已闭合的 CPU/GPU solver variant，必须证明所有实际 external-control query 时刻满足 `0 <= t_query < effective_TimeMax <= T_end`。该结论应由 reviewed 调用路径（CPU `RunCpu` / GPU `RunGpu` 接收当前 `TimeStep`，主循环仅在 `TimeStep < TimeMax` 时进入）与已验证 effective horizon 推导；不能声称最终积分 `TimeStep` 必须精确等于 `T_end`，也不能以最后保存帧替代所有控制查询时刻的上界证明。
6. CPU path 的 `TERMINATE` “未发生”不能靠事后目录清单或日志中没有警告来推断；需要可信 supervisor 证明该名字在全过程中不能被未授权主体创建/改写/删除，或提供完备的 filesystem event 监控。事件丢失、缓冲区 overflow、监控缺口均 fail-closed。另须证明不是 minimum-fluid 提前停机、step-count break 或异常结束；普通零退出码与 `Simulation finished` 文本不足。完整逐帧 C→D 轴到冻结 endpoint 是必要条件而非充分条件。
7. B 的 control CSV 按冻结 tolerance 覆盖闭区间 `[0,T_end]`，起点为 0、末端与已验证 horizon 一致，采样轴单调且满足冻结 T/64 grid。执行记录还须证明一次调用、零退出码、无 signal/timeout、干净 process tree、cgroup cap/peak/events 与授权一致；日志/attestation 均在 C exact output manifest 内并由固定 parser 重验。任一输入/horizon/终止/资源证据缺失时 gate 为 `missing`/`open`，不得 pass。

## 尚待复核的问题

需要独立 reviewer 确认可信 supervisor/attestation 技术能否落地并封闭 execve/input TOCTOU；如何以有界观察证明所有 control query 时刻而非 final frame；CPU 输出目录 `TERMINATE` 的写者/事件监控完整性；solver log 的 horizon/early-stop parser；递归 `OPT` 与 `DsphConfig.xml` 的 exact grammar；以及 CPU/GPU binary-to-source provenance。若这些信任根/测量条件无法成立，合同应保持 gate open，而不是接受 executor 自报的布尔值。身份未 attested 的 reviewer 指出的这些为阻断级边界；Terra High review 尚未完成。

所有未来实现只用 temporary synthetic bundles/logs 测试；不读取 production solver frames，不调用 GenCase/native decoder/solver/worker/GPU/queue，不触碰 registry/ledger。Terra High 设计复核通过之前，草案不得作为执行 schema 或 gate adjudicator。
