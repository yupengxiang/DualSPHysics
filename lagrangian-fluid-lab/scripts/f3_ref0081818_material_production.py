"""Run the three bounded ref0081818 material configurations.

The module is deliberately inert on import.  ``freeze_plan``/``plan`` only
write an immutable, hash-bound material plan; ``run_one`` is the explicit
single-configuration entry point.  Every attempt consumes one material
configuration charge before its worker is started, including failed and
interrupted attempts.  Results are material *candidates* only: this runner
never sets a T2 qualification or formal-release flag.

The numerical back-end is the already reviewed implementation in
``f3_material_reference``: its fixed 512 seeds, exact-window alignment and
passive-tracer/Shepard diagnostic path are reused without source-particle
identity shortcuts.  Ref008 gate/authentication is checked before a plan is
frozen or an attempt is registered.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
from typing import Any

import numpy as np

if __package__ in (None, ""):  # pragma: no cover - direct CLI invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_material_reference as material_backend
from scripts import f3_nopen_stage_score as source_score
from scripts import f3_ref0081818_material_reference as adapter
from scripts import passive_tracers
from scripts.f3_material_reference_score import label_trace
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_cpu_slots import cpu_slot


PLAN_NAME = "F3-REF0081818-MATERIAL-PRODUCTION-PLAN.json"
PLAN_SCHEMA = "f3.ref0081818.material_production_plan.v1"
ATTEMPT_SCHEMA = "f3.material.reference_attempt.v1"
RESULT_SCHEMA = "f3.ref0081818.material_candidate.v1"
PRODUCTION_PLAN_CASE = "NP05"
GRACE_SECONDS = 5.0

# These values are intentionally aliases of the revision-bound adapter.  The
# downstream preflight reserves exactly three configurations alongside the six
# training runs, so changing one side silently would invalidate the approval.
MATERIAL_TIMEOUT_SECONDS = adapter.MATERIAL_TIMEOUT_SECONDS
MATERIAL_POSTPROCESS_RESERVE_SECONDS = adapter.MATERIAL_POSTPROCESS_RESERVE_SECONDS
MATERIAL_CPU_ACTIVITY_CORES = adapter.MATERIAL_CPU_ACTIVITY_CORES
MATERIAL_STORAGE_MULTIPLIER = adapter.MATERIAL_STORAGE_MULTIPLIER

SUPPORT = dict(material_backend.SUPPORT)
DIAGNOSTICS = tuple(material_backend.DIAGNOSTICS)
# Public wrappers make the reused reviewed primitives explicit and keep the
# worker easy to fixture in tests without replacing the whole legacy module.
def frozen_seeds() -> dict[str, np.ndarray]:
    return material_backend.frozen_seeds()


def align_source(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return material_backend.align_source(*args, **kwargs)


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _relative(path: str | Path) -> str:
    return str(Path(path).resolve().relative_to(LAB.resolve()))


def _path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (LAB / path).resolve()
    resolved.relative_to(LAB.resolve())
    return resolved


def _fingerprint(path: str | Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": _relative(path), "sha256": sha256(path)}


def _assert_digest(path: str | Path, expected: str, message: str) -> None:
    path = Path(path)
    if not path.is_file() or sha256(path) != expected:
        raise ValueError(message + ": " + str(path))


def _jsonable(value: Any) -> Any:
    """Convert source evidence and numpy values to strict JSON values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _material_configs() -> list[dict[str, Any]]:
    rows = [dict(row) for row in adapter.configurations(adapter.PRODUCTION_CASE)]
    expected = [
        "REF008-0075-NOMINAL-s2",
        "REF008-0075-NOMINAL-s4",
        "REF008-0075-CADENCE-s4",
    ]
    if [row.get("config_id") for row in rows] != expected or len(rows) != 3:
        raise ValueError("ref008 material scope must contain the registered three configurations")
    for row in rows:
        if (row.get("source_case_id") != adapter.PRODUCTION_CASE
                or row.get("dp_m") != adapter.PRODUCTION_DP_M
                or row.get("amplitude") != 1.0
                or row.get("output_interval_s") not in (0.01, 0.002)
                or row.get("substeps") not in (2, 4)):
            raise ValueError("material configuration is outside the ref008 registered domain")
    return rows


