"""Execute predeclared whole-template/F3 cases with shared campaign guards."""

import argparse, json, fcntl, subprocess, time, hashlib, shutil, re
from datetime import datetime, timezone
from scripts.l1r_continuation_evidence import LAB, OUT, write, ledger
from scripts.l1r_postprocess_case import process
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.campaign_runner import execute_attempt


def run(record):
    from scripts.l1r_continuation_evidence import begin_activity_window

    begin_activity_window()
    name = record["id"]
    if record["family"] == "F3":
        from scripts.l1r_input_preflight import check_input

        check_input(record)
    runs = LAB / "campaigns/l1-resume/runs/branches"
    latest = runs / name / "latest.json"
    if latest.exists():
        result = json.loads(latest.read_text())
        if result.get("status") != "completed":
            return result
        return process(record, result)
    with (OUT / "solver.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from scripts.l1r_continuation_evidence import check_budget

        check_budget()
        ledger()
        budget = json.loads((OUT / "RESOURCE-LEDGER.json").read_text())
        if (
            budget["qualification_attempts_remaining"] <= 0
            or budget["gpu_solver_hours"] >= 64
        ):
            raise RuntimeError("original budget exhausted")
        if datetime.now(timezone.utc) >= datetime.fromisoformat(
            budget["conservative_expiry_utc"]
        ):
            raise RuntimeError("original activity expired")
        # F3 continuation uses the shared qualification pool checked above.
        # The exhausted historical six-case child cap is not a new parent cap.
        disk = shutil.disk_usage(LAB)
        if disk.free < max(100 * 1024**3, 0.1 * disk.total):
            raise RuntimeError("disk reserve")
        gpu, preflight = q2.choose_gpu(record["gencase"]["total_particles"])
        if gpu is None:
            result = {"status": "blocked_resource", "resource_preflight": preflight}
            write(name + "-SOLVER.json", result)
            return result
        active = subprocess.run(
            ["pgrep", "-f", "/DualSPHysics5.4_linux64"], capture_output=True, text=True
        )
        if active.stdout.strip():
            raise RuntimeError("another solver active")
        prefix = LAB / record["generated_prefix"]
        cmd = [
            str(q2.SOLVER),
            f"-gpu:{gpu}",
            record["solver_mode"],
            str(prefix),
            "{output}",
        ]
        def guard():
            state=q2.gpu_guard(gpu,next(row['uuid'] for row in preflight['snapshot'] if row['index']==gpu))
            expected=record.get('expected_slip_mode')
            if state.get('ok') and expected:
                for log in (runs/name/'attempts').glob('*.partial/Run.out'):
                    found=re.search(r'SlipMode="([^"]+)"',log.read_text(errors='replace'))
                    if found and found[1]!=expected:
                        return {'ok':False,'reason':'effective boundary mode mismatch','expected':expected,'actual':found[1]}
            return state
        result = execute_attempt(
            name,
            cmd,
            runs,
            cwd=prefix.parent,
            env=q2.environment(),
            evidence_glob="data/Part_*.bi4",
            required_text="Finished execution (code=0)",
            timeout_seconds=1800,
            resource_guard=guard,
            resource_poll_seconds=1.0,
        )
        result.update(
            resource_preflight=preflight,
            source_record=record,
            solver_sha256=q2.sha256(q2.SOLVER),
        )
        write(name + "-SOLVER.json", result)
        q2.atomic_json(latest, result)
        ledger()
    if result["status"] == "completed":
        return process(record, result)
    return result


def run_registry(records):
    results = []
    for record in records:
        write(record["id"] + "-PREPARED.json", record)
        result = run(record)
        results.append(result)
        print(
            record["id"], result.get("audit_status", result.get("status")), flush=True
        )
        if result.get("status") in ("blocked_resource", "failed"):
            print(
                "Stopped on execution/input failure; no repeated launches for a shared cause.",
                flush=True,
            )
            break
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["f1", "f3"])
    a = p.parse_args()
    registry = OUT / ("F1-WHOLE-TEMPLATE.json" if a.kind == "f1" else "F3-INPUT-REPAIR-READY.json")
    run_registry(json.loads(registry.read_text())["records"])
