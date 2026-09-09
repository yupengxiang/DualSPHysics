"""Reuse the existing Q1 raw trajectory for native external probe observations."""

import subprocess, time
from scripts import l1r_q1_official as q1
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.l1r_continuation_evidence import LAB, OUT, write


def main():
    start = time.monotonic()
    attempt = next(
        (LAB / "campaigns/l1-resume/runs/q1-official").glob("*/attempts/*.complete")
    )
    dest = OUT / "q1-measure"
    dest.mkdir(exist_ok=True)
    source = LAB / "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak"
    for name in ("elevation", "pressure"):
        cmd = [
            str(q2.BIN / "MeasureTool_linux64"),
            "-dirdata",
            str(attempt / "data"),
            "-points",
            str(source / (name + ".txt")),
            "-onlytype:-all,+fluid",
            "-threads:8",
            "-savecsv",
            str(dest / name),
        ]
        cmd += (
            ["-elevation:0.5"]
            if name == "elevation"
            else ["-vars:-all,+press", "-kclimit:0.5", "-kcusedummy:0"]
        )
        with (dest / (name + ".log")).open("w") as f:
            p = subprocess.run(
                cmd,
                cwd=LAB,
                env=q2.environment(cpu=True),
                stdout=f,
                stderr=subprocess.STDOUT,
            )
        if p.returncode:
            raise RuntimeError(f"{name} failed: {p.returncode}")
    write(
        "Q1-MEASURE-EXECUTION.json",
        {
            "elapsed_seconds": time.monotonic() - start,
            "cpu_core_hours_upper_bound": 8 * (time.monotonic() - start) / 3600,
            "source_attempt": str(attempt.relative_to(LAB)),
            "probe_files": {
                name: q2.fingerprint(source / (name + ".txt"))
                for name in ("elevation", "pressure")
            },
            "pressure_dummy_support": False,
            "new_solver_attempts": 0,
        },
    )


if __name__ == "__main__":
    main()
