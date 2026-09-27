# Core continuation status — 2026-09-27 — UPDATE-233

## F3 material v2 synthetic performance profile

按计划先完成材料模块的可重复小规模性能基线。使用仓库 `.venv/bin/python`，并将 `OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`MKL_NUM_THREADS`、`NUMEXPR_NUM_THREADS` 固定为 `1`；启动时 1-minute load 为 `34.60`，低于进程可见的 128 CPU，因此通过 profiler 的资源门。命令只生成临时 synthetic source/trace HDF5，运行结束后临时文件已删除。

固定默认配置为 512 seeds、4096 particles、20 intervals、1 substep、`dp=0.0075 m`、model provider。报告为 [`F3-MATERIAL-V2-SYNTHETIC-PROFILE-2026-09-27.json`](F3-MATERIAL-V2-SYNTHETIC-PROFILE-2026-09-27.json)，其摘要为：

| 项目 | 结果 |
|---|---:|
| wall / CPU time | 13.803345 / 13.803414 s |
| peak RSS | 574108 KiB |
| final unknown fraction | 0.623046875 |
| common reliable path fraction | 0.376953125 |
| profiler regression | 4 passed |

报告的 `profile_kind=synthetic_only_no_qualification_credit`、`qualification_claim=none` 保持不变。合成随机支持云不代表生产 F3 粒子分布；unknown/reliable 数字不是材料科学资格结果，也没有读取生产 HDF5、运行 solver/worker/GPU/queue、写入 T2 registry 或产生资格 credit。`core_campaign.py status` 的 T1/T2、训练和 case-run 分母不变。

系统 Python 的 h5py/NumPy ABI 不兼容，且直接调用缺少 `PYTHONPATH`；这两项环境问题通过仓库规定的 `.venv` 与 `PYTHONPATH=.` 入口解决，没有修改环境或代码。生产材料运行仍须新的资源/worker 授权，并单独通过可靠性矩阵。
