"""Training attempt accounting and guarded execution; production gate is pending.

The public launcher deliberately refuses production until full numerical-domain
and actual-development-data contract validation is implemented. File hashes alone
do not establish those qualifications. Tests replace that gate for CPU workers.
This module's pure training_usage() can be imported by the shared ledger.
"""

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import uuid


LAB = Path(__file__).resolve().parents[1]
OUT = LAB / "campaigns/l1-resume/continuation"
# Full-axis evaluation outputs are large.  Keep them in an immutable archive
# beside the lab while the compact attempt records remain under the campaign;
# the physical-disk guard still applies and every attempt carries an artifact
# manifest with per-file hashes.
TRAINING_ROOT = LAB.parent / "f3-ref0081818-training-archive"
PARALLEL_AUTHORIZATION = OUT / "F3-075-REF0081818-TRAINING-PARALLEL-AUTHORIZATION.json"
REGISTRATION_LOCK = OUT / "training-registration.lock"
TRAINING_LOCK_ROOT = OUT / "training-attempt-locks"
ATTEMPT_SCHEMA = "f3.training.attempt.v1"
ACCOUNTING_VERSION = "f3-training-v1"
TERMINATION_GRACE_SECONDS = 5.0
CPU_CONTROL_CORES = 1
CPU_ALLOWANCE = 1.1
# Matches the preserved activity-window charge in l1r_continuation_evidence.
# This is a forward launch reserve only; actual base usage stays in that ledger.
BASE_CPU_ACTIVITY_CORE_MULTIPLIER = 16 * 1.1
GPU_PROBE_TIMEOUT_SECONDS = 5.0
POLL_SECONDS = 0.25
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_GPU_IDS = (4, 5, 6, 7)
PARALLEL_GPU_IDS = tuple(range(8))
GPU_MEMORY_RESERVATION_MIB = 18000


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parallel_policy():
    """Read the downstream-only eight-GPU authorization, if present.

    The historical Q2/ref008 gate intentionally retains its 4--7 protected
    policy.  Training may use the additional devices only through this
    separately recorded owner authorization, whose UUID map is checked against
    the live inventory before every launch and guard probe.
    """
    path = Path(PARALLEL_AUTHORIZATION)
    if not path.is_file() or path.parent.resolve() != OUT.resolve():
        return None
    value = json.loads(path.read_text())
    if (value.get("schema") != "f3.ref0081818.training.parallel-authorization.v1"
            or value.get("status") != "approved"
            or value.get("allowed_gpu_indices") != list(PARALLEL_GPU_IDS)):
        raise RuntimeError("parallel training authorization is invalid")
    uuids = value.get("allowed_gpu_uuids")
    if not isinstance(uuids, dict) or set(uuids) != {str(i) for i in PARALLEL_GPU_IDS}:
        raise RuntimeError("parallel training authorization lacks the complete GPU UUID map")
    if value.get("max_concurrent_training_runs", 0) < 1:
        raise RuntimeError("parallel training authorization has no concurrency allowance")
    return {"path": str(path.resolve()), "sha256": _sha256(path), "content": value,
            "gpu_ids": tuple(PARALLEL_GPU_IDS), "gpu_uuids": set(uuids.values())}


def _gpu_policy_for_record(record):
    policy = record.get("gpu_policy")
    if isinstance(policy, dict):
        indices = tuple(policy.get("allowed_gpu_indices", ()))
        uuids = set(policy.get("allowed_gpu_uuids", ()))
        if indices and uuids:
            return indices, uuids
    from scripts import l1r_q2_mdbc_bridge as q2
    # Legacy records predate the UUID field in the training policy.  Their
    # index restriction remains auditable; the live launch/guard performs the
    # inventory UUID check when such a record is actually started.
    return tuple(q2.GPU_IDS), None


def _training_gpu_policy():
    parallel = _parallel_policy()
    if parallel is not None:
        return parallel
    return {"path": None, "sha256": None, "content": None,
            "gpu_ids": DEFAULT_GPU_IDS, "gpu_uuids": None}