def verify_authorization() -> dict[str, Any]:
    """Verify the enabled gate, downstream owner auth and material scope."""
    gate, score, score_path = adapter.verify_revision_gate(require_material=True)
    auth_rel = gate.get("downstream_authorization_path")
    auth_digest = gate.get("downstream_authorization_sha256")
    if not isinstance(auth_rel, str) or not isinstance(auth_digest, str):
        raise PermissionError("ref008 downstream authorization binding is missing")
    auth_path = _path(auth_rel)
    _assert_digest(auth_path, auth_digest, "ref008 downstream authorization changed")
    auth = _read(auth_path)
    if (auth.get("schema") != "f3.revision075.ref0081818.downstream_owner_authorization.v1"
            or auth.get("status") != "owner_authorized"
            or auth.get("recipe_id") != adapter.RECIPE
            or auth.get("owner_reply") != "我批准"):
        raise PermissionError("ref008 downstream owner authorization is not valid")
    material = auth.get("material")
    configs = _material_configs()
    expected_ids = [row["config_id"] for row in configs]
    if (not isinstance(material, dict) or material.get("allowed") is not True
            or material.get("configuration_count") != len(expected_ids)
            or material.get("configuration_ids") != expected_ids):
        raise PermissionError("downstream authorization does not approve the ref008 material scope")
    limits_path = OUT / "RESOURCE-LIMITS.json"
    limits = _read(limits_path).get("limits", {})
    auth_limits = auth.get("resource_limits", {})
    expected_limits = {
        "cpu_core_hours": limits.get("cpu_core_hours"),
        "gpu_hours": limits.get("gpu_hours"),
        "qualification_attempts": limits.get("qualification"),
        "development_attempts": limits.get("development"),
        "material_configurations": limits.get("materials"),
        "training_attempts": limits.get("training"),
    }
    if any(auth_limits.get(key) != value for key, value in expected_limits.items()):
        raise PermissionError("downstream authorization resource limits differ from current limits")
    # The auth record is the owner decision.  Its proposal is also hash-bound,
    # but the proposal intentionally predates the gate update, so do not demand
    # that its old gate digest equal the now-enabled gate digest.
    proposal = auth.get("preflight")
    if not isinstance(proposal, dict) or not isinstance(proposal.get("path"), str):
        raise PermissionError("downstream authorization has no bound preflight")
    proposal_path = _path(proposal["path"])
    _assert_digest(proposal_path, proposal.get("sha256", ""),
                   "downstream preflight changed")
    return {
        "gate": gate,
        "score": score,
        "score_path": score_path,
        "gate_path": _path(OUT / adapter.GATE_NAME),
        "auth": auth,
        "auth_path": auth_path,
        "proposal_path": proposal_path,
        "configurations": configs,
    }


def _source(bindings: dict[str, str]) -> dict[str, Any]:
    """Load the immutable .0075 m source with its native timestep evidence."""
    source = source_score._source(PRODUCTION_PLAN_CASE, bindings)
    if source.get("case_id") != adapter.PRODUCTION_CASE:
        raise ValueError("source scorer selected a different production source")
    entry = source.get("entry", {})
    if (entry.get("dp_m") != adapter.PRODUCTION_DP_M
            or entry.get("amplitude") != 1.0
            or entry.get("output_interval_s") != adapter.OUTPUT_INTERVAL_S
            or entry.get("time_window_s") != [0, adapter.HORIZON_S]):
        raise ValueError("native source does not match the ref008 material recipe")
    return source


def _bind(path: Path, bindings: dict[str, str], expected: str | None = None) -> None:
    digest = sha256(path)
    if expected is not None and digest != expected:
        raise ValueError("changed ref008 material evidence: " + _relative(path))
    bindings[_relative(path)] = digest


def _source_evidence(authz: dict[str, Any], source_bindings: dict[str, str]) -> dict[str, str]:
    bindings = dict(source_bindings)
    for path in (authz["gate_path"], authz["auth_path"], authz["score_path"], authz["proposal_path"]):
        _bind(Path(path), bindings)
    return bindings


