"""Execute predeclared whole-template/F3 cases with shared campaign guards."""

import argparse, json, fcntl, subprocess, time, hashlib, shutil, re, math
from datetime import datetime, timezone
from pathlib import Path
from scripts.l1r_continuation_evidence import LAB, OUT, write, ledger, resource_limits
from scripts.l1r_postprocess_case import process
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.campaign_runner import execute_attempt, validate_resource_category


REF008_RECIPE = "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818"
REF008_MANIFEST = LAB / "diagnostics/f3-audit/F3-075-REF0081818-MANIFEST.json"
REF008_SUMMARY = OUT / "F3-075-REF0081818-PREPARATION-SUMMARY.json"
REF008_AUTHORIZATION = OUT / "F3-075-REF0081818-AUTHORIZATION.json"
REF008_GATE = OUT / "F3-075-REF0081818-GATE.json"


def check_gpu_time_reserve(record,budget):
    timeout=float(record.get('solver_timeout_seconds',1800))
    if not math.isfinite(timeout) or not 0<timeout<=7200:
        raise ValueError('solver timeout must be finite, positive and at most 7200 s')
    if budget['gpu_budget_charge_hours']+timeout/3600>resource_limits()['gpu_hours']:
        raise RuntimeError('remaining GPU budget cannot cover the guarded attempt timeout')
    return timeout


def check_cpu_time_reserve(timeout_seconds,budget):
    # Preserve the existing full activity-window accounting rate and reserve
    # ten additional minutes for normalization/audit. This is a launch bound,
    # not measured CPU usage and does not reset or deduct previous charges.
    reserve=(timeout_seconds+600)*17.6/3600
    if budget['cpu_core_hours_upper_bound']+reserve>budget['limits']['cpu_core_hours']:
        raise RuntimeError('remaining CPU budget cannot cover solver timeout and postprocessing reserve')
    return {'cpu_core_hours_forward_reserve':reserve,'accounting_cores':17.6,
            'solver_timeout_seconds':timeout_seconds,'postprocessing_reserve_seconds':600}


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