def _lock_is_held(path):
    """Return whether another process currently holds an advisory lock."""
    path = Path(path)
    if not path.is_file():
        return False
    with path.open("a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False


def _registration_lock():
    REGISTRATION_LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = REGISTRATION_LOCK.open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    except BaseException:
        handle.close()
        raise


def _running_attempt_is_live(record):
    pid = record.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    lock_path = record.get("training_lock_path")
    if lock_path:
        return _lock_is_held(lock_path)
    return True


def _atomic_json(path, value):
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _write_artifact_manifest(directory):
    """Hash every worker artifact before the attempt directory is published.

    ``attempt.json`` is intentionally excluded because the controller adds the
    manifest binding to that record immediately afterwards.  The manifest
    itself is also excluded from its file list to avoid a self-hash cycle.
    """
    directory = Path(directory)
    files = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name in ("attempt.json", "artifact-manifest.json"):
            continue
        files.append({"path": str(path.relative_to(directory)),
                      "size": path.stat().st_size,
                      "sha256": _sha256(path)})
    value = {
        "schema": "f3.training.external_archive_manifest.v1",
        "storage_scope": "external_immutable_archive",
        "excluded_files": ["attempt.json", "artifact-manifest.json"],
        "files": files,
    }
    path = directory / "artifact-manifest.json"
    _atomic_json(path, value)
    return {"path": "artifact-manifest.json", "sha256": _sha256(path),
            "file_count": len(files)}


def _nonnegative(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid numeric field: " + field)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid numeric field: " + field)
    return float(value)


def _reservation(timeout_seconds, cpu_cores):
    timeout = _nonnegative(timeout_seconds, "timeout_seconds")
    if timeout == 0:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(cpu_cores, bool) or not isinstance(cpu_cores, int) or not 1 <= cpu_cores <= 8:
        raise ValueError("cpu_cores must be an integer from 1 to 8")
    seconds = timeout + TERMINATION_GRACE_SECONDS
    multiplier = (cpu_cores + CPU_CONTROL_CORES) * CPU_ALLOWANCE
    return {"gpu_reserved_seconds": seconds,
            "cpu_reserved_core_hours": seconds * multiplier / 3600,
            "cpu_accounting_core_multiplier": multiplier}


def training_usage(root=None):
    """Read all training attempts, including failed and unresolved running work.

    Running timeout-plus-termination reserves are charges, not evidence of liveness.
    The CPU charge adds a controller core and 10% allowance to the worker affinity.
    Shared base CPU activity may already cover this time: adding both is explicitly
    conservative double counting, with no historical/base deduction.
    """
    root = Path(root) if root is not None else TRAINING_ROOT
    for directory in root.glob("*/*"):
        if (directory.is_dir() and directory.suffix in (".partial", ".complete", ".failed")
                and not (directory / "attempt.json").is_file()):
            raise ValueError("training attempt directory lacks its record: " + str(directory))
    rows = []
    seen = set()
    gpu_elapsed = gpu_reserved = cpu_elapsed = cpu_reserved = 0.0
    for path in sorted(root.glob("*/*/attempt.json")):
        raw = path.read_bytes()
        record = json.loads(raw)
        if record.get("schema") != ATTEMPT_SCHEMA or record.get("resource_category") != "training":
            raise ValueError("unrecognized training attempt: " + str(path))
        logical_id = record["logical_run_id"]
        execution_id = record["execution_attempt_id"]
        if not SAFE_ID.fullmatch(logical_id) or not SAFE_ID.fullmatch(execution_id):
            raise ValueError("invalid training attempt identity")
        if path.parent.parent.name != logical_id or path.parent.name not in (
            execution_id + ".partial", execution_id + ".complete", execution_id + ".failed"
        ) or execution_id in seen:
            raise ValueError("inconsistent or duplicate training attempt identity")
        seen.add(execution_id)
        reservation = _reservation(record["timeout_seconds"], record["cpu_cores"])
        allowed_indices, allowed_uuids = _gpu_policy_for_record(record)
        if (record["gpu_index"] not in allowed_indices
                or not isinstance(record.get("gpu_uuid"), str) or not record.get("gpu_uuid")):
            raise ValueError("training attempt lacks allowed GPU provenance")
        if any(record.get(key) != value for key, value in reservation.items()):
            raise ValueError("training attempt resource reservation is inconsistent")
        if record["status"] == "running":
            if record.get("elapsed_seconds") is not None:
                raise ValueError("running training attempt has terminal elapsed time")
            gpu_reserved += reservation["gpu_reserved_seconds"] / 3600
            cpu_reserved += reservation["cpu_reserved_core_hours"]
        elif record["status"] in ("completed", "failed"):
            elapsed = _nonnegative(record["elapsed_seconds"], "elapsed_seconds")
            gpu_elapsed += elapsed / 3600
            cpu_elapsed += elapsed * reservation["cpu_accounting_core_multiplier"] / 3600
        else:
            raise ValueError("unrecognized training attempt status")
        manifest = record.get("artifact_manifest")
        if manifest is not None:
            if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
                raise ValueError("training artifact manifest binding is invalid")
            manifest_path = Path(record["attempt_directory"]) / manifest["path"]
            if not manifest_path.is_file() or _sha256(manifest_path) != manifest.get("sha256"):
                raise ValueError("training artifact manifest changed: " + str(manifest_path))
        rows.append({**record, "record_path": str(path),
                     "record_sha256": hashlib.sha256(raw).hexdigest()})
    manifest = [{"path": row["record_path"], "sha256": row["record_sha256"]} for row in rows]
    return {
        "schema": "f3.training.usage.v1", "attempts_used": len(rows), "attempts": rows,
        "gpu_elapsed_hours": gpu_elapsed, "gpu_reserved_hours": gpu_reserved,
        "gpu_budget_charge_hours": gpu_elapsed + gpu_reserved,
        "cpu_elapsed_core_hours_upper_bound": cpu_elapsed,
        "cpu_reserved_core_hours": cpu_reserved,
        "cpu_core_hours_upper_bound": cpu_elapsed + cpu_reserved,
        "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "cpu_accounting_note": "Add to preserved shared base CPU without deduction; this can double-count activity-window time conservatively.",
    }


def _bound_file(reference, field, *, read_json=False):
    if not isinstance(reference, dict) or not reference.get("path"):
        raise ValueError(field + " requires a file path and SHA256")
    digest = reference.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(field + " requires a nonempty SHA256 digest")
    path = Path(reference["path"]).resolve()
    if not path.is_file() or _sha256(path) != digest:
        raise ValueError(field + " file differs from its SHA256")
    bound = {"path": str(path), "sha256": digest}
    if read_json:
        content = json.loads(path.read_text())
        if not isinstance(content, dict) or not content:
            raise ValueError(field + " must contain a nonempty JSON object")
        bound["content"] = content
    return bound


def _require_production_contracts(qualification, development):
    """Revalidate the actual domain gate and every selected development source.

    A digest proves that a contract file was not changed; it does not prove that
    the contract was substantively produced.  This gate therefore re-runs the
    domain verifier and the development contract verifier before any attempt is
    registered or a GPU is probed.
    """
    domain = qualification["content"]
    # The exact-tiling ref0081818 recipe has a separate revision gate and a
    # separate actual-source adapter.  Route it before the historical NoPen
    # schema checks so an old .010 gate can never qualify the new loader.
    if domain.get("recipe_id") == "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818":
        from scripts import f3_ref0081818_development as revision_development
        from scripts import f3_ref0081818_training_data as revision_training

        canonical = revision_development.verify_revision_gate()
        if canonical != domain:
            raise RuntimeError("qualification contract differs from the current ref0081818 gate")
        if canonical.get("training_launch_allowed") is not True:
            raise RuntimeError("ref0081818 gate has not granted training launch")
        if canonical.get("development_launch_allowed") is not True:
            raise RuntimeError("ref0081818 gate has not granted development launch")
        if canonical.get("production_resolution_m") != 0.0075:
            raise RuntimeError("ref0081818 gate has an invalid production resolution")
        if canonical.get("time_window_s") != [0.0, 8.35] or canonical.get("scoring_interval_s") != 0.01:
            raise RuntimeError("ref0081818 gate has an invalid time window or scoring interval")
        development_content = development["content"]
        if (development_content.get("schema") != revision_training.SCHEMA
                or development_content.get("status") != "passed"
                or development_content.get("qualified_sources") is not True
                or development_content.get("recipe_id") != canonical["recipe_id"]
                or development_content.get("production_resolution_m") != canonical["production_resolution_m"]
                or development_content.get("scope") not in revision_training.CONTRACTS):
            raise RuntimeError("ref0081818 contract is not a passed actual-source contract")
        source_gate = development_content.get("source_domain_gate")
        canonical_path = str(Path(qualification["path"]).resolve().relative_to(LAB.resolve()))
        if (not isinstance(source_gate, dict)
                or source_gate.get("path") != canonical_path
                or source_gate.get("sha256") != qualification["sha256"]):
            raise RuntimeError("ref0081818 training contract is bound to another revision gate")
        validated = revision_training.validate_development_contract(development["path"])
        if validated != development_content:
            raise RuntimeError("ref0081818 development contract changed during substantive validation")
        return {"domain": canonical, "development": validated}

    # The recipe and production resolution belong to the current, hash-bound
    # domain gate.  Keeping the old .010 recipe here would make a formally
    # accepted prospective recipe (for example .0075 m) impossible to train
    # on: the launcher would reject it before any attempt was registered.  The
    # fixed time window and scoring cadence are task contract fields and remain
    # explicit here.
    recipe_id = domain.get("recipe_id")
    production_resolution = domain.get("production_resolution_m")
    if (domain.get("schema") != "f3.nopen.domain_gate.v1"
            or domain.get("stage") != "domain"
            or domain.get("status") != "passed"
            or not isinstance(recipe_id, str) or not recipe_id
            or isinstance(production_resolution, bool)
            or not isinstance(production_resolution, (int, float))
            or not math.isfinite(production_resolution) or production_resolution <= 0
            or domain.get("time_window_s") != [0, 8.35]
            or domain.get("scoring_interval_s") != .01):
        raise RuntimeError("qualification contract is not a passed F3 NoPen domain gate")
    evidence = domain.get("evidence_sha256")
    if not isinstance(evidence, dict) or not evidence:
        raise RuntimeError("qualification domain gate has no bound evidence")
    for relative, digest in evidence.items():
        path = Path(relative)
        if path.is_absolute() or not relative:
            raise RuntimeError("qualification evidence path must be LAB-relative")
        resolved = (LAB / path).resolve()
        try:
            resolved.relative_to(LAB.resolve())
        except ValueError as error:
            raise RuntimeError("qualification evidence escapes LAB") from error
        if not resolved.is_file() or _sha256(resolved) != digest:
            raise RuntimeError("qualification evidence changed: " + relative)
    from scripts.f3_nopen_development import verify_domain_gate
    canonical = verify_domain_gate()
    if canonical != domain:
        raise RuntimeError("qualification contract differs from the current canonical domain gate")

    development_content = development["content"]
    if (development_content.get("schema") != "f3.training.development_data.v1"
            or development_content.get("status") != "passed"
            or development_content.get("qualified_sources") is not True
            or development_content.get("recipe_id") != recipe_id
            or development_content.get("production_resolution_m") != production_resolution
            or development_content.get("scope") not in ("pilot", "full")):
        raise RuntimeError("development contract is not a passed actual-source contract")
    source_gate = development_content.get("source_domain_gate")
    if not isinstance(source_gate, dict):
        raise RuntimeError("development contract has no source domain gate binding")
    # The contract stores a LAB-relative path; compare it to the bound
    # qualification file after normalizing the caller's absolute path.
    canonical_path = str(Path(qualification["path"]).resolve().relative_to(LAB.resolve()))
    if source_gate.get("path") != canonical_path or source_gate.get("sha256") != qualification["sha256"]:
        raise RuntimeError("development contract is bound to another domain gate")
    from scripts.f3_training_data import validate_development_contract
    validated = validate_development_contract(development["path"])
    if validated != development_content:
        raise RuntimeError("development contract changed during substantive validation")
    return {"domain": canonical, "development": validated}


def _shared_budget():
    # Import lazily so the shared ledger can import training_usage without a cycle.
    from scripts.l1r_continuation_evidence import begin_activity_window, ledger
    begin_activity_window()
    ledger()
    return json.loads((OUT / "RESOURCE-LEDGER.json").read_text())


def _campaign_storage_bytes():
    """Count persisted campaign and training artifacts against the shared cap."""
    roots = (LAB / "campaigns" / "l1-qualification",
             LAB / "campaigns" / "l1-resume")
    return sum(path.stat().st_size for root in roots if root.exists()
               for path in root.rglob("*") if path.is_file())


def _check_shared_totals(shared, usage):
    if shared.get("shared_training_accounting_version") != ACCOUNTING_VERSION:
        raise RuntimeError("shared CFD/training budget integration is not installed")
    if shared.get("gpu_unbounded_attempts", 0):
        raise RuntimeError("unbounded shared GPU attempts require reconciliation")
    gpu_base = _nonnegative(shared["gpu_solver_budget_charge_hours"], "GPU solver base")
    cpu_base = _nonnegative(shared["cpu_base_core_hours_upper_bound"], "CPU base")
    gpu = gpu_base + usage["gpu_budget_charge_hours"]
    cpu = cpu_base + usage["cpu_core_hours_upper_bound"]
    if not math.isclose(_nonnegative(shared["gpu_budget_charge_hours"], "shared GPU total"), gpu, rel_tol=1e-10, abs_tol=1e-10):
        raise RuntimeError("shared GPU total does not include current training charges")
    if not math.isclose(_nonnegative(shared["cpu_core_hours_upper_bound"], "shared CPU total"), cpu, rel_tol=1e-10, abs_tol=1e-10):
        raise RuntimeError("shared CPU total does not include current training charges")
    limits = shared["limits"]
    if gpu > limits["gpu_hours"] or cpu > limits["cpu_core_hours"]:
        raise RuntimeError("shared CPU/GPU budget exhausted")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(shared["conservative_expiry_utc"]):
        raise RuntimeError("campaign expired")
    storage_limit = limits.get("storage_gib")
    if storage_limit is not None and _campaign_storage_bytes() >= storage_limit * 1024**3:
        raise RuntimeError("shared storage budget exhausted")
    return gpu, cpu


def check_training_budget(shared, usage, *, timeout_seconds, cpu_cores):
    """Check one additional attempt against both the training cap and global totals."""
    gpu, cpu = _check_shared_totals(shared, usage)
    if usage["attempts_used"] >= shared["limits"]["training"]:
        raise RuntimeError("training attempt limit exhausted, including failures and resumes")
    reservation = _reservation(timeout_seconds, cpu_cores)
    reservation["cpu_base_growth_reserve_core_hours"] = (
        reservation["gpu_reserved_seconds"] * BASE_CPU_ACTIVITY_CORE_MULTIPLIER / 3600
    )
    if (gpu + reservation["gpu_reserved_seconds"] / 3600 > shared["limits"]["gpu_hours"]
            or cpu + reservation["cpu_reserved_core_hours"] > shared["limits"]["cpu_core_hours"]):
        raise RuntimeError("remaining shared CPU/GPU budget cannot cover the training timeout reserve")
    _check_base_growth_and_expiry(shared, cpu + reservation["cpu_reserved_core_hours"], reservation)
    return reservation


def _check_base_growth_and_expiry(shared, cpu_with_training_reserve, reservation):
    if (cpu_with_training_reserve + reservation["cpu_base_growth_reserve_core_hours"]
            > shared["limits"]["cpu_core_hours"]):
        raise RuntimeError("remaining CPU budget cannot cover continued activity-window growth")
    if (datetime.now(timezone.utc) + timedelta(seconds=reservation["gpu_reserved_seconds"])
            > datetime.fromisoformat(shared["conservative_expiry_utc"])):
        raise RuntimeError("training timeout reserve would extend past campaign expiry")


def _gpu_snapshot(timeout_seconds=GPU_PROBE_TIMEOUT_SECONDS):
    # Same inventory and memory policy as q2, with a bounded external probe so
    # nvidia-smi cannot stall the worker's timeout enforcement.
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,uuid,memory.used,memory.total,memory.free,utilization.gpu",
         "--format=csv,noheader,nounits"],
        cwd=LAB, check=True, text=True, stdout=subprocess.PIPE, timeout=timeout_seconds,
    ).stdout
    rows = []
    for line in output.splitlines():
        index, device_uuid, used, total, free, utilization = [item.strip() for item in line.split(",")]
        rows.append({"index": int(index), "uuid": device_uuid, "memory_used_mib": int(used),
                     "memory_total_mib": int(total), "memory_free_mib": int(free),
                     "utilization_percent": int(utilization)})
    return rows


