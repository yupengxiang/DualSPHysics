"""Validate required driving assets using the native parser before GPU launch."""

import json, subprocess
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts import l1r_q2_mdbc_bridge as q2


def check_input(record):
    file = (LAB / record["generated_prefix"]).parent / "CaseSloshingAccData.csv"
    source = (
        LAB
        / "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv"
    )
    if not file.is_file() or file.stat().st_size == 0:
        raise ValueError("missing/empty acceleration input; no solver attempt launched")
    if q2.sha256(file) != q2.sha256(source):
        raise ValueError("driving input differs from declared source")
    p = subprocess.run(
        [str(LAB / "campaigns/l1-resume/artifacts/check_acc_input"), str(file)],
        text=True,
        capture_output=True,
    )
    if p.returncode:
        raise ValueError("native acceleration reader rejects input")
    parsed = json.loads(p.stdout)
    if parsed["first_time_s"] > 0 or parsed["last_time_s"] < record["time_max_s"]:
        raise ValueError("driving data does not cover run")
    result = {
        "asset": q2.fingerprint(file),
        "source": q2.fingerprint(source),
        "native_reader": parsed,
        "solver_attempts": 0,
        "status": "passed",
    }
    write(record["id"] + "-INPUT-PREFLIGHT.json", result)
    return result
