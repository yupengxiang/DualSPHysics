# F3 material 原生 cadence 防插值冒充审计（2026-09-24）

## 结论

材料参考对齐器此前允许把 `.01 s` 的稀疏 CFD 源状态插值到 `.002 s` 的 `NP04-cadence-s4` 目标网格。这只会产生插值帧，不是计划要求的加密原生输出，因而不能作为 cadence 对照证据。现已在 `align_source` 加入 fail-closed 守卫：目标间隔不得小于来源登记的原生输出间隔；违规时在创建临时 HDF5 前拒绝。

来源间隔不是单独采信配置值：对齐仍须通过 `CachedSource` 的 HDF5 时间轴检查，包括完整帧数、时间范围、相对登记 `output_interval_s` 的网格偏差、积分步长容差和时间步日志覆盖。对齐回执同时记录 `source_native_output_interval_s`、目标间隔和 `no_synthetic_upsampling=true`，并保留逐帧 native bracket/alpha。

## 验证

- `.01 s` 原生 fixture 请求 `.002 s` 对齐：按预期拒绝；目标文件与 `.partial` 文件均未创建。
- `.002 s` 原生 fixture 请求 `.002 s` 对齐：通过，完整 4,176 帧；`.01 s` 同 cadence 对齐原有测试仍通过。
- `tests/test_f3_material_reference.py`：28 passed。
- 关联的 T2 readiness v1/v2/v3、material-neighbor、manufactured tests：44 passed。
- `git diff --check`：通过。

以上都是合成输入上的代码/测试验证；没有读取生产 HDF5、提交或启动 material worker、solver、GPU、队列或 qualification attempt。没有新增材料结果或 T2 credit。它关闭的是“插值生成更密时间轴可被当作原生 cadence”的实现漏洞，不证明 `.002 s` 生产来源已存在或通过验收。