def _source_summary(source: dict[str, Any]) -> dict[str, Any]:
    # Keep enough metadata for the worker to call the reviewed alignment
    # backend, while avoiding arbitrary paths or non-JSON numpy objects.
    value = _jsonable(source)
    path = _path(value["hdf5_path"])
    value["hdf5_path"] = _relative(path)
    return value


def _plan_value(authz: dict[str, Any]) -> dict[str, Any]:
    source_bindings: dict[str, str] = {}
    source = _source(source_bindings)
    bindings = _source_evidence(authz, source_bindings)
    seeds = {key: _jsonable(value) for key, value in frozen_seeds().items()}
    seed_digest = hashlib.sha256(
        json.dumps(seeds, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    configs = _material_configs()
    code = {
        "runner_sha256": sha256(Path(__file__)),
        "adapter_sha256": sha256(Path(adapter.__file__)),
        "backend_sha256": sha256(Path(material_backend.__file__)),
        "material_score_sha256": sha256(Path(material_backend.__file__).parent / "f3_material_reference_score.py"),
        "passive_tracers_sha256": sha256(LAB / "scripts/passive_tracers.py"),
        "material_neighbors_sha256": sha256(LAB / "scripts/f3_material_neighbors.py"),
    }
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "frozen",
        "launch": False,
        "recipe_id": adapter.RECIPE,
        "qualification_gate": _fingerprint(authz["gate_path"]),
        "downstream_authorization": _fingerprint(authz["auth_path"]),
        "downstream_preflight": _fingerprint(authz["proposal_path"]),
        "score_report": _fingerprint(authz["score_path"]),
        "production_source_case_id": adapter.PRODUCTION_CASE,
        "production_resolution_m": adapter.PRODUCTION_DP_M,
        "time_window_s": [0.0, adapter.HORIZON_S],
        "coordinate_frame": adapter.COORDINATE_FRAME,
        "control_domain": adapter.CONTROL_DOMAIN,
        "output_intervals_s": [0.01, 0.002],
        "neighbours": 24,
        "regularization_m": 0.004,
        "maximum_support_distance_m": 0.03,
        "support_gate": SUPPORT,
        "seed_design": seeds,
        "seed_design_sha256": seed_digest,
        "seed_rule": "independent fixed 16x8x4 equal-volume points; not source particle identities",
        "configurations": configs,
        "source": _source_summary(source),
        "source_evidence_sha256": bindings,
        "code_sha256": code,
        "configuration_charge": 0,
        "planned_configuration_count": len(configs),
        "candidate_only": True,
        "qualified_T2_macro": False,
        "qualified_T2_path": False,
        "formal_release": False,
        "quadrature_status": "pending; no post-result selection",
        "matrix_coverage_status": "not_evaluated",
        "resource_policy": {
            "timeout_seconds": MATERIAL_TIMEOUT_SECONDS,
            "postprocess_reserve_seconds": MATERIAL_POSTPROCESS_RESERVE_SECONDS,
            "cpu_activity_cores": MATERIAL_CPU_ACTIVITY_CORES,
            "gpu_hours_reserved": 0.0,
            "training_logical_runs_bound": 6,
        },
    }
    return plan


def build_plan() -> dict[str, Any]:
    """Build the frozen plan without writing it."""
    return _plan_value(verify_authorization())


def freeze_plan(path: str | Path | None = None) -> dict[str, Any]:
    """Freeze the exact material matrix, refusing replacement of a plan."""
    target = Path(path) if path is not None else OUT / PLAN_NAME
    target = target.resolve()
    target.relative_to(LAB.resolve())
    value = build_plan()
    if target.exists():
        if _read(target) != value:
            raise ValueError("existing ref008 material plan differs; refusing replacement")
        return value
    atomic_json(target, value)
    return value


def plan(path: str | Path | None = None) -> dict[str, Any]:
    """Public alias for :func:`freeze_plan`."""
    return freeze_plan(path)


def register(path: str | Path | None = None) -> dict[str, Any]:
    """Compatibility name for callers that register frozen material plans."""
    return freeze_plan(path)


def _source_from_plan(value: dict[str, Any]) -> dict[str, Any]:
    source = _jsonable(value["source"])
    source["hdf5_path"] = _path(source["hdf5_path"])
    return source


def verify_plan(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    path.relative_to(LAB.resolve())
    value = _read(path)
    if value.get("schema") != PLAN_SCHEMA or value.get("status") != "frozen":
        raise ValueError("material plan is not frozen")
    expected = build_plan()
    if value != expected:
        raise ValueError("material plan, gate/auth, source or code binding changed")
    seeds = value.get("seed_design", {})
    if hashlib.sha256(json.dumps(seeds, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != value.get("seed_design_sha256"):
        raise ValueError("material seed design digest changed")
    if value.get("candidate_only") is not True or value.get("qualified_T2_macro") is not False or value.get("qualified_T2_path") is not False or value.get("formal_release") is not False:
        raise ValueError("material plan cannot enable qualification or release")
    if value.get("configuration_charge") != 0 or len(value.get("configurations", [])) != 3:
        raise ValueError("frozen material plan has an invalid configuration charge or count")
    return value


def _reserve_bytes(config: dict[str, Any], source: dict[str, Any]) -> int:
    frames = round(adapter.HORIZON_S / float(config["output_interval_s"])) + 1
    particle_count = int(source["audit"]["particle_axis_count"])
    return int(frames * (particle_count * 64 + 512 * 256) * MATERIAL_STORAGE_MULTIPLIER)


def resource_preflight(timeout_seconds: float, reserve_bytes: int, *, configuration_count: int = 1) -> dict[str, Any]:
    """Reserve one attempt's CPU/material/storage budget without launching."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    if reserve_bytes < 0 or configuration_count < 1:
        raise ValueError("invalid material resource reserve")
    from scripts import l1r_continuation_evidence as resources

    resources.begin_activity_window()
    resources.ledger()
    ledger = _read(OUT / "RESOURCE-LEDGER.json")
    limits = resources.resource_limits()
    used = resources.material_usage()
    seconds = timeout_seconds + GRACE_SECONDS + MATERIAL_POSTPROCESS_RESERVE_SECONDS
    cpu_reserve = seconds * MATERIAL_CPU_ACTIVITY_CORES / 3600.0 * configuration_count
    if used + configuration_count > limits["materials"]:
        raise RuntimeError("material configuration cap includes failed and incomplete attempts")
    if float(ledger["cpu_core_hours_upper_bound"]) + cpu_reserve > limits["cpu_core_hours"]:
        raise RuntimeError("CPU timeout reserve exceeds the remaining activity budget")
    expiry = ledger.get("conservative_expiry_utc")
    if expiry and datetime.now(timezone.utc) + timedelta(seconds=seconds) > datetime.fromisoformat(expiry):
        raise RuntimeError("material timeout exceeds campaign expiry")
    total = sum(
        p.stat().st_size
        for name in ("l1-qualification", "l1-resume")
        for p in (LAB / "campaigns" / name).rglob("*")
        if p.is_file()
    )
    if total + reserve_bytes > limits["storage_gib"] * 1024**3:
        raise RuntimeError("material output reserve exceeds campaign storage cap")
    disk = shutil.disk_usage(LAB)
    if disk.free - reserve_bytes < max(100 * 1024**3, 0.1 * disk.total):
        raise RuntimeError("material output violates physical disk reserve")
    return {
        "status": "passed",
        "material_used": used,
        "cpu_core_hours": float(ledger["cpu_core_hours_upper_bound"]),
        "cpu_forward_reserve_core_hours": cpu_reserve,
        "timeout_seconds": timeout_seconds,
        "postprocess_reserve_seconds": MATERIAL_POSTPROCESS_RESERVE_SECONDS,
        "cpu_activity_cores": MATERIAL_CPU_ACTIVITY_CORES,
        "output_reserve_bytes": reserve_bytes,
        "campaign_storage_bytes": total,
        "configuration_count": configuration_count,
        "gpu_hours_reserved": 0.0,
        "limits": limits,
    }


def _worker(payload_path: str | Path) -> None:
    payload_path = Path(payload_path).resolve()
    payload = _read(payload_path)
    attempt = _read(payload["attempt_record_path"])
    if (attempt.get("schema") != ATTEMPT_SCHEMA
            or attempt.get("status") != "running"
            or attempt.get("configuration_charge") != 1
            or attempt.get("payload_sha256") != sha256(payload_path)
            or attempt.get("controller_pid") != os.getppid()
            or attempt.get("directory") != payload.get("directory")
            or attempt.get("configuration") != payload.get("configuration")
            or attempt.get("plan", {}).get("sha256") != payload.get("plan_sha256")):
        raise ValueError("worker lacks a current charged registration from its controller")
    plan_value = verify_plan(payload["plan_path"])
    if sha256(payload["plan_path"]) != payload.get("plan_sha256"):
        raise ValueError("worker plan differs from charged registration")
    cfg = payload.get("configuration")
    if cfg not in plan_value["configurations"]:
        raise ValueError("worker configuration is outside the frozen ref008 matrix")
    source_score._verify_bindings(payload["source_evidence_sha256"])
    source = _source_from_plan(plan_value)
    folder = Path(payload["directory"])
    folder.mkdir(parents=True, exist_ok=True)
    alignment = align_source(source, folder / "aligned.h5",
                             step_s=float(cfg["output_interval_s"]))
    triangles = passive_tracers.box_surface_triangles(
        [-.45, -.09, 0.0], [.45, .09, .51],
        sides=("xmin", "xmax", "ymin", "ymax", "zmin"),
    )
    seeds = frozen_seeds()
    from scripts.f3_material_neighbors import shepard_velocity_with_diagnostics

    trace = passive_tracers.advect_hdf5(
        alignment["path"], seeds["initial_position"], neighbours=24,
        regularization=.004, maximum_support_distance=.03,
        substeps_per_interval=int(cfg["substeps"]),
        barrier_provider=lambda h, a, b, t: triangles,
        support_gate=SUPPORT,
        velocity_interpolator=shepard_velocity_with_diagnostics,
    )
    expected_shape = (int(alignment["target_count"]) - 1, len(seeds["initial_position"]))
    for field in DIAGNOSTICS:
        if field not in trace or np.asarray(trace[field]).shape != expected_shape:
            raise ValueError("tracer omitted complete support/failure diagnostics: " + field)
    expected_time = source_score.target_grid(float(cfg["output_interval_s"]))
    if not np.array_equal(trace["time"], expected_time):
        raise ValueError("tracer changed the full aligned ref008 time axis")
    labels = label_trace(trace, seeds)
    arrays = {
        key: np.asarray(json.dumps(value, sort_keys=True) if isinstance(value, dict) else value)
        for key, value in labels.items()
    }
    if any(value.dtype.kind == "O" for value in arrays.values()):
        raise ValueError("material bundle must not require pickle")
    arrays["mass_weight_kg"] = seeds["mass_fraction"] * float(source["audit"]["initial_fluid_mass_kg"])
    arrays["boundary_triangles_m"] = triangles
    artifact = folder / "material.npz"
    partial = artifact.with_name(artifact.name + ".partial")
    with partial.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    os.replace(partial, artifact)
    current_code = {
        "runner_sha256": sha256(Path(__file__)),
        "adapter_sha256": sha256(Path(adapter.__file__)),
        "backend_sha256": sha256(Path(material_backend.__file__)),
        "material_score_sha256": sha256(Path(material_backend.__file__).parent / "f3_material_reference_score.py"),
        "passive_tracers_sha256": sha256(LAB / "scripts/passive_tracers.py"),
        "material_neighbors_sha256": sha256(LAB / "scripts/f3_material_neighbors.py"),
    }
    if current_code != plan_value["code_sha256"]:
        raise ValueError("material implementation changed during execution")
    result = {
        "schema": RESULT_SCHEMA,
        "status": "candidate",
        "candidate_only": True,
        "config_id": cfg["config_id"],
        "configuration": cfg,
        "alignment": alignment,
        "material": {"path": str(artifact.resolve()), "sha256": sha256(artifact)},
        "source_evidence_sha256": payload["source_evidence_sha256"],
        "initial_fluid_mass_kg": float(source["audit"]["initial_fluid_mass_kg"]),
        "seed_count": len(seeds["initial_position"]),
        "frame_count": len(trace["time"]),
        "code_sha256": current_code,
        "quadrature_status": "pending",
        "matrix_coverage_status": "not_evaluated",
        "qualified_T2_macro": False,
        "qualified_T2_path": False,
        "formal_release": False,
        "event_semantics": "saved-frame linear crossing; observed/valid_no_event/censored; historical observed arrivals survive later failure",
    }
    atomic_json(folder / "result.json", result)


def worker(payload_path: str | Path) -> None:
    """Public explicit worker entry point; never callable without a charge."""
    _worker(payload_path)


def _run_process(command: list[str], folder: Path, timeout_seconds: float,
                 env: dict[str, str], *, on_spawn=None) -> None:
    with (folder / "worker.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=LAB, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        code = None
        try:
            if on_spawn is not None:
                on_spawn(process.pid)
            code = process.wait(timeout=timeout_seconds)
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            except ProcessLookupError:
                pass
    if code != 0:
        raise RuntimeError("material worker failed; inspect retained worker.log")


def run_one(config_id: str, *, timeout_seconds: float = MATERIAL_TIMEOUT_SECONDS,
            plan_path: str | Path | None = None, retry_of: str | None = None) -> dict[str, Any]:
    """Charge and run exactly one material configuration."""
    authz = verify_authorization()
    path = Path(plan_path).resolve() if plan_path is not None else OUT / PLAN_NAME
    plan_value = verify_plan(path)
    configs = {row["config_id"]: row for row in plan_value["configurations"]}
    if config_id not in configs:
        raise ValueError("unknown frozen ref008 material configuration")
    cfg = configs[config_id]
    source = _source_from_plan(plan_value)
    source_score._verify_bindings(plan_value["source_evidence_sha256"])
    taskset = shutil.which("taskset")
    if taskset is None:
        raise RuntimeError("CPU affinity enforcement is unavailable")
    affinity = min(os.sched_getaffinity(0))
    with cpu_slot():
        with (OUT / "material-registration.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            prior = [
                _read(p) for p in OUT.glob(f"F3-MATERIAL-REFERENCE-{config_id}-*.json")
            ]
            if any(row.get("status") != "failed" for row in prior):
                raise RuntimeError("configuration is running or completed; do not automatically relaunch")
            failed = [row for row in prior if row.get("status") == "failed"]
            if failed and retry_of not in {row.get("execution_attempt_id") for row in failed}:
                raise ValueError("failed material configuration requires explicit retry_of")
            if not failed and retry_of is not None:
                raise ValueError("retry_of has no prior failed material attempt")
            reserve = resource_preflight(timeout_seconds, _reserve_bytes(cfg, source))
            execution = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:10]
            folder = (LAB / "campaigns/l1-resume/data/f3-material-reference" / execution).resolve()
            folder.relative_to(LAB.resolve())
            folder.mkdir(parents=True, exist_ok=False)
            record_path = OUT / f"F3-MATERIAL-REFERENCE-{config_id}-{execution}.json"
            payload = {
                "plan_path": str(path),
                "plan_sha256": sha256(path),
                "configuration": cfg,
                "source": source,
                "source_evidence_sha256": plan_value["source_evidence_sha256"],
                "directory": str(folder),
                "attempt_record_path": str(record_path.resolve()),
            }
            atomic_json(folder / "payload.json", _jsonable(payload))
            record = {
                "schema": ATTEMPT_SCHEMA,
                "status": "running",
                "resource_category": "material",
                "backend": "cpu",
                "configuration_charge": 1,
                "execution_attempt_id": execution,
                "config_id": config_id,
                "retry_of": retry_of,
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": None,
                "timeout_seconds": timeout_seconds,
                "cpu_cores": 1,
                "cpu_affinity": [affinity],
                "cpu_budget": reserve,
                "configuration": cfg,
                "plan": _fingerprint(path),
                "authorization": _fingerprint(authz["auth_path"]),
                "source_evidence_sha256": plan_value["source_evidence_sha256"],
                "code_sha256": plan_value["code_sha256"],
                "controller_pid": os.getpid(),
                "payload_sha256": sha256(folder / "payload.json"),
                "directory": str(folder),
                "candidate_only": True,
                "qualified_T2_macro": False,
                "qualified_T2_path": False,
                "formal_release": False,
            }
            atomic_json(record_path, record)
        start = time.monotonic()
        try:
            env = os.environ.copy()
            env.update(
                OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="void",
                LAGRANGIAN_TRACER_TORCH_THREADS="1", LAGRANGIAN_TRACER_TORCH_DEVICE="cpu",
            )
            command = [taskset, "--cpu-list", str(affinity), sys.executable, "-m",
                       "scripts.f3_ref0081818_material_production", "--worker",
                       str(folder / "payload.json")]
            record["command"] = command
            atomic_json(record_path, record)

            def spawned(pid: int) -> None:
                record.update(worker_pid=pid, process_group_id=pid)
                atomic_json(record_path, record)

            _run_process(command, folder, timeout_seconds, env, on_spawn=spawned)
            result_path = folder / "result.json"
            result = _read(result_path)
            if (result.get("schema") != RESULT_SCHEMA
                    or result.get("status") != "candidate"
                    or result.get("candidate_only") is not True
                    or result.get("qualified_T2_macro") is not False
                    or result.get("qualified_T2_path") is not False
                    or result.get("formal_release") is not False):
                raise ValueError("worker cannot publish material qualification or release")
            for ref in (result.get("material"), result.get("alignment")):
                if not isinstance(ref, dict) or sha256(ref["path"]) != ref["sha256"]:
                    raise ValueError("material worker output hash mismatch")
            record.update(status="completed", result=_fingerprint(result_path))
        except BaseException as error:
            record.update(status="failed", error=repr(error))
            raise
        finally:
            record.update(elapsed_seconds=time.monotonic() - start,
                          finished_at_utc=datetime.now(timezone.utc).isoformat())
            atomic_json(record_path, record)
            from scripts import l1r_continuation_evidence as resources
            resources.ledger()
    return record


def preflight() -> dict[str, Any]:
    """Return the frozen launch proposal without creating a worker or charge."""
    value = build_plan()
    source = _source_from_plan(value)
    reserves = {
        row["config_id"]: {
            "output_reserve_bytes": _reserve_bytes(row, source),
            "cpu_core_hours": (MATERIAL_TIMEOUT_SECONDS + GRACE_SECONDS
                                + MATERIAL_POSTPROCESS_RESERVE_SECONDS)
            * MATERIAL_CPU_ACTIVITY_CORES / 3600.0,
        }
        for row in value["configurations"]
    }
    return {
        "status": "ready",
        "launch": False,
        "solver_runs": 0,
        "material_configurations_charged": 0,
        "configuration_count": len(value["configurations"]),
        "plan": value,
        "reserve_by_configuration": reserves,
        "candidate_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("plan")
    sub.add_parser("preflight")
    run = sub.add_parser("run")
    run.add_argument("config_id")
    run.add_argument("--retry-of")
    run.add_argument("--timeout-seconds", type=float, default=MATERIAL_TIMEOUT_SECONDS)
    worker = sub.add_parser("worker")
    worker.add_argument("payload", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            value = plan()
        elif args.action == "preflight":
            value = build_plan()
            value["launch"] = False
            value["worker_runs"] = 0
        elif args.action == "run":
            value = run_one(args.config_id, timeout_seconds=args.timeout_seconds,
                            retry_of=args.retry_of)
        else:
            worker(args.payload)
            value = {"status": "completed"}
        print(json.dumps(value, indent=2, ensure_ascii=False))
    except (PermissionError, ValueError, RuntimeError, FileNotFoundError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
