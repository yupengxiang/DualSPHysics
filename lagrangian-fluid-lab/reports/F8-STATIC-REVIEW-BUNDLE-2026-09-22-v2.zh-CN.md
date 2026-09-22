# F8 static review bundle v2（2026-09-22）

v2 在保留 static bundle v1 的 13+2 qualification matrix、body-force 命名、
固定分母和 root-decision 边界的基础上，新增并 hash-bind：

- 零初速度启动瞬态解析 oracle；
- 可执行的 observation payload parser；
- 固定频率正弦/余弦幅值与相位提取，禁止 time-shift fitting；
- startup oracle、parser 及测试的独立 contracts。

这仍不是 F8 admission。弱可压缩 SPH 的密度/相位/Mach 校准、native
integrity、组合 Definition/control、CPU anchor 和 13+2 实际资格仍缺失；
F8 是否属于 Core 第三家族仍待 root decision。没有任何 Definition、control、
GenCase、native decode、solver、GPU、queue、registry、ledger 或 training 执行。
