"""Refresh this round's audits against final code, retaining previous summaries."""

import json, shutil
from scripts.l1r_continuation_evidence import LAB, OUT, trajectories
from scripts.l1r_cpu_slots import cpu_slot
from scripts.l1r_postprocess_case import _process
from scripts import l1r_q2_mdbc_bridge as q2

if __name__ == "__main__":
    with cpu_slot():
        old = OUT / "Q2-TRAJECTORIES.json"
        previous = OUT / "Q2-TRAJECTORIES-PREVIOUS.json"
        if not previous.exists():
            shutil.copy2(old, previous)
        trajectories()
        for name in (
            "Q2C3_OFFICIAL_CANONICAL_t06",
            "Q2C4_OFFICIAL_HALFGRID_t06",
            "F1_OFFICIAL_NS_NOP0_dp02_t15",
        ):
            path = OUT / (name + "-AUDIT.json")
            previous = OUT / (name + "-AUDIT-PREVIOUS.json")
            if not previous.exists():
                shutil.copy2(path, previous)
            record = json.loads((OUT / (name + "-PREPARED.json")).read_text())
            solver = json.loads((OUT / (name + "-SOLVER.json")).read_text())
            result = _process(record, solver)
            result["auditor_sha256"] = q2.sha256(LAB / "scripts/finite_wall_audit.py")
            q2.atomic_json(path, result)
            print(name, result["audit_status"], flush=True)
