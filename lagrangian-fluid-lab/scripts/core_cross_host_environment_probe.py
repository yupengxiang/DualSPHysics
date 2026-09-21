#!/usr/bin/env python3
"""Record a matched canary environment without constructing a CUDA model."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


PACKAGE_NAMES = ("torch", "numpy", "scipy", "h5py")
BUNDLE_MODULES = ("scripts.core_contract", "scripts.core_dataset", "scripts.core_models")


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def package_record(name: str) -> dict:
    module = importlib.import_module(name)
    path = Path(module.__file__).resolve()
    return {
        "name": name,
        "version": str(getattr(module, "__version__", "unknown")),
        "path": str(path),
        "sha256": sha256_file(path),
    }


def command_output(argv: list[str]) -> dict:
    executable = argv[0]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    except Exception as error:  # pragma: no cover - host-specific utility
        return {"argv": argv, "available": False, "error": f"{type(error).__name__}: {error}"}
    return {
        "argv": argv,
        "executable": executable,
        "available": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def cpu_record() -> dict:
    path = Path("/proc/cpuinfo")
    if not path.is_file():
        return {"available": False}
    raw = path.read_bytes()
    text = raw.decode(errors="replace")
    flags = set()
    model_names = set()
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        if key.strip().lower() in {"flags", "features"}:
            flags.update(value.split())
        if key.strip().lower() == "model name":
            model_names.add(value.strip())
    return {
        "available": True,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "logical_processors": sum(
            line.partition(":")[0].strip() == "processor"
            for line in text.splitlines()),
        "model_names": sorted(model_names),
        "flags": sorted(flags),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bundle-code-root", type=Path)
    parser.add_argument("--host-label")
    args = parser.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES"):
        raise SystemExit("probe requires CUDA_VISIBLE_DEVICES to be empty")

    packages = [package_record(name) for name in PACKAGE_NAMES]
    torch = importlib.import_module("torch")
    bundle_modules = []
    if args.bundle_code_root is not None:
        sys.path.insert(0, str(args.bundle_code_root.resolve()))
        bundle_modules = [
            {"module": name, "path": str(Path(importlib.import_module(name).__file__).resolve()),
             "sha256": sha256_file(Path(importlib.import_module(name).__file__).resolve())}
            for name in BUNDLE_MODULES
        ]
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    payload = {
        "schema": "core.cross_host_environment_probe.v1",
        "host_label": args.host_label,
        "probe_without_cuda_model": True,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "python": {"version": sys.version, "executable": sys.executable},
        "platform": platform.platform(),
        "hostname": platform.node(),
        "cpu": cpu_record(),
        "packages": packages,
        "torch_runtime": {
            "version": torch.__version__,
            "cuda_version": torch.version.cuda,
            "cuda_available_with_visibility_empty": bool(torch.cuda.is_available()),
            "deterministic_algorithms_enabled": bool(torch.are_deterministic_algorithms_enabled()),
            "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
            "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
        },
        "bundle_modules": bundle_modules,
        "pip_freeze_all": freeze,
        "driver_query": command_output([
            "nvidia-smi", "--query-gpu=driver_version,name,uuid", "--format=csv,noheader,nounits"
        ]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), "packages": packages}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
