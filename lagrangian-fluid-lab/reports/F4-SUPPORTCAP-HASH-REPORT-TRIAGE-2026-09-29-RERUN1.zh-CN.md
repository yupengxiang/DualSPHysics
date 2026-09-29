# F4 supportcap static receipt hash/report triage（2026-09-29 RERUN1）

本次只处理 F4 supportcap `r002` 静态设计的当前测试失败；旧 attribution、旧 recipe 和历史报告均未覆盖。

## 结论

最初从仓库根目录运行专项测试时出现 `4 failed, 112 passed`。四个失败都来自测试直接对
`predecessor.ATTRIBUTION` 做相对路径读取；同一批测试从 canonical `lagrangian-fluid-lab`
目录运行时原本已经是 `116 passed`。因此这不是 R001 attribution 内容或 HDF5 hash 漂移，
而是测试入口 cwd 依赖。

本 RERUN 只把测试读取改为 `predecessor.LAB / predecessor.ATTRIBUTION`，保持所有
zero-credit、fail-closed 和禁止读取大型生产 artifact 的边界。受测试源码 hash 影响的
静态 recipe 使用新的不可覆盖路径：

- `campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v2-20260929-RERUN1/recipe.json`
- `campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/r002-static-design-v3-20260929-RERUN1/recipe.json`

旧的 `r002-static-design-v2/`、`r002-static-design-v3/` recipe 保持原样，R001 attribution
也保持原样。新 recipe 仍声明 `native_preflight_authorized=false`、`cpu_canary_authorized=false`、
`solver_authorized=false`、`gpu_authorized=false`、`worker_or_queue_authorized=false`，
qualification credit 为 `0`，且静态 builder 不对 HDF5/NPZ 执行 stat/open/parse/hash。

## 验证

```text
lagrangian-fluid-lab/.venv/bin/pytest -q lagrangian-fluid-lab/tests/test_f4_supportcap*.py
116 passed in 5.05s
py_compile: passed
git diff --check: passed
```

本轮没有启动 solver、worker、GPU 或 queue，也没有打开大型生产 HDF5/NPZ。

当前实现/测试/recipe SHA-256：

```text
scripts/f4_supportcap_r002_static_design_v2.py  c17ade76f97fab60f54254d73733e0285c36e8d18a2f17ede95a1a54b19abbc6
scripts/f4_supportcap_r002_static_design_v3.py  a1694053a8e0a60bacb587156dfdb8db6160137c4556c9a3322139a4e0b3fcd7
tests/test_f4_supportcap_r002_static_design_v2.py 65ba571402663ba271e39ff5f7311b0ef1eeec52d4aa9509a36909840c0d6512
tests/test_f4_supportcap_r002_static_design_v3.py 56c504ed9e6bbea978115fcdbe5baa7aaf538ad93db7641f8e97f6c5372b4897
```
