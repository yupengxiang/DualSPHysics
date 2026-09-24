# UPDATE-57：F8 R008 控制查询源码调用链静态复核

日期：2026-09-25（Asia/Shanghai）

只读复核标准 DualSPHysics `src/source`：accinput 从 active XML/MK range 进入 runtime `Inputs`，经 CPU/GPU `PreInteraction_Forces` 在当前 `TimeStep` 查询；Verlet 每步一次力预处理，Symplectic predictor/corrector 各一次，但都发生于 `TimeStep` 增量前。查询只在 `TimeIni<=TimeStep<=TimeEnd` 生效，control acceleration 与派生 velocity 都经 `JLinearValue::GetValue3d3d`；表端点外会 hold。

源码审计发现先前草案将完整 XML `[TimeIni,TimeEnd]` 当实际查询域过严：检查的 R008 Definition 不写 `<time>`，因此默认 `TimeEnd=DBL_MAX`；实际查询仍受每次循环 `TimeStep<TimeMax_effective` 约束。冻结示例的 `TimeMax=11.832052282049933`，CSV endpoint=`11.832052282049935`。合同应验证每个 runtime entry 的实际 active query 集与动态有效 horizon 的交集落在 table endpoints 内，而不是要求声明窗口自身有限。

仍未闭合：XML `TimeMax` 可被 `-TMAX`/OPT 覆盖，early stop / minimum fluid / `TERMINATE` 改变终态；`TERMINATE` 只在 SaveData 后轮询；multi-GPU 分支只设置未见读取点的 `TerminateTimeMax`；CPU/GPU 及 non-Newtonian 源码树没有绑定到 R008 binary/build/features/runtime event producer。新增详细[源码审计](F8-R008-CONTROL-QUERY-SOURCE-CALLGRAPH-AUDIT-2026-09-25.zh-CN.md)，不据此判 `control_no_extrapolation` pass；R008 `T1_numerical=false`、零信用。未改源码或运行 solver/worker/GPU/queue。
