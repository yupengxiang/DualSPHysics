#!/usr/bin/env python3
"""Build a static, fail-closed proposal for the F3 coarse material candidate.

This module is deliberately a proposal builder, not a launcher.  It reads
source bytes only to compute a binding hash and reads JSON metadata/contracts;
it never opens an HDF5 file, imports ``core_material``, calls ``core_runtime``,
creates an attempt directory, or produces a material trace.  A later launch
would still require a fresh root/scheduler authorization and a measured host
I/O admission record.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f3.coarse.proposal.v1"
CREATED_AT = "2026-09-28"

CANDIDATE_ID = "CORE-F3-MATERIAL-COARSE-s2"
JOB_ID = "core-f3-material-coarse-s2"

CORE_MATERIAL = Path("scripts/core_material.py")
CORE_RUNTIME = Path("scripts/core_runtime.py")
NEIGHBOUR_CODE = Path("scripts/f3_material_neighbors.py")
PASSIVE_TRACER_CODE = Path("scripts/passive_tracers.py")
SOURCE_H5 = Path("campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5")
SOURCE_AUDIT = Path("campaigns/l1-resume/continuation/R0081818-NOMINAL-AUDIT.json")
SOURCE_PREPARED = Path("campaigns/l1-resume/continuation/R0081818-NOMINAL-PREPARED.json")
REVISION_MANIFEST = Path("diagnostics/f3-audit/F3-075-REF0081818-MANIFEST.json")
RUNTIME_SPEC = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-qualification-diagnostic-runtime-spec-2026-09-19.json"
)
QUEUE_REGISTRATION = Path(
    "campaigns/core-v1/material/evidence/diagnostic-queue-registration.json"
)
JOB_SPEC = Path("campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json")
HISTORICAL_PROPOSAL = Path("reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
RERUN_PROPOSAL = Path("reports/F3-MATERIAL-COARSE-PROPOSAL-2026-09-29-RERUN1.json")

EXPECTED_CORE_MATERIAL_SHA256 = (
    "9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e"
)
EXPECTED_SOURCE_SHA256 = (
    "3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575"
)
EXPECTED_JOB_SPEC_SHA256 = (
    "1f1080e497feab414863e3e02dd31dbec91c0d09e4ef9ac855e0cdbbda070628"
)
EXPECTED_SOURCE_AUDIT_SHA256 = (
    "eff6e351eaeb6ec270a2ec9883a15d0fbea1c04bd57c213e94db4cd0c90d6c11"
)
EXPECTED_SOURCE_PREPARED_SHA256 = (
    "043febcc4e2deb9c515ed32fe99b8ed7241c68fa8dbf72b9ad8d1f7e5ef6684f"
)
EXPECTED_REVISION_MANIFEST_SHA256 = (
    "0d4cbd7d22daaff864bccb82e57348631e0a057a3465490a6bbc19e67c0aa078"
)
EXPECTED_RUNTIME_SPEC_SHA256 = (
    "06c2d549d971d679f48b0d46480a7decc64d1ab58a3e35ece8cb5a61a04a1aa9"
)
EXPECTED_QUEUE_REGISTRATION_SHA256 = (
    "71ce17d5421d27dde2f849f7d1b3a226bfa0e6b275440f10f45eb0ec9a9da2cc"
)

OLD_RUNTIME_CORE_MATERIAL_SHA256 = (
    "1880c02a50168ae3325c39993a55103a1ebba06adcc48a486b7f6f4825d94b7e"
)

CHECKPOINT_FIELDS = (
    "position",
    "reliable",
    "first_passage",
    "return_time",
    "residence",
    "residence_left",
    "residence_right",
    "returned",
)
MATERIAL_METRIC_FIELDS = (
    "task",
    "source_definition",
    "by_source",
    "mass_closed",
    "unknown_gate_pass",
    "unknown_fraction_monotone",
    "common_reliable_path_coverage",
    "committed_frame",
    "committed_time_s",
    "status",
    "qualification_claim",
    "material_reliability",
    "qualified_T2_macro",
    "qualified_T2_path",
    "elapsed_seconds",
    "max_rss_kib",
    "timing_seconds",
    "native_frame_count",
    "binding",
    "checkpoint_manifest",
)
PER_SOURCE_METRIC_FIELDS = (
    "source",
    "initial_mass_fraction",
    "terminal_categories",
    "unknown_fraction_max",
    "unknown_fraction_monotone",
    "reliable_path_coverage",
    "mass_closure_fraction",
    "mass_closure_error",
    "first_passage_cdf",
    "first_passage_cdf_bounds",
    "return_cdf",
    "return_cdf_bounds",
    "residence_opposite_s",
    "residence_left_s",
    "residence_right_s",
    "residence_mean_s_bounds",
    "residence_cdf_bounds",
    "residence_right_censored_unknown_mass_fraction",
    "first_unreliable_frame",
    "first_unreliable_time_s",
)
EXECUTION_CONTROL_KEYS = (
    "core_runtime_job_started",
    "cpu_material_worker_started",
    "gpu_started",
    "solver_started",
    "native_started",
    "gencase_started",
    "queue_mutations",
    "material_trace_read",
    "material_trace_created",
    "registry_mutations",
    "completion_mutations",
    "ledger_mutations",
    "denominator_mutations",
    "gate_mutations",
)


def sha256_file(path: Path) -> str:
    """Hash bytes without interpreting an HDF5 or material-trace format."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _path(root: Path, relative: Path) -> Path:
    resolved = (root / relative).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _ref(
    root: Path,
    relative: Path,
    role: str,
    *,
    expected_sha256: str | None = None,
    hash_only: bool = False,
) -> dict[str, Any]:
    path = _path(root, relative)
    if not path.is_file():
        raise FileNotFoundError(path)
    observed = sha256_file(path)
    if expected_sha256 is not None and observed != expected_sha256:
        raise ValueError(
            f"hash mismatch for {relative}: expected {expected_sha256}, got {observed}"
        )
    return {
        "path": _relative_path(root, path),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": observed,
        "expected_sha256": expected_sha256,
        "sha256_match": expected_sha256 is None or observed == expected_sha256,
        "hash_only": hash_only,
    }


