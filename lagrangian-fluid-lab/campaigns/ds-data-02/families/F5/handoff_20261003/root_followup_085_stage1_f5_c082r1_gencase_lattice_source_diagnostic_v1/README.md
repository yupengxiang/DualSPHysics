# F5 fresh085：C082R1 GenCase 格点缺口诊断

这是 F5 隔离工作树中的 source-only 诊断包。它不修改 C082/C082R1 输入，不读取
BI4/H5/科学 CSV，不启动 GenCase、PartVTK、solver 或 converter。Root 严格 CPU
worker 启用后，才会读取 Root246 已生成的 `R1-initial-all.csv`；本包对该 CSV
只绑定路径，`official_csv_sha256` 保持 `null`，由实际 worker 在作业内读取和计算。

Root234 的实际 R1 producer 证据仍是：

```text
194427 = 158559 fixed + 4210 moving + 0 floating + 31658 fluid
generated XML SHA 2417cf656dbb7308e5e9c193e230fb115b80510d87ad39342f02cdeaf3fdb976
producer-declared BI4 SHA d7fa9b4373d9addcaed7f44324622aca94c91a7dd23f55407e6897126c900f67
```

Root246 的官方 PartVTK 已导出 194427 行；先前的身份/零类别字段问题已由 Root246
修复，但 worker 在真正的科学检查中因 fluid `dp` 格点残差失败。Root 提供的
producer CSV SHA256 是
`a1165d9d1d6645f22774eb57c6be0a236b1fbba90f46577cc2ab3fa51d2abfb8`；source agent
没有打开或重新哈希该 CSV，只把这个 Root 已登记的 opaque hash 绑定进 disabled
request。该失败保留为 negative evidence，不能通过放宽残差阈值、平移或重采样输入来消除。

源级结论如下：

* C082/C082R1 的顺序是 `closed=true drawextrude` 床体，随后 tank/sidewall/piston，
  `shapeout reset=true`，然后 `setmkfluid`、原 clipplane、`drawbox boxfill=solid`
  流体、`clipreset`。源码没有 `erase` 或 `eraseall`；`shapeout reset` 不能据此解释
  为 erase selector。
* C082 使用 `layers vdp="0,1,2,3,4"`，R1 使用 `0,-1,-2,-3,-4`。两者 fluid 都是
  31658，而 fixed 计数改变，故 layer 符号本身不是已证实的流体缺口根因。
* 官方模板只证明 `drawextrude` 接受 `closed`、`extrude` 和 `layers` 语法；随仓库
  没有普通 GenCase draw/boxfill parser 的 C++ 实现。官方边界示例通常在边界后使用
  `fillbox modefill=void`，C082R1 在 closed solid bed 后使用 `drawbox boxfill=solid`。
  这构成有依据但未证实的 draw-order/solid-occupancy 假设，不能写成 parser 契约。

独立格点预检（不是 producer 计数合同）给出：矩形 fluid box 的端点组合中，按
`pointref=(.01,0,.01)`, `dp=.02` 和 clipplane 的 tie 规则，clip-only 湿格候选为
约 40695–40740；历史 40710 落在这个 tie band 内。将 closed bed 的几何内部直接
从矩形扣除得到连续等效约 38232.76 DP³，但这不是 clip-plane 后的离散期望，不能
用来替换 31658。实际 31658 比 clip-only band 少约 9037–9082 个格点，远超过端点
tie/CSV 精度差异，提示需要实际 CSV 的位置分布来区分 shape occupancy、drawbox
固体优先级和导出精度。生成的 `discrete-wet-lattice-preflight.json` 还显示，简单的
boundary-inclusive polygon point test 从该候选 band 只扣除 0/45 个 tie 点；这是源级
算术比较，不是 GenCase parser 合同。

`workers/diagnose_r1_initial_csv_lattice.py` 的实际诊断包括：逐轴 residual 分位数
和最大值、nearest source grid、float32 ULP/round-trip 对照、fluid x/y/z 计数、
clip-only 缺口、Type0/Mk50 六段中心床面支持、fluid profile/bounds 判定和运行时
CSV SHA。报告只描述观测与缺口，不给出 QA pass、dynamic acceptance 或 full801 授权。

`diagnostic-request.json` 保持 disabled，attempt 使用 `root-stage1-f5-c082r1-initial-csv-lattice-diagnostic-247`。
短时 solver、typed、XMF、bed audit 与 full801 仍 disabled；该诊断不增加独立案例数。