def _select_gpu(index, *, usage=None):
    policy = _training_gpu_policy()
    if isinstance(index, bool) or index not in policy["gpu_ids"]:
        raise ValueError("requested GPU is outside the authorized training pool")
    row = next((row for row in _gpu_snapshot() if row["index"] == index), None)
    from scripts import l1r_q2_mdbc_bridge as q2
    reserved = 0
    if usage is not None:
        fallback_reservation = GPU_MEMORY_RESERVATION_MIB if policy.get("path") else 0
        reserved = sum((item.get("gpu_memory_reserved_mib") if item.get("gpu_memory_reserved_mib") is not None
                        else fallback_reservation)
                       for item in usage["attempts"]
                       if item.get("status") == "running" and item.get("gpu_index") == index)
    memory_reservation = GPU_MEMORY_RESERVATION_MIB if policy.get("path") else 0
    allowed_uuids = policy["gpu_uuids"] if policy["gpu_uuids"] is not None else set(q2.allowed_gpu_uuids())
    if (row is None or row["uuid"] not in allowed_uuids
            or row["memory_free_mib"] - reserved < q2.LAUNCH_MIN_FREE_MIB + memory_reservation):
        raise RuntimeError("training GPU UUID or launch memory guard failed")
    return {"gpu_index": index, "gpu_uuid": row["uuid"], "launch_snapshot": row,
            "gpu_memory_reserved_mib": memory_reservation,
            "gpu_policy": {"allowed_gpu_indices": list(policy["gpu_ids"]),
                            "allowed_gpu_uuids": sorted(allowed_uuids),
                            "authorization_path": policy.get("path"),
                            "authorization_sha256": policy.get("sha256")}}


