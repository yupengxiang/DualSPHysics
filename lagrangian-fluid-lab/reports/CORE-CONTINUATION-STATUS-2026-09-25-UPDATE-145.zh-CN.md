# Core 计划续推状态 UPDATE-145

## Formal planner 的 plan/launch authority 分离

修复 `core_formal_planner` 的执行权声明不一致：公共 `build_plan()` 当前因缺少可信 admission capability 而固定 hold，但私有 `_build_job()` 仍输出 `launch_allowed_by_planner=true`，且顶层 `launch_allowed` 原先会随着 jobs 变为 true。现在顶层单独输出 `plan_ready`，`launch_allowed` 无条件为 false；job spec 也将 `launch_allowed_by_planner` 与 `launch_allowed` 固定为 false。planner 只描述可准备的工作，不能授予执行权，执行须经过独立可信 broker。

新增合成回归覆盖三条路径：完整但普通 Mapping/path 输入仍 hold、私有 job spec 不自授权、以及用 stubbed audit 仅测试 ready 序列化时 `plan_ready=true` 仍与 `launch_allowed=false` 分离。ready-path fixture 设 `write_specs=false`，没有写 job 文件或调用 scheduler/worker。当前 source-closure 计算值随 planner 更新为 `7bbde553fae61f72c7a0744129a138eb797640aa54c15223148aa6c207e091e7`；测试基线随之更新，历史 source-closure receipts 未改写。

相关 planner、admission readiness、launch contract、source-closure audit/admission 回归 **52 passed**；`py_compile` 与 `git diff --check` 通过。此次没有创建可信 root/capability、没有改变永久 diagnostic hold，也未启动 training/GPU/queue；T1/T2 资格与 Core completion 状态不变。
