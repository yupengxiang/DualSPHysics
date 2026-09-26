# UPDATE-178：`pointref` 公共合同与本地源码适用范围

时间：2026-09-26（Asia/Shanghai）

## 可确认的公共语义

DualSPHysics v5.4 官方变更记录将 `<pointref>` 描述为 `<definition>` 中的可选项，用来“according to reference position and Dp value”进行 fit。它确认参考位置与粒距参与拟合，但没有在该条目中规定普通 `fillbox`/`boxfill` 的精确节点纳入、半格 tie-breaking 或人口计数规则。见[官方 CHANGES.txt](https://github.com/DualSPHysics/DualSPHysics/blob/master/CHANGES.txt)（本地随附副本同样记录于第 263 行）。

## 本地 v5.4.355 源码的适用边界

只读检查本仓库 `src/source/main.cpp` 标记的 DualSPHysics v5.4.355，以及：

- `JCaseVRes::LoadXmlPtref` 从 `case.casedef.geometry.definition.pointref` 读取参考坐标，缺省为零（`src/source/JCaseVRes.cpp:967–989`）。
- 该函数在 `JCaseVRes::ReadXmlDef` 处理 `bufferbox` 时按 `dp=parent->Dp/dpratio` 调用；读取的参考点被传给 `JCaseVRes_Box`（同文件 `:1038–1078`）。
- 该类用于变分辨率子域的 `FitDomain` 以 `CalcRoundPos(pos, ConfigRef, Dp)` 将范围拟合到格点，并在舍入后将 min/max 向外扩展以包住配置几何（同文件 `:725–744`；`FunctionsMath.h:381–384` 中 `CalcRoundPos` 使用 `round((pos-posmin)/dp)`）。

这是 buffer-zone / variable-resolution 域边界拟合的直接实现证据，不是 F4R 普通 fluid `fillbox` 的生成路径证据。当前仓库没有对应的 GenCase 实现源码；尽管有随附 GenCase 二进制，本轮没有执行它。因此不能把上述 rounding/扩域规则外推为 F4R 的 `boxfill=solid` 纳入算法。

源码快照 SHA-256：`JCaseVRes.cpp` `a1394e05ce178c053c3bba87cf600a64022dae90363881a17cbc7493f977a445`；`FunctionsMath.h` `944e4f65021e278ad666997ddf0c3a6ea123a52d4516b1fe300a0167032c425c`。

## 对 F4R 后续工作的影响

现有证据仍支持“显式参考位置是可研究的格点相位控制量”，但尚不足以冻结 `pointref=0 → dp/2` 为已知结果的 F4R 候选，更不能据此声称会消除 `dp/3` 外偏或动态穿墙。任何后续对照至少要同时核算实际生成人口、总初始质量（保持名义单粒子质量，不作质量缩放）、池面/边缘位置及控制变量；连续几何和其他控制应锁定。

本研究分支的 F4R 格点相位问题与已登记的 F4 supportcap 新候选 CPU canary 授权不是同一已确认 scope。本轮没有定义或提交 canary 候选，没有消费该一次性授权；也没有运行 GenCase、solver、worker、GPU、队列或重读 HDF5。T1/T2=false，资格 credit=0。

## 结论

公开合同支持“参考位置与 `Dp` 参与 fit”；本地源码只闭合变分辨率 buffer-zone 子域的实现细节。F4R 普通 box-fill 的格点边界规则及其与动态穿墙的因果仍未闭合。下一步应优先取得与 F4R 对应版本的 GenCase 源码/权威算法说明，或在先冻结可审计的纯格点预测与质量核算、明确权限 scope 后再设计独立对照；在此之前不把推断写成结果。