def _gpu_guard(index, expected_uuid, *, timeout_seconds=GPU_PROBE_TIMEOUT_SECONDS):
    policy = _training_gpu_policy()
    from scripts import l1r_q2_mdbc_bridge as q2
    row = next((row for row in _gpu_snapshot(timeout_seconds) if row["index"] == index), None)
    if row is None:
        return {"ok": False, "gpu_index": index, "error": "gpu_disappeared"}
    allowed_uuids = policy["gpu_uuids"] if policy["gpu_uuids"] is not None else set(q2.allowed_gpu_uuids())
    uuid_ok = (index in policy["gpu_ids"] and row["uuid"] in allowed_uuids
               and row["uuid"] == expected_uuid)
    return {"ok": uuid_ok and row["memory_free_mib"] >= q2.ABORT_MIN_FREE_MIB,
            "gpu_index": index, **row, "expected_uuid": expected_uuid,
            "abort_below_mib": q2.ABORT_MIN_FREE_MIB}


def _assert_no_solver():
    active = subprocess.run(["pgrep", "-f", "/DualSPHysics5.4_linux64"], capture_output=True,
                            text=True, timeout=GPU_PROBE_TIMEOUT_SECONDS)
    if active.returncode not in (0, 1) or active.stdout.strip():
        raise RuntimeError("another solver is active or process inspection failed")


