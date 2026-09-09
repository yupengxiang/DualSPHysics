# 复现与审阅命令

工作目录：`/home/jade/Projects/DualSPHysics`。以下命令使用已存在的 lab virtualenv；不要用未配置 `LD_LIBRARY_PATH` 的裸 solver 命令。

## 环境

- branch：`codex/lagrangian-fluid-exploration`
- baseline：`dc9533eecf7ee608a1db04ea4e26bb80cd2b456a`
- OS：Ubuntu kernel `6.8.0-138-generic`，x86_64
- Python：3.10.12；GPU：NVIDIA RTX 6000 Ada，49,140 MiB/card；driver `595.71.05`
- solver：`vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64`
- solver SHA-256：`0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29`
- GenCase SHA-256：`a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226`
- PartVTK SHA-256：`62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00`

## 只读检查

```bash
cd /home/jade/Projects/DualSPHysics
PYTHONPATH=lagrangian-fluid-lab \
  lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/scripts/l1_f1_qualification.py status

PYTHONPATH=lagrangian-fluid-lab \
  lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/scripts/l1_f1_qualification.py recompute-resources
```

`recompute-resources` 只从 attempt manifest 重算 GPU/CPU 账本，不启动 solver。

## 已完成 W2-A 的审计恢复

W2-A solver 的完成 attempt 和归一化 HDF5 已存在时，使用：

```bash
cd /home/jade/Projects/DualSPHysics
PYTHONPATH=lagrangian-fluid-lab \
  lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/scripts/l1_w2_boundary_control.py --audit-existing
```

该模式只读 `latest.json`、已有 HDF5、`RunPARTs.csv` 和 preflight snapshot，不重新运行 GenCase/PartVTK/solver。它会写 `l1-w2-boundary-control.json` 和 W2 full audit。

## 从头复现实验（只在明确授权且 GPU 有余量时）

```bash
cd /home/jade/Projects/DualSPHysics
PYTHONPATH=lagrangian-fluid-lab \
  lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/scripts/l1_w2_boundary_control.py
```

执行器会在 GPU 4--7 中重新选择 allowlisted 且空闲显存不少于 6144 MiB 的单卡；每秒检查，低于 4096 MiB 自动终止本 L1 solver。GPU 0--3 不会被触碰。该命令会产生新 attempt，不能用来覆盖本次已封存的 W2-A 证据。

## 验证

```bash
cd /home/jade/Projects/DualSPHysics
lagrangian-fluid-lab/.venv/bin/python -m py_compile \
  lagrangian-fluid-lab/scripts/l1_f1_qualification.py \
  lagrangian-fluid-lab/scripts/r6_n2_campaign.py \
  lagrangian-fluid-lab/scripts/l1_w2_boundary_control.py

lagrangian-fluid-lab/.venv/bin/python -m pytest -q \
  lagrangian-fluid-lab/tests/test_l1_f1_qualification_contract.py \
  lagrangian-fluid-lab/tests/test_campaign_runner.py
```

逐个输出和小型证据的哈希见 `DATA-MANIFEST.json`。原始 `.bi4`、CSV、HDF5 不随 Git 提交，需从同一运行节点按清单另行归档。
