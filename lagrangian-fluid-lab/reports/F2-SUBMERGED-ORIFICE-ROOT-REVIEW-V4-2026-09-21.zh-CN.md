# F2 submerged-orifice v4 independent root review

该 review 只检查 v3 失败证据、v4 Definition/candidate/contract 及父 scope hash closure，没有执行 GenCase/native decoder、solver、GPU、queue、ledger、registry 或 matrix 操作。

v4 的唯一假设是镜像 GeometryForNormals 层方向并把源格点固定为 86×56×48；预测离散质量相对误差为 +0.78125%，zero-normal、ID、有限值、端点和质量门槛保持原登记值。

receipt 只授权一次全新 v4 CPU GenCase/native decode，credit=0。任何 hard-gate 失败都停止并保留 15 行分母，不能转 solver 或资格。

receipt SHA-256：`645136a7eaa138db0dae6da372ac29cdc27f0e4445567cf45311d97878f8bbc5`。
