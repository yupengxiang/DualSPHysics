# F3 material 原生 cadence 元数据伪报回归（2026-09-24）

新增合成回归：实际 HDF5 时间轴为 `.01 s`，但来源 metadata 被篡改为 `.002 s`，再请求 `.002 s` 对齐。对齐器必须由 `CachedSource` 的帧数/完整时间轴审计拒绝；目标文件和 `.partial` 均不得创建。这证明守卫不只依赖调用者声明的 cadence。

- `tests/test_f3_material_reference.py`：29 passed。
- F3 material reference、T2 readiness v1/v2/v3、neighbor、manufactured 关联测试：73 passed。
- `git diff --check`：通过。

验证仅使用临时合成 HDF5；没有读取生产 HDF5、运行 worker/solver/GPU/queue，也没有提交 scientific attempt 或改变 T1/T2 credit。
