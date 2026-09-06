#!/usr/bin/env python3
"""Capture a reproducible, non-mutating campaign inventory."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "v0.1-candidate"
REPORT = CAMPAIGN / "w00-inventory.json"
BIN = ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"


def command(*args):
    return subprocess.run(args, cwd=ROOT.parent, text=True, check=True,
                          stdout=subprocess.PIPE).stdout.strip()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    gpu_query = command("nvidia-smi", "--query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu",
                        "--format=csv,noheader,nounits")
    gpus = []
    for line in gpu_query.splitlines():
        index, uuid, name, used, total, utilization = [value.strip() for value in line.split(",")]
        gpus.append({"physical_index": int(index), "uuid": uuid, "name": name,
                     "memory_used_mib": int(used), "memory_total_mib": int(total),
                     "utilization_percent": int(utilization),
                     "idle_at_inventory": int(used) < 1024 and int(utilization) < 10})
    binaries = {}
    for name in ("DualSPHysics5.4_linux64", "GenCase_linux64", "PartVTK_linux64"):
        path = BIN / name
        binaries[name] = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
                          "sha256": sha256(path)}
    disk = shutil.disk_usage(ROOT)
    report = {
        "schema_version": 1, "campaign_id": "v0.1-candidate",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "git": {"branch": command("git", "branch", "--show-current"),
                "commit": command("git", "rev-parse", "HEAD"),
                "status_porcelain": command("git", "status", "--porcelain")},
        "host": {"gpu_count": len(gpus), "gpus": gpus,
                 "disk_total_bytes": disk.total, "disk_free_bytes": disk.free},
        "execution_policy": {
            "allowed_gpu_uuids": [gpu["uuid"] for gpu in gpus if gpu["idle_at_inventory"]],
            "single_heavy_job_per_gpu": True,
            "recheck_before_each_batch": True,
            "raw_first_round_immutable": True,
            "new_data_limit_bytes": 1649267441664,
        },
        "binaries": binaries,
    }
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {REPORT.relative_to(ROOT)}; idle GPUs: " +
          ", ".join(str(g["physical_index"]) for g in gpus if g["idle_at_inventory"]))


if __name__ == "__main__":
    main()