def _literal_assignment(tree: ast.AST, name: str) -> Any:
    for node in ast.walk(tree):
        targets: Iterable[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets, value = (node.target,), node.value
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            try:
                return ast.literal_eval(value)
            except (TypeError, ValueError):
                return None
    return None


def _function_arguments(tree: ast.AST, function_name: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return [item.arg for item in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
    return []


def _module_cli_contract(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    flags = sorted(value for value in literals if value.startswith("--"))
    has_main_guard = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and any(isinstance(item, ast.Constant) and item.value == "__main__" for item in ast.walk(node.test))
        for node in ast.walk(tree)
    )
    checkpoint_schema = _literal_assignment(tree, "CHECKPOINT_SCHEMA")
    module_schema = _literal_assignment(tree, "SCHEMA")
    checkpoint_fields = _literal_assignment(tree, "CHECKPOINT_FIELDS")
    if not isinstance(checkpoint_fields, tuple):
        checkpoint_fields = ()
    return {
        "path": str(path),
        "module": "scripts.core_material",
        "static_parse": True,
        "main_guard": has_main_guard,
        "declared_flags": flags,
        "required_f3_flags": {
            flag: flag in flags
            for flag in (
                "--source",
                "--output",
                "--seeds",
                "--substeps",
                "--neighbour-variant",
                "--resume",
            )
        },
        "test_only_or_partial_flags": {
            "--stop-after": "--stop-after" in flags,
            "--kill-after": "--kill-after" in flags,
        },
        "module_functions": {
            name: any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
                for node in ast.walk(tree)
            )
            for name in ("trace", "macro_summary", "main")
        },
        "trace_arguments": _function_arguments(tree, "trace"),
        "schema": module_schema,
        "checkpoint_schema": checkpoint_schema,
        "checkpoint_fields": list(checkpoint_fields),
        "history_fields": ["time", *checkpoint_fields],
    }


def normalized_argv(root: Path, *, resume: bool = False) -> list[str]:
    source = _path(root, SOURCE_H5)
    # Keep the frozen job's logical interpreter path.  Resolving the venv
    # symlink would turn it into /usr/bin/python3.10 and would no longer match
    # the bound runtime contract.
    python_path = (root / ".venv/bin/python").absolute()
    if not python_path.is_file():
        raise FileNotFoundError(python_path)
    argv = [
        str(python_path),
        "-m",
        "scripts.core_material",
        "--source",
        str(source),
        "--output",
        "{attempt_dir}/material.h5",
        "--seeds",
        "512",
        "--substeps",
        "2",
        "--neighbour-variant",
        "baseline24",
    ]
    if resume:
        argv.append("--resume")
    return argv


def forbidden_argv_reasons(argv: Sequence[str], root: Path = LAB_ROOT) -> list[str]:
    """Return hard failures for a proposed child argv, without executing it."""

    values = [str(item) for item in argv]
    lowered = [value.lower() for value in values]
    reasons: list[str] = []
    raw_paths = {
        str(_path(root, CORE_MATERIAL)),
        str(CORE_MATERIAL),
        "core_material.py",
    }
    if any(value in raw_paths or value.endswith("/scripts/core_material.py") for value in values):
        reasons.append("raw_script_path_forbidden")
    if "-m" not in values or "scripts.core_material" not in values:
        reasons.append("module_entry_required")
    gpu_tokens = ("--gpu", "--cuda", "cuda_visible_devices", "gpu_peak_mib")
    if any(token in value for value in lowered for token in gpu_tokens):
        reasons.append("gpu_launch_or_gpu_override_forbidden")
    partial_tokens = ("--stop-after", "--kill-after")
    if any(token in lowered for value in lowered for token in partial_tokens):
        reasons.append("partial_or_kill_hook_forbidden")
    row30_tokens = (
        "row30",
        "f3-material-30-canonical-s4-r003",
        "--retry-row30",
        "--force-retry",
    )
    if any(token in value for value in lowered for token in row30_tokens):
        reasons.append("row30_retry_forbidden")
    return reasons


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} changed: expected {expected!r}, got {actual!r}")


def _source_contract(root: Path, source_sha256: str) -> dict[str, Any]:
    audit = _read_json(_path(root, SOURCE_AUDIT))
    prepared = _read_json(_path(root, SOURCE_PREPARED))
    revision = _read_json(_path(root, REVISION_MANIFEST))
    _assert_equal(audit.get("case_id"), "R0081818-NOMINAL", "source audit case_id")
    _assert_equal(audit.get("frames"), 836, "source audit frame count")
    _assert_equal(audit.get("time_start_s"), 0.0, "source audit time_start_s")
    _assert_equal(audit.get("hdf5_sha256"), source_sha256, "source audit HDF5 hash")
    _assert_equal(prepared.get("case_id"), "R0081818-NOMINAL", "prepared case_id")
    _assert_equal(prepared.get("formal_release"), False, "prepared formal_release")
    _assert_equal(prepared.get("launch_allowed"), False, "prepared launch_allowed")
    _assert_equal(prepared.get("qualified"), False, "prepared qualified")
    _assert_equal(revision.get("launch_allowed"), False, "revision manifest launch_allowed")
    required_before_launch = revision.get("required_before_launch")
    if not isinstance(required_before_launch, list) or not any(
        "new authorization" in str(item) for item in required_before_launch
    ):
        raise ValueError("revision manifest no longer requires a new authorization")
    return {
        "source_role": "coarse",
        "case_id": audit["case_id"],
        "audit_status": audit.get("audit_status"),
        "acceptance_status": audit.get("acceptance_status"),
        "formal_release": prepared["formal_release"],
        "qualified": prepared["qualified"],
        "launch_allowed": prepared["launch_allowed"],
        "required_before_launch": required_before_launch,
        "window": {
            "native_frame_count": audit["frames"],
            "first_frame": 0,
            "last_frame": audit["frames"] - 1,
            "time_start_s": audit["time_start_s"],
            "time_end_s": audit["time_end_s"],
            "source_h5_hash_matches_audit": audit["hdf5_sha256"] == source_sha256,
            "hdf5_structure_opened_by_proposal": False,
        },
        "metadata_only": True,
    }


def _runtime_contract(
    root: Path,
    runtime_spec: Mapping[str, Any],
    queue_registration: Mapping[str, Any],
    module_contract: Mapping[str, Any],
    current_code_sha256: str,
    current_neighbour_sha256: str,
    current_passive_sha256: str,
    runtime_sha256: str,
) -> dict[str, Any]:
    runtime = runtime_spec.get("runtime")
    implementation = runtime_spec.get("implementation_binding")
    acceptance = runtime_spec.get("acceptance")
    if not isinstance(runtime, Mapping) or not isinstance(implementation, Mapping) or not isinstance(acceptance, Mapping):
        raise ValueError("runtime spec is missing required contract objects")
    _assert_equal(runtime.get("module"), "scripts.core_material", "runtime module")
    _assert_equal(runtime.get("working_directory"), str(root), "runtime working directory")
    _assert_equal(runtime.get("cpu_only"), True, "runtime cpu_only")
    _assert_equal(runtime.get("gpu_forbidden"), True, "runtime gpu_forbidden")
    _assert_equal(runtime.get("full_native_window"), True, "runtime full_native_window")
    _assert_equal(runtime.get("stop_after"), None, "runtime stop_after")
    _assert_equal(runtime.get("scheduler_owned_resources"), True, "runtime scheduler_owned_resources")
    _assert_equal(implementation.get("neighbour_variant"), "baseline24", "runtime neighbour variant")
    _assert_equal(implementation.get("neighbours"), 24, "runtime neighbour count")
    _assert_equal(acceptance.get("unknown_gate"), "every source row in every completed output has unknown_fraction_max <= 0.01", "unknown gate")
    return {
        "runtime_spec_status": runtime_spec.get("status"),
        "runtime_spec_sha256": runtime_sha256,
        "module": runtime["module"],
        "working_directory": runtime["working_directory"],
        "cpu_only": runtime["cpu_only"],
        "gpu_forbidden": runtime["gpu_forbidden"],
        "scheduler_owned_resources": runtime["scheduler_owned_resources"],
        "full_native_window": runtime["full_native_window"],
        "stop_after": runtime["stop_after"],
        "resume_policy": runtime["resume_policy"],
        "required_execution_receipt_fields": list(runtime["required_receipt"]),
        "implementation_binding": {
            "historical_runtime_spec_core_material_sha256": implementation.get("core_material_sha256"),
            "current_core_material_sha256": current_code_sha256,
            "current_neighbour_code_sha256": current_neighbour_sha256,
            "current_passive_tracer_code_sha256": current_passive_sha256,
            "historical_core_material_matches_current": implementation.get("core_material_sha256") == current_code_sha256,
            "historical_neighbour_code_matches_current": implementation.get("neighbor_code_sha256") == current_neighbour_sha256,
            "historical_passive_code_matches_current": implementation.get("passive_tracer_code_sha256") == current_passive_sha256,
            "refresh_required_before_launch": implementation.get("core_material_sha256") != current_code_sha256,
        },
        "acceptance": {
            "unknown_gate": acceptance["unknown_gate"],
            "mass_closure": acceptance["mass_closure"],
            "initial_support_validation": acceptance["initial_support_validation"],
            "reconstruction_gate": acceptance["reconstruction_gate"],
            "qualification_rule": acceptance["qualification_rule"],
            "macro_outputs": list(acceptance["macro_outputs"]),
        },
        "module_static_contract": dict(module_contract),
        "frozen_worker": {
            "runtime_path": str(_path(root, CORE_RUNTIME).relative_to(root)),
            "runtime_sha256": runtime_sha256,
            "required_surface": ["freeze_job", "worker", "launch_detached", "Coordinator", "probe", "choose_resources"],
            "submission_surface": "scheduler-owned core_runtime coordinator; no direct child launch",
            "source_snapshot_required": True,
            "source_snapshot_created_by_proposal": False,
        },
        "queue_registration": {
            "path": str(QUEUE_REGISTRATION),
            "qualification_claim": queue_registration.get("qualification_claim"),
            "note": queue_registration.get("note"),
            "queue_mutated_by_proposal": False,
        },
    }


def _host_io_prerequisites(job_spec: Mapping[str, Any]) -> dict[str, Any]:
    resources = job_spec.get("resources")
    if not isinstance(resources, Mapping):
        raise ValueError("job spec resources are missing")
    return {
        "status": "not_measured_proposal_only",
        "measured_admission_required": True,
        "probe_surface": "scripts/core_runtime.py::probe plus scheduler-owned choose_resources",
        "resource_request": {
            "cpu_cores": resources.get("cpu_cores"),
            "ram_mib": resources.get("ram_mib"),
            "gpu_peak_mib": resources.get("gpu_peak_mib"),
            "io_weight": resources.get("io_weight"),
        },
        "cpu_only": resources.get("gpu_peak_mib") == 0,
        "gpu_forbidden": True,
        "required_snapshot_fields": [
            "cpu_count",
            "load1",
            "ram_total_mib",
            "ram_available_mib",
            "disk_free_bytes",
            "io_capacity",
        ],
        "admission_conditions": [
            "cpu_reserved + request.cpu_cores <= floor(cpu_count * 0.8)",
            "ram_reserved + request.ram_mib <= ram_available_mib + owned_rss_mib - 0.15 * ram_total_mib",
            "owned_io_weight + request.io_weight <= measured io_capacity",
            "io_capacity is finite and > 0",
            "disk_free_bytes >= 20 GiB unless an explicit bounded spec overrides it",
        ],
        "gpu_vram_headroom_is_not_admission": True,
        "snapshot_collected_by_proposal": False,
    }


def _fresh_attempt_contract(root: Path) -> dict[str, Any]:
    attempt_root = Path("campaigns/core-v1/runtime/attempts") / JOB_ID
    return {
        "created": False,
        "attempt_root": str(attempt_root),
        "namespace_template": str(attempt_root / "<fresh-attempt-id>"),
        "attempt_id_policy": "new scheduler-generated identity; never reuse a historical attempt directory",
        "same_attempt_resume_only": True,
        "historical_attempt_reuse_forbidden": True,
        "output_templates": [
            "material.h5",
            "material.json",
            "material.h5.checkpoint.npz",
            "material.h5.checkpoint.json",
        ],
        "proposal_created_path": None,
        "root_is_lab_relative_to": str(root),
    }


def build_proposal(root: str | Path = LAB_ROOT) -> dict[str, Any]:
    """Return the current source-bound proposal without starting any process."""

    root = Path(root).resolve()
    core_ref = _ref(root, CORE_MATERIAL, "current core material module", expected_sha256=EXPECTED_CORE_MATERIAL_SHA256)
    source_ref = _ref(
        root,
        SOURCE_H5,
        "read-only coarse native source; byte hash only",
        expected_sha256=EXPECTED_SOURCE_SHA256,
        hash_only=True,
    )
    job_ref = _ref(root, JOB_SPEC, "historical coarse job specification binding", expected_sha256=EXPECTED_JOB_SPEC_SHA256)
    source_audit_ref = _ref(root, SOURCE_AUDIT, "coarse source audit manifest", expected_sha256=EXPECTED_SOURCE_AUDIT_SHA256)
    source_prepared_ref = _ref(root, SOURCE_PREPARED, "coarse source preparation manifest", expected_sha256=EXPECTED_SOURCE_PREPARED_SHA256)
    revision_ref = _ref(root, REVISION_MANIFEST, "F3 revision/source manifest", expected_sha256=EXPECTED_REVISION_MANIFEST_SHA256)
    runtime_ref = _ref(root, RUNTIME_SPEC, "frozen material runtime contract", expected_sha256=EXPECTED_RUNTIME_SPEC_SHA256)
    queue_ref = _ref(root, QUEUE_REGISTRATION, "diagnostic queue registration", expected_sha256=EXPECTED_QUEUE_REGISTRATION_SHA256)
    runtime_path_ref = _ref(root, CORE_RUNTIME, "current frozen worker runtime")
    neighbour_ref = _ref(root, NEIGHBOUR_CODE, "current neighbour backend dependency")
    passive_ref = _ref(root, PASSIVE_TRACER_CODE, "current passive tracer dependency")

    job_spec = _read_json(_path(root, JOB_SPEC))
    runtime_spec = _read_json(_path(root, RUNTIME_SPEC))
    queue_registration = _read_json(_path(root, QUEUE_REGISTRATION))
    module_contract = _module_cli_contract(_path(root, CORE_MATERIAL))
    source_contract = _source_contract(root, source_ref["sha256"])
    runtime_contract = _runtime_contract(
        root,
        runtime_spec,
        queue_registration,
        module_contract,
        core_ref["sha256"],
        neighbour_ref["sha256"],
        passive_ref["sha256"],
        runtime_ref["sha256"],
    )

    observed_argv = list(job_spec.get("argv", []))
    normalized = normalized_argv(root)
    resume = normalized_argv(root, resume=True)
    raw_path_present = any(str(item).endswith("/scripts/core_material.py") for item in observed_argv)
    normalized_reasons = forbidden_argv_reasons(normalized, root)
    if normalized_reasons:
        raise ValueError(f"internal normalized argv is forbidden: {normalized_reasons}")
    if job_spec.get("job_id") != JOB_ID or job_spec.get("logical_id") != CANDIDATE_ID:
        raise ValueError("bound job spec is not the requested coarse candidate")
    _assert_equal(job_spec.get("cwd"), str(root), "job spec cwd")
    if job_spec.get("input_files", [{}])[0].get("sha256") != EXPECTED_SOURCE_SHA256:
        raise ValueError("job spec source hash is not the requested coarse source")

    blocking_reasons = [
        "fresh_root_or_scheduler_authorization_missing",
        "measured_host_io_admission_missing",
        "source_preparation_manifest_launch_forbidden",
    ]
    if raw_path_present:
        blocking_reasons.append("historical_job_spec_uses_forbidden_raw_script_path; use normalized module argv")
    if not runtime_contract["implementation_binding"]["historical_core_material_matches_current"]:
        blocking_reasons.append("runtime_spec_core_material_binding_stale_against_current_code")

    return {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "status": "proposal_only_fail_closed",
        "candidate": {
            "configuration_id": CANDIDATE_ID,
            "job_id": JOB_ID,
            "family": "F3",
            "source_role": "coarse",
            "substeps": 2,
            "seeds": 512,
            "neighbour_variant": "baseline24",
        },
        "proposal_state": {
            "proposal_only": True,
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "qualification_claim": "none",
            "qualification_credit": 0,
            "T2_credit": 0,
            "T2_macro": False,
            "T2_path": False,
            "launch_admitted": False,
        },
        "input_bindings": {
            "core_material": core_ref,
            "source_h5": source_ref,
            "job_spec": job_ref,
            "source_audit_manifest": source_audit_ref,
            "source_prepared_manifest": source_prepared_ref,
            "revision_manifest": revision_ref,
            "runtime_spec": runtime_ref,
            "queue_registration": queue_ref,
            "current_frozen_worker": runtime_path_ref,
            "current_neighbour_code": neighbour_ref,
            "current_passive_tracer_code": passive_ref,
        },
        "source_manifest_contract": source_contract,
        "cli_contract": {
            "module_entry": module_contract,
            "observed_bound_job_spec_argv": observed_argv,
            "observed_bound_job_spec_cwd": job_spec.get("cwd"),
            "observed_raw_script_path": raw_path_present,
            "raw_script_path_accepted": False,
            "normalization_required": raw_path_present,
        },
        "normalized_launch": {
            "cwd": str(root),
            "argv": normalized,
            "resume_argv_same_attempt": resume,
            "full_native_window": True,
            "stop_after": None,
            "output": "{attempt_dir}/material.h5",
        },
        "frozen_worker_runtime_contract": runtime_contract,
        "resource_admission": _host_io_prerequisites(job_spec),
        "fresh_attempt_namespace": _fresh_attempt_contract(root),
        "required_output_contract": {
            "outputs": [
                "material.h5",
                "material.json",
                "material.h5.checkpoint.npz",
                "material.h5.checkpoint.json",
            ],
            "native_window": {
                "native_frame_count": 836,
                "first_frame": 0,
                "last_committed_frame": 835,
                "partial_stop_forbidden": True,
            },
            "atomic_checkpoint": {
                "schema": module_contract["checkpoint_schema"],
                "fields": list(CHECKPOINT_FIELDS),
                "sidecar_state": "material.h5.checkpoint.npz",
                "sidecar_manifest": "material.h5.checkpoint.json",
                "publish_state_before_hdf5_row": True,
                "binding_hash_required": True,
            },
            "resume": {
                "same_attempt_only": True,
                "resume_flag": "--resume",
                "checkpoint_is_authoritative": True,
                "new_scientific_configuration_forbidden": True,
                "new_attempt_after_partial_failure_forbidden": True,
            },
            "material_json": {
                "top_level_fields": list(MATERIAL_METRIC_FIELDS),
                "per_source_fields": list(PER_SOURCE_METRIC_FIELDS),
                "unknown_fraction_limit": 0.01,
                "mass_closure_error_limit": 1e-12,
                "right_censored_mass_must_be_retained": True,
            },
            "execution_receipt": list(runtime_contract["required_execution_receipt_fields"]),
        },
        "forbidden": {
            "raw_script_path": [
                "scripts/core_material.py",
                str(_path(root, CORE_MATERIAL)),
                "python scripts/core_material.py ...",
            ],
            "gpu": [
                "--gpu",
                "--cuda",
                "non-empty CUDA_VISIBLE_DEVICES",
                "resources.gpu_peak_mib > 0",
                "using GPU VRAM headroom as CPU/I/O admission",
            ],
            "partial_or_test_hooks": ["--stop-after", "--kill-after"],
            "row30_retry": [
                "row30",
                "--retry-row30",
                "--force-retry",
                "f3-material-30-canonical-s4-r003",
            ],
            "scope_mutations": [
                "core_runtime submit/worker execution during proposal",
                "solver/native/GenCase/queue start",
                "material trace read or generation",
                "registry/completion/ledger/denominator/gate/PLAN mutation",
            ],
        },
        "execution_controls": {
            "core_runtime_job_started": False,
            "cpu_material_worker_started": False,
            "gpu_started": False,
            "solver_started": False,
            "native_started": False,
            "gencase_started": False,
            "queue_mutations": 0,
            "material_trace_read": False,
            "material_trace_created": False,
            "source_hdf5_hash_only": True,
            "source_hdf5_opened_as_hdf5": False,
            "material_metrics_created": False,
            "registry_mutations": 0,
            "completion_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "gate_mutations": 0,
        },
        "authorization": {
            "status": "not_granted",
            "fresh_root_authorization_required": True,
            "source_manifest_launch_allowed": False,
            "prepared_source_launch_allowed": False,
            "runtime_spec_ready_for_root_queue_is_not_authorization": True,
            "measured_host_io_receipt_required": True,
            "historical_outputs_reuse_forbidden": True,
        },
        "blocking_reasons": blocking_reasons,
        "next_safe_action": (
            "Obtain a fresh root/scheduler admission receipt bound to the current code SHA, exact source SHA, "
            "normalized module argv/cwd, a fresh attempt namespace, and a measured host-I/O snapshot; only then "
            "may the frozen worker be considered for one CPU-only diagnostic attempt."
        ),
    }


def validate_proposal(value: Mapping[str, Any]) -> list[str]:
    """Validate fixed fail-closed markers without touching any runtime state."""

    errors: list[str] = []
    if value.get("schema") != SCHEMA:
        errors.append("schema")
    if value.get("status") != "proposal_only_fail_closed":
        errors.append("status")
    state = value.get("proposal_state", {})
    for key, expected in (
        ("proposal_only", True),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("qualification_credit", 0),
        ("T2_credit", 0),
        ("T2_macro", False),
        ("T2_path", False),
        ("launch_admitted", False),
    ):
        if state.get(key) != expected:
            errors.append(f"proposal_state.{key}")
    if state.get("qualification_claim") != "none":
        errors.append("proposal_state.qualification_claim")
    source = value.get("source_manifest_contract", {})
    if source.get("window", {}).get("native_frame_count") != 836:
        errors.append("source_manifest_contract.window.native_frame_count")
    normalized = value.get("normalized_launch", {})
    if normalized.get("stop_after") is not None:
        errors.append("normalized_launch.stop_after")
    if forbidden_argv_reasons(normalized.get("argv", []), LAB_ROOT):
        errors.append("normalized_launch.argv")
    if value.get("fresh_attempt_namespace", {}).get("created") is not False:
        errors.append("fresh_attempt_namespace.created")
    controls = value.get("execution_controls", {})
    for key in EXECUTION_CONTROL_KEYS:
        expected = 0 if key.endswith("mutations") else False
        if controls.get(key) != expected:
            errors.append(f"execution_controls.{key}")
    return errors


def refresh_static_proposal(
    root: str | Path = LAB_ROOT,
    *,
    source_report_path: str | Path = HISTORICAL_PROPOSAL,
) -> dict[str, Any]:
    """Refresh only current code bindings in an additive proposal report.

    The historical proposal already contains the byte-only source-HDF5 claim
    and the immutable campaign metadata.  This helper deliberately reuses
    those claims without opening the source file, while rebinding the current
    frozen worker to the checked-out ``core_runtime.py`` bytes.  It is a
    diagnostic proposal refresh, never an authorization or a formal receipt.
    """

    root_path = Path(root).resolve()
    source_path = Path(source_report_path)
    if not source_path.is_absolute():
        source_path = root_path / source_path
    source_path = source_path.resolve()
    try:
        source_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError("historical proposal must remain below the lab root") from error

    previous = _read_json(source_path)
    refreshed = copy.deepcopy(previous)
    runtime_ref = _ref(root_path, CORE_RUNTIME, "current frozen worker runtime")
    bindings = refreshed.get("input_bindings")
    if not isinstance(bindings, dict):
        raise ValueError("historical proposal input_bindings is not an object")
    bindings["current_frozen_worker"] = runtime_ref

    runtime_contract = refreshed.get("frozen_worker_runtime_contract")
    if not isinstance(runtime_contract, dict):
        raise ValueError("historical proposal frozen worker contract is not an object")
    runtime_contract["runtime_sha256"] = runtime_ref["sha256"]
    frozen_worker = runtime_contract.get("frozen_worker")
    if isinstance(frozen_worker, dict):
        frozen_worker["runtime_sha256"] = runtime_ref["sha256"]

    refreshed["created_at"] = "2026-09-29"
    refreshed["rerun_metadata"] = {
        "kind": "additive_dated_rerun",
        "rerun_of": str(source_path.relative_to(root_path)),
        "reason": "refresh current frozen-worker byte binding after security hardening",
        "source_hdf5_opened": False,
        "formal": False,
        "qualification_credit": 0,
    }
    return refreshed


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    """Write only an explicitly requested proposal report; never overwrite."""

    errors = validate_proposal(value)
    if errors:
        raise ValueError("refusing to write invalid proposal: " + ", ".join(errors))
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="explicit JSON report path; no attempt/runtime is started")
    parser.add_argument(
        "--refresh-from",
        type=Path,
        default=None,
        help="refresh only current code bindings from an existing proposal without opening source HDF5",
    )
    args = parser.parse_args(argv)
    if args.refresh_from is None:
        value = build_proposal()
    else:
        value = refresh_static_proposal(source_report_path=args.refresh_from)
    errors = validate_proposal(value)
    if errors:
        raise SystemExit("proposal validation failed: " + ", ".join(errors))
    if args.output is not None:
        write_report(value, args.output)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