def _stop_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    # Clean up any descendants still in the group even if the main worker exited.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _resume_binding(logical_run_id, usage, qualification, development, resume_from):
    prior = [row for row in usage["attempts"] if row["logical_run_id"] == logical_run_id]
    if not prior:
        if resume_from is not None:
            raise ValueError("resume requires an existing logical training run")
        return None
    if not isinstance(resume_from, dict):
        raise ValueError("existing logical_run_id requires explicit resume_from")
    source = next((row for row in prior if row["execution_attempt_id"] == resume_from.get("execution_attempt_id")), None)
    if source is None or source["status"] not in ("completed", "failed"):
        raise ValueError("resume source is not a terminal attempt of this logical run")
    for row in prior:
        if (row["qualification_contract"]["sha256"] != qualification["sha256"]
                or row["development_contract"]["sha256"] != development["sha256"]):
            raise ValueError("logical run contracts changed across a resume")
    checkpoint = _bound_file(resume_from.get("checkpoint"), "resume checkpoint")
    return {"execution_attempt_id": source["execution_attempt_id"], "checkpoint": checkpoint}


def run_training(logical_run_id, command, *, qualification_contract, development_contract,
                 timeout_seconds, gpu_index=4, cpu_cores=1, cpu_affinity=None,
                 resume_from=None, cwd=None, env=None):
    """Run one billed execution attempt, once production and shared gates exist.

    command is an argv list, with {output} and {device} substitutions; a resumed
    command may use {resume_checkpoint}. CUDA_VISIBLE_DEVICES is the guarded UUID,
    so {device} is cuda:0. There is no production-gate bypass parameter.
    """
    if not isinstance(logical_run_id, str) or not SAFE_ID.fullmatch(logical_run_id):
        raise ValueError("unsafe logical_run_id")
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(x, str) or not x for x in command):
        raise ValueError("command must be a nonempty argv list")
    policy = _training_gpu_policy()
    if isinstance(gpu_index, bool) or gpu_index not in policy["gpu_ids"]:
        if policy.get("path") is None:
            raise ValueError("training is restricted to physical GPUs 4-7")
        raise ValueError("requested GPU is outside the authorized training pool")
    _reservation(timeout_seconds, cpu_cores)
    qualification = _bound_file(qualification_contract, "qualification contract", read_json=True)
    development = _bound_file(development_contract, "development contract", read_json=True)
    _require_production_contracts(qualification, development)
    taskset = shutil.which("taskset")
    available_cpus = sorted(os.sched_getaffinity(0))
    if taskset is None or len(available_cpus) < cpu_cores:
        raise RuntimeError("requested CPU affinity cannot be enforced")

    # The CFD solver keeps an exclusive lock.  Training takes a shared lock so
    # several low-utilization workers can coexist while solver execution remains
    # mutually exclusive with the whole training group.
    with (OUT / "solver.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("shared solver/training lock is busy") from error
        registration = None
        training_lock = None
        proc = None
        failure = None
        stop_reason = None
        start = None
        partial = None
        record = None
        execution_id = None
        try:
            registration = _registration_lock()
            usage = training_usage()
            stale = [row for row in usage["attempts"]
                     if row.get("status") == "running" and not _running_attempt_is_live(row)]
            if stale:
                raise RuntimeError("unresolved training attempt requires process reconciliation; no automatic relaunch")
            resume = _resume_binding(logical_run_id, usage, qualification, development, resume_from)
            if resume is None and any("{resume_checkpoint}" in item for item in command):
                raise ValueError("resume checkpoint placeholder without a resume source")
            shared = _shared_budget()
            reservation = check_training_budget(shared, usage, timeout_seconds=timeout_seconds, cpu_cores=cpu_cores)
            _assert_no_solver()
            gpu = _select_gpu(gpu_index, usage=usage)
            disk = shutil.disk_usage(LAB)
            if disk.free < max(100 * 1024**3, .1 * disk.total):
                raise RuntimeError("disk reserve")

            used_cpus = {core for row in usage["attempts"] if row.get("status") == "running"
                         for core in row.get("cpu_affinity", [])}
            if cpu_affinity is None:
                affinity = [core for core in available_cpus if core not in used_cpus][:cpu_cores]
                if len(affinity) != cpu_cores:
                    raise RuntimeError("no disjoint CPU affinity is available")
            else:
                if (not isinstance(cpu_affinity, (list, tuple))
                        or len(cpu_affinity) != cpu_cores
                        or len(set(cpu_affinity)) != len(cpu_affinity)
                        or any(core not in available_cpus for core in cpu_affinity)):
                    raise ValueError("cpu_affinity must be a unique allowed CPU subset")
                affinity = list(cpu_affinity)

            execution_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:12]
            partial = TRAINING_ROOT / logical_run_id / (execution_id + ".partial")
            partial.mkdir(parents=True, exist_ok=False)
            TRAINING_LOCK_ROOT.mkdir(parents=True, exist_ok=True)
            training_lock_path = TRAINING_LOCK_ROOT / (execution_id + ".lock")
            training_lock = training_lock_path.open("a")
            fcntl.flock(training_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            worker_command = [item.replace("{output}", str(partial)).replace("{device}", "cuda:0") for item in command]
            if resume:
                worker_command = [item.replace("{resume_checkpoint}", resume["checkpoint"]["path"]) for item in worker_command]
            actual_command = [taskset, "--cpu-list", ",".join(map(str, affinity)), *worker_command]
            worker_env = os.environ.copy()
            worker_env.update(env or {})
            worker_env.update({"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": gpu["gpu_uuid"],
                               "NVIDIA_VISIBLE_DEVICES": gpu["gpu_uuid"], "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
                               "OMP_NUM_THREADS": str(cpu_cores),
                               "OPENBLAS_NUM_THREADS": str(cpu_cores), "MKL_NUM_THREADS": str(cpu_cores)})
            record = {"schema": ATTEMPT_SCHEMA, "resource_category": "training",
                      "logical_run_id": logical_run_id, "execution_attempt_id": execution_id,
                      "status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                      "elapsed_seconds": None, "timeout_seconds": float(timeout_seconds),
                      "termination_grace_seconds": TERMINATION_GRACE_SECONDS,
                      "cpu_cores": cpu_cores, "cpu_affinity": affinity, **reservation, **gpu,
                      "qualification_contract": {k: v for k, v in qualification.items() if k != "content"},
                      "development_contract": {k: v for k, v in development.items() if k != "content"},
                      "resume_from": resume, "command": actual_command, "cwd": str(Path(cwd or LAB).resolve()),
                      "inherited_solver_lock_fd": lock.fileno(), "solver_lock_mode": "shared",
                      "training_lock_path": str(training_lock_path.resolve()),
                      "inherited_training_lock_fd": training_lock.fileno(),
                      "shared_accounting_version": ACCOUNTING_VERSION,
                      "budget_before": {"gpu_hours": shared["gpu_budget_charge_hours"],
                                        "cpu_core_hours": shared["cpu_core_hours_upper_bound"],
                                        "training_attempts_used": usage["attempts_used"]},
                      "elapsed_scope": "Popen invocation through owned process-group cleanup; prelaunch bookkeeping remains in shared base CPU",
                      "completion_scope": "worker process exit only; model quality and recovery correctness require the training driver",
                      "storage_policy": {
                          "scope": "external_immutable_archive",
                          "archive_root": str(TRAINING_ROOT.resolve()),
                          "campaign_storage_exempt": True,
                      }}
            _atomic_json(partial / "attempt.json", record)
            # Recheck the shared ledger after the running record is visible, then
            # spawn while the registration lock still excludes other launchers.
            refreshed = _shared_budget()
            _, cpu_with_reserve = _check_shared_totals(refreshed, training_usage())
            _check_base_growth_and_expiry(refreshed, cpu_with_reserve, reservation)
            with (partial / "worker.stdout.log").open("wb") as log:
                start = time.monotonic()
                proc = subprocess.Popen(actual_command, cwd=record["cwd"], env=worker_env,
                                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                        pass_fds=(lock.fileno(), training_lock.fileno()))
                record["pid"] = proc.pid
                record["process_group_id"] = proc.pid
                _atomic_json(partial / "attempt.json", record)
            registration.close()
            registration = None
            while proc.poll() is None:
                remaining = timeout_seconds - (time.monotonic() - start)
                if remaining <= 0:
                    stop_reason = "timeout"
                    break
                guard = _gpu_guard(gpu_index, gpu["gpu_uuid"],
                                   timeout_seconds=min(GPU_PROBE_TIMEOUT_SECONDS, remaining))
                if not guard or not guard.get("ok", False):
                    record["resource_guard"] = guard
                    stop_reason = "gpu_guard"
                    break
                time.sleep(min(POLL_SECONDS, max(.001, timeout_seconds - (time.monotonic() - start))))
        except BaseException as error:
            failure = error
            stop_reason = "exception"
            if record is not None:
                record["error"] = repr(error)
        finally:
            if registration is not None:
                registration.close()
            if proc is not None:
                _stop_group(proc)
            if partial is not None and record is not None and partial.exists():
                elapsed = time.monotonic() - start if start is not None else 0.0
                returncode = proc.returncode if proc is not None else None
                success = proc is not None and returncode == 0 and stop_reason is None
                status = "completed" if success else "failed"
                final = partial.with_name(execution_id + (".complete" if success else ".failed"))
                record.update(status=status, finished_at_utc=datetime.now(timezone.utc).isoformat(),
                              elapsed_seconds=elapsed, returncode=returncode,
                              stop_reason=stop_reason or (None if success else "worker_exit"),
                              attempt_directory=str(final))
                record["artifact_manifest"] = _write_artifact_manifest(partial)
                _atomic_json(partial / "attempt.json", record)
                os.replace(partial, final)
            if training_lock is not None:
                training_lock.close()
            if record is not None:
                with _registration_lock() as final_registration:
                    _shared_budget()
        if failure is not None:
            raise failure
        return record
