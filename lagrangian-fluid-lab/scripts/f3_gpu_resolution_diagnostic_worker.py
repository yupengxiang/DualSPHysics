"""Run the registered CFL contrast under the private matching GPU runtime."""
import json
import os
from pathlib import Path
import subprocess

from scripts.l1r_continuation_evidence import OUT, begin_activity_window, finish_activity_window, ledger
from scripts import l1r_q2_mdbc_bridge as q2


def runtime_environment():
    evidence = json.loads((OUT / "F3-GPU-RUNTIME-RECOVERY.json").read_text())
    root = Path(evidence["root"])
    if Path("/proc/driver/nvidia/version").read_text() != evidence["kernel_version"]:
        raise RuntimeError("loaded NVIDIA kernel changed; revalidate private runtime")
    for relative, digest in evidence["library_hashes"].items():
        if q2.sha256(root / relative) != digest:
            raise RuntimeError("private NVIDIA library changed: " + relative)
    target = root / "595.71.05"
    if q2.sha256(target / "usr/bin/nvidia-smi") != evidence["nvidia_smi_sha256"]:
        raise RuntimeError("private NVIDIA utility changed")
    env = os.environ.copy()
    # This worker selects the physical GPU through the guarded solver command;
    # an inherited empty mask would make CUDA report device 100 before launch.
    env.pop("CUDA_VISIBLE_DEVICES", None)
    env.pop("NVIDIA_VISIBLE_DEVICES", None)
    env["PATH"] = str(target / "usr/bin") + ":" + env["PATH"]
    env["LD_LIBRARY_PATH"] = str(target / "usr/lib/x86_64-linux-gnu")
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "8"
    return env


def main():
    from scripts.f3_nopen_resolution_diagnostic import DIAGNOSTIC_ID
    env = runtime_environment()
    command = [str(Path(__file__).resolve().parents[1] / ".venv/bin/python"), "-u", "-m",
               "scripts.f3_nopen_resolution_diagnostic"]
    begin_activity_window()
    child = None
    try:
        child = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=env)
        code = child.wait()
        return code
    finally:
        if child is None or child.poll() is not None:
            finish_activity_window()
            ledger()


if __name__ == "__main__":
    raise SystemExit(main())
