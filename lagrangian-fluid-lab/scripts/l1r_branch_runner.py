"""Execute predeclared whole-template/F3 cases with shared campaign guards."""

import argparse, json, fcntl, subprocess, time, hashlib, shutil, re, math
from datetime import datetime, timezone
from pathlib import Path
from scripts.l1r_continuation_evidence import LAB, OUT, write, ledger, resource_limits
from scripts.l1r_postprocess_case import process
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.campaign_runner import execute_attempt, validate_resource_category


def check_gpu_time_reserve(record,budget):
    timeout=float(record.get('solver_timeout_seconds',1800))
    if not math.isfinite(timeout) or not 0<timeout<=7200:
        raise ValueError('solver timeout must be finite, positive and at most 7200 s')
    if budget['gpu_budget_charge_hours']+timeout/3600>resource_limits()['gpu_hours']:
        raise RuntimeError('remaining GPU budget cannot cover the guarded attempt timeout')
    return timeout


def boundary_log_mismatch(record,log):
    for key,pattern,convert in (
        ('expected_slip_mode',r'SlipMode="([^"]+)"',str),
        ('expected_no_penetration',r'No Penetration=(True|False)',lambda x:x=='True'),
    ):
        found=re.search(pattern,log)
        if key in record and found and convert(found[1])!=record[key]:
            return {'ok':False,'reason':'effective boundary mode mismatch',
                    'field':key,'expected':record[key],'actual':convert(found[1])}
    return None


def check_completed_boundary(record,result):
    """Do not publish a source audit without the required native initialization."""
    fields={'expected_slip_mode':r'SlipMode="([^"]+)"',
            'expected_no_penetration':r'No Penetration=(True|False)'}
    if not any(key in record for key in fields):return
    log=(Path(result['attempt_directory'])/'Run.out').read_text()
    for key,pattern in fields.items():
        if key in record and not re.search(pattern,log):
            raise ValueError('completed solver log lacks required boundary field: '+key)
    mismatch=boundary_log_mismatch(record,log)
    if mismatch:raise ValueError('completed solver boundary mismatch: '+json.dumps(mismatch))


def check_case_attempt_limit(record,runs):
    cap=record.get('max_attempts')
    if cap is None:return
    if not isinstance(cap,int) or isinstance(cap,bool) or cap<1:
        raise ValueError('invalid per-case attempt limit')
    attempts=runs/record['id']/'attempts'
    count=sum(p.is_dir() for p in attempts.iterdir()) if attempts.exists() else 0
    if count>=cap:raise RuntimeError('registered per-case attempt limit exhausted; reconcile existing attempt without relaunch')


def check_record_resource_category(record):
    """Bind development accounting to registered physical cases, not reference qualification."""
    category=validate_resource_category(record.get('resource_category','qualification'))
    if category=='qualification':return category
    if record.get('family')!='F3' or not record.get('case_id') or record.get('id')!=record['case_id']:
        raise ValueError('development resource category requires matching F3 case identities')
    registry=json.loads((OUT/'F3-DEVELOPMENT-CANDIDATES.json').read_text())
    candidates=[row for row in registry['cases'] if row['case_id']==record['case_id']]
    if len(candidates)!=1:
        raise ValueError('development case is not uniquely registered in the candidate manifest')
    candidate=candidates[0]
    for key,source_key in (('drive_amplitude','drive_amplitude'),
                           ('drive_sha256','control_file_sha256'),
                           ('physical_lineage_sha256','physical_lineage_sha256')):
        if key not in record or record[key]!=candidate[source_key]:
            raise ValueError('development case differs from registered candidate: '+key)
    return category


def run(record):
    from scripts.l1r_continuation_evidence import begin_activity_window

    category=check_record_resource_category(record)
    begin_activity_window()
    name = record["id"]
    if record["family"] == "F3":
        from scripts.l1r_input_preflight import check_input

        check_input(record)
    runs = LAB / "campaigns/l1-resume/runs/branches"
    latest = runs / name / "latest.json"
    if latest.exists():
        result = json.loads(latest.read_text())
        if validate_resource_category(result.get('resource_category','qualification'))!=category:
            raise ValueError('existing attempt resource category differs; historical attempts cannot be relabelled')
        if result.get("status") != "completed":
            return result
        check_completed_boundary(record,result)
        return process(record, result)
    with (OUT / "solver.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_case_attempt_limit(record,runs)
        from scripts.l1r_continuation_evidence import check_budget

        budget = check_budget(category=category)
        timeout_seconds=check_gpu_time_reserve(record,budget)
        if (
            budget[f"{category}_attempts_remaining"] <= 0
            or budget["gpu_solver_hours"] >= 64
        ):
            raise RuntimeError("original budget exhausted")
        if datetime.now(timezone.utc) >= datetime.fromisoformat(
            budget["conservative_expiry_utc"]
        ):
            raise RuntimeError("original activity expired")
        # Both categories share CPU, GPU and storage caps; only attempt pools differ.
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
            if state.get('ok'):
                for log in (runs/name/'attempts').glob('*.partial/Run.out'):
                    mismatch=boundary_log_mismatch(record,log.read_text(errors='replace'))
                    if mismatch:return mismatch
            return state
        result = execute_attempt(
            name,
            cmd,
            runs,
            cwd=prefix.parent,
            env=q2.environment(),
            evidence_glob="data/Part_*.bi4",
            required_text="Finished execution (code=0)",
            timeout_seconds=timeout_seconds,
            resource_guard=guard,
            resource_poll_seconds=1.0,
            resource_category=category,
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
        check_completed_boundary(record,result)
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
