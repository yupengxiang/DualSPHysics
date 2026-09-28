# F4 Tallwall120 coarse host-I/O admission projection

- Schema：`core.material.f4.tallwall120.coarse.host_io_admission_projection.v1`
- 状态：`diagnostic_admission_blocked`
- Scope：`F4_resting_pool_laminar_tallwall120_x_v1`
- Case：`F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`

## 投影决策

- 输入合同：`True`
- F4 scope：`True`
- proposal/job normalized argv：`True` / `True`
- cwd：`True`；fresh namespace：`True`
- resource projection：`True`
- launch admitted：`False`；worker authorized：`False`
- formal：`False`；credit：`0`

该结果是 JSON-only synthetic diagnostic projection。generic host-I/O probe 不是 root/scheduler authorization，因此本报告不授予 worker launch、formal admission、T2 或 credit。

## 资源投影

- declared CPU/RAM/GPU：`2` / `24576` MiB / `6144` MiB
- declared owned I/O：`2097152` bytes
- declared total probe I/O：`2228224` bytes
- scheduler-owned I/O verified：`False`
- GPU allocation observed/authorized：`False` / `False`

## 边界

只读取 coarse proposal、generic host-I/O receipt 和 DEV_07 F4 job spec。未解析、打开、哈希或读取 proposal 指向的大体积 HDF5；未启动 worker、solver、native、GPU、queue；未修改 registry、completion、ledger、denominator 或 gate。

## 阻塞原因

- `fresh_root_authorization_missing`
- `scheduler_authorization_missing`