def _verify_ref008_authorization(record):
    """Verify the on-disk owner authorization instead of trusting a dict flag."""
    if record.get("recipe_id") != REF008_RECIPE:
        return None
    if not REF008_AUTHORIZATION.is_file():
        raise PermissionError("ref0081818 has no owner authorization record")
    if not REF008_MANIFEST.is_file() or not REF008_SUMMARY.is_file():
        raise PermissionError("ref0081818 authorization bindings are incomplete")
    authorization = json.loads(REF008_AUTHORIZATION.read_text())
    manifest = json.loads(REF008_MANIFEST.read_text())
    summary = json.loads(REF008_SUMMARY.read_text())
    manifest_sha = q2.sha256(REF008_MANIFEST)
    summary_sha = q2.sha256(REF008_SUMMARY)
    if authorization.get("status") != "owner_authorized":
        raise PermissionError("ref0081818 authorization is not owner-authorized")
    if authorization.get("recipe_id") != REF008_RECIPE:
        raise PermissionError("ref0081818 authorization recipe mismatch")
    if authorization.get("manifest_sha256") != manifest_sha:
        raise PermissionError("ref0081818 authorization manifest binding mismatch")
    if authorization.get("summary_sha256") != summary_sha:
        raise PermissionError("ref0081818 authorization summary binding mismatch")
    approved_caps = manifest.get("resource_policy", {}).get("approved_resource_caps")
    if authorization.get("resource_limits") != approved_caps or approved_caps != {
        "cpu_core_hours": 896,
        "gpu_hours": 64,
        "qualification_attempts": 80,
    }:
        raise PermissionError("ref0081818 authorization resource caps are not the approved caps")
    if manifest.get("recipe_id") != REF008_RECIPE or manifest.get("launch_allowed") is not False:
        raise PermissionError("ref0081818 manifest is not the prepared-only manifest")
    if summary.get("recipe_id") != REF008_RECIPE or summary.get("launch_allowed") is not False:
        raise PermissionError("ref0081818 summary is not the prepared-only summary")
    if (summary.get("manifest_sha256") != manifest_sha
            or summary.get("solver_attempts") != 0
            or summary.get("qualification_attempts_charged") != 0
            or summary.get("qualified") is not False
            or summary.get("formal_release") is not False
            or summary.get("new_authorization_required") is not True):
        raise PermissionError("ref0081818 summary state is not the prepared-only state")
    cell_ids = set(authorization.get("authorized_cell_ids", []))
    manifest_cell_ids = {item.get("cell_id") for item in manifest.get("cells", [])}
    summary_cell_ids = set(summary.get("cell_ids", []))
    if cell_ids != manifest_cell_ids or summary_cell_ids != manifest_cell_ids:
        raise PermissionError("ref0081818 authorization cell set differs from manifest")
    record_bindings = summary.get("record_bindings", [])
    preflight_bindings = summary.get("preflight_bindings", [])
    if {item.get("path", "").split("/")[-1].removesuffix("-PREPARED.json")
        for item in record_bindings} != manifest_cell_ids:
        raise PermissionError("ref0081818 summary record bindings are incomplete")
    if {item.get("path", "").split("/")[-1].removesuffix("-INPUT-PREFLIGHT.json")
        for item in preflight_bindings} != manifest_cell_ids:
        raise PermissionError("ref0081818 summary preflight bindings are incomplete")
    for item in [*record_bindings, *preflight_bindings]:
        bound_path = LAB / item.get("path", "")
        if not bound_path.is_file() or q2.sha256(bound_path) != item.get("sha256"):
            raise PermissionError("ref0081818 summary binding hash mismatch")
    if record.get("id") not in cell_ids:
        raise PermissionError("ref0081818 record is outside the authorized cell set")
    expected_record = OUT / f"{record['id']}-PREPARED.json"
    binding = authorization.get("record_bindings", {}).get(record.get("id"))
    if not expected_record.is_file() or not isinstance(binding, str):
        raise PermissionError("ref0081818 record authorization binding is missing")
    if q2.sha256(expected_record) != binding:
        raise PermissionError("ref0081818 record authorization hash mismatch")
    persisted = json.loads(expected_record.read_text())
    if persisted != record:
        raise PermissionError("ref0081818 in-memory record differs from prepared record")
    if (persisted.get("recipe_id") != REF008_RECIPE
            or persisted.get("revision_manifest_sha256") != manifest_sha
            or persisted.get("launch_allowed") is not False
            or persisted.get("qualified") is not False
            or persisted.get("formal_release") is not False):
        raise PermissionError("ref0081818 prepared record is not the bound fail-closed record")
    prefix = LAB / persisted["generated_prefix"]
    for name, digest in persisted.get("input_assets", {}).items():
        asset = prefix.parent / name
        if not asset.is_file() or q2.sha256(asset) != digest:
            raise PermissionError("ref0081818 prepared input asset changed")
    if persisted.get("generated_xml_sha256") != q2.sha256(prefix.with_suffix(".xml")):
        raise PermissionError("ref0081818 prepared XML changed")
    preflight_path = OUT / f"{persisted['id']}-INPUT-PREFLIGHT.json"
    preflight = json.loads(preflight_path.read_text()) if preflight_path.is_file() else {}
    if (preflight.get("status") != "passed"
            or preflight.get("record_id") != persisted["id"]
            or preflight.get("record_sha256") != q2.sha256(expected_record)
            or preflight.get("recipe_id") != REF008_RECIPE
            or preflight.get("revision_manifest_sha256") != manifest_sha):
        raise PermissionError("ref0081818 prepared preflight binding changed")
    return authorization


def _verify_ref008_development_gate(record):
    """Require the passed ref008 gate before any development launch."""
    if record.get("resource_category") != "development":
        raise PermissionError("ref0081818 non-qualification records must be development records")
    if not REF008_GATE.is_file():
        raise PermissionError("ref0081818 development gate is not passed")
    gate = json.loads(REF008_GATE.read_text())
    if (gate.get("schema") != "f3.revision075.ref0081818.gate.v1"
            or gate.get("status") != "passed"
            or gate.get("recipe_id") != REF008_RECIPE
            or gate.get("development_launch_allowed") is not True):
        raise PermissionError("ref0081818 development gate is not passed")
    if record.get("source_revision_gate_sha256") != q2.sha256(REF008_GATE):
        raise PermissionError("ref0081818 development record is bound to another gate")


def run(record):
    from scripts.l1r_continuation_evidence import begin_activity_window

    # The exact-tiling ref0081818 branch remains blocked until a real
    # owner-authorized file is present and bound to the immutable preparation.
    if record.get("recipe_id") == REF008_RECIPE:
        if record.get("resource_category", "qualification") == "qualification":
            _verify_ref008_authorization(record)
        else:
            _verify_ref008_development_gate(record)

    category=check_record_resource_category(record)
    begin_activity_window()
    name = record["id"]
    if record["family"] == "F3":
        from scripts.l1r_input_preflight import check_input

        check_input(record)
        if record.get("recipe_id") == REF008_RECIPE:
            _verify_ref008_authorization(record)
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
        cpu_reserve=check_cpu_time_reserve(timeout_seconds,budget)
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
            cpu_time_reserve=cpu_reserve,
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
