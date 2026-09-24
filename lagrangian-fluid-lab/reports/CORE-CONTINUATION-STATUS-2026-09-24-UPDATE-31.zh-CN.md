# Core 接续状态 UPDATE-31：F8 R008 native fluid table v2 静态实现复核

日期：2026-09-24

## 本轮推进

承接 [UPDATE-30](CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-30.zh-CN.md)，新增版本化的 F8 R008 native fluid table v2 合约与 standalone 语义 verifier。历史 v1 schema、接口及回执均未改写；其 SHA-256 仍为 `2258f903146ee1e0a2b09b616864b770d928270818128826b327aeb625e7a8a8`。

v2 固定完整 C 原生时间轴及排序后的 fluid-only ID 投影，逐帧从原始 BI4 的 `Pos`/`Posd`、`Vel`、`Rhop` 重算位置、速度、密度；`MassFluid` 则要求先与 B 初态逐字节匹配 binary64，再以 IEEE-754 roundTiesToEven 一次转换为 float32，不能从时变密度推质量。HDF5 校验包含大小/维度预算、held-FD 与前后身份/hash 检查、固定属性、精确 dtype/enum、链接闭包、过滤器与分块布局。验证器只接受由调用方预先验证并绑定的 B/C/D 上下文，不自行认证这些外部信任输入。

Terra High 首轮静态复核指出固定属性可被调用方同步覆盖、enum 原始值 `2` 会被 bool 转换混淆、根 link 闭包需更强证明；修正后 focused follow-up 为 `PASS`。最终回执为 [design review v2](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/design-review-v2/receipt.json)，reviewer 为 `gpt-5.6-terra` / high。

## 验证结果与边界

- v2 合约、实现、synthetic BI4/HDF5 回归及 review archive 测试共 **34 passed**；其中 standalone verifier 定向套件 **32 passed**。覆盖 Posd float64 与 Pos float32 路径、Rhop 与 MassFluid 分离、完整帧轴和 ID 宇宙、MassFluid binary64 drift 与 roundTiesToEven 中点、HDF5 布尔 enum 原始值、未知 hard/group/soft/external links、缺失 chunk 和属性/尺寸篡改。
- 仅生成并读取临时 synthetic BI4/HDF5 fixtures；没有读取生产 B/C/D bundle 或生产 solver frame，也没有调用 GenCase、native decoder、solver、worker、GPU 或 queue。
- 本轮仅实现并复核 D table standalone semantics。**还没有**把它接入已审 B/C/D chain 的 trusted orchestration、没有 v2 table producer/metric adapter，也没有冻结 R008 Definition/control、几何/边界/法向的完整生产绑定审计；这些不能由当前 PASS 代替。
- F8 R008 仍 `readiness_pass=false`、`T1_numerical=false`、资格信用为 0；本轮不改变资源准入或正式执行门。

## 下一步

将 standalone verifier 接到安全重开的 B/C/D per-case provenance 上下文，加入 Definition/control 与几何、边界、法向的独立重算；随后再做 Terra High 静态复核。只有完整静态链与资源/执行授权门分别通过后，才能讨论 solver/T1 工作。
