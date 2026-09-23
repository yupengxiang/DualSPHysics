#!/usr/bin/env python3
"""Seal the exact, zero-credit F8 R008 CPU/native one-shot authorization."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
REQUEST = ROOT / "cpu-native-preflight-request-v3/request.json"
RESOURCE = ROOT / "resource-admission-v1/receipt.json"
CAPABILITY = ROOT / "resource-capability-probe-v1/receipt.json"
INDEPENDENT_REVIEW = ROOT / "independent-static-review-terra-high-v1/receipt.json"
R007_AUTH = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r007/cpu-native-preflight-authorization-v1/authorization.json")
R007_PREFLIGHT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r007/cpu-native-preflight-v1/receipt.json")
OUTPUT = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
SCOPED_COMMAND = Path("scripts/f8_r008_scoped_native_command_v1.py")
EXECUTOR = Path("scripts/f8_r008_cpu_native_preflight_execute_v1.py")
BUILDER = Path("scripts/f8_r008_cpu_native_preflight_authorization_v1.py")
TESTS = Path("tests/test_f8_r008_cpu_native_preflight_v1.py")
AUDIT_HELPERS = Path("scripts/f8_r006_cpu_native_preflight_execute_v1.py")
NATIVE_HELPERS = Path("scripts/f8_r003_cpu_native_preflight_execute_v1.py")
NATIVE_RUNNER = Path("scripts/f8_r003_cpu_native_preflight_runner_v1.py")
GEOMETRY_REVIEW = Path("scripts/f8_r007_static_design_review_v1.py")
SCHEMA = "core.cfd.f8.r008_cpu_native_preflight_authorization.v1"
MEMORY_MAX_BYTES = 4096 * 1024**2
MIN_AVAILABLE_MEMORY_BYTES = 8 * 1024**3
MIN_FREE_DISK_BYTES = 8 * 1024**3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"R008 binding must remain relative to the lab root: {value}")
    return path


def binding(path: Path, role: str) -> dict[str, Any]:
    path = Path(path)
    if path.is_absolute():
        resolved = path.resolve(strict=True)
        display = str(resolved)
    else:
        relative = _relative_path(str(path))
        resolved = (LAB / relative).resolve(strict=True)
        resolved.relative_to(LAB.resolve())
        display = str(relative)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {"path": display, "sha256": sha256(resolved), "bytes": resolved.stat().st_size, "role": role}


def verify_binding(item: dict[str, Any]) -> Path:
    raw = item.get("path")
    if not isinstance(raw, str) or not raw:
        raise ValueError("binding path is missing")
    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve(strict=True)
    else:
        resolved = (LAB / _relative_path(raw)).resolve(strict=True)
        resolved.relative_to(LAB.resolve())
    if (not resolved.is_file() or resolved.stat().st_size != item.get("bytes")
            or sha256(resolved) != item.get("sha256")):
        raise ValueError(f"hash-closed R008 source changed: {raw}")
    return resolved


def _load(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def _xml_subtree(path: Path, selector: str) -> bytes:
    node = ET.parse(path).getroot().find(selector)
    if node is None:
        raise ValueError(f"Definition is missing {selector}: {path}")
    return ET.tostring(node, encoding="utf-8")


def validate_predecessors() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = _load(REQUEST)
    resource = _load(RESOURCE)
    capability = _load(CAPABILITY)
    review = _load(INDEPENDENT_REVIEW)
    r007_auth = _load(R007_AUTH)
    r007_receipt = _load(R007_PREFLIGHT)

    if not (
        request.get("schema") == "core.cfd.f8.r008_cpu_native_preflight_request.v3"
        and request.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
        and request.get("request_only") is True
        and request.get("authorization", {}).get("this_request_grants_execution") is False
        and request.get("authorization", {}).get("qualification_credit") == 0
        and request.get("execution_controls", {}).get("gencase_invoked") is False
        and request.get("execution_controls", {}).get("native_decode_invoked") is False
        and request.get("execution_controls", {}).get("runtime_namespace_created") is False
    ):
        raise PermissionError("R008 v3 is not the fresh, zero-authority request expected by this authorization")

    proposed = request.get("proposed_preflight_only", {})
    if not (
        proposed.get("case_count") == 1
        and proposed.get("max_gencase_invocations") == 1
        and proposed.get("max_native_decode_invocations") == 1
        and proposed.get("solver_invocations") == 0
        and proposed.get("retries_or_output_reuse_allowed") is False
        and proposed.get("proposed_resource_envelope", {}).get("ram_limit_bytes") == MEMORY_MAX_BYTES
        and proposed.get("proposed_resource_envelope", {}).get("gpu_allowed") is False
        and proposed.get("proposed_resource_envelope", {}).get("queue_or_scheduler") is False
    ):
        raise PermissionError("R008 request exceeds the single CPU/native preflight envelope")

    all_inputs = request.get("all_r008_inputs", {}).get("bindings", [])
    sources = request.get("source_bindings", [])
    if len(all_inputs) != 94 or len({item.get("path") for item in all_inputs}) != 94:
        raise ValueError("R008 request must close exactly 94 distinct Definition/control inputs")
    if request.get("source_binding_count") != 24 or len(sources) != 24:
        raise ValueError("R008 v3 source closure must contain exactly 24 bindings")
    for item in [*all_inputs, *sources]:
        verify_binding(item)

    target = request.get("target_case", {})
    if not (target.get("case_id") == "space-q0p5-dp0p0075" and target.get("qualification_only") is True):
        raise ValueError("R008 representative case changed from the request-bound qualification anchor")
    input_by_path = {item.get("path"): item for item in all_inputs}
    target_paths = {target.get("definition", {}).get("path"), target.get("control", {}).get("path")}
    if not target_paths.issubset(input_by_path):
        raise ValueError("representative R008 input is outside the 94-file hash closure")
    for key in ("definition", "control"):
        target_ref = target.get(key, {})
        closed_ref = input_by_path.get(target_ref.get("path"), {})
        if any(target_ref.get(field) != closed_ref.get(field) for field in ("path", "sha256", "bytes")):
            raise ValueError(f"R008 target {key} reference differs from its 94-input closure")

    for reference in (request.get("resource_admission_reference"), request.get("capability_probe_reference")):
        if not isinstance(reference, dict):
            raise ValueError("R008 resource evidence reference is missing")
        verify_binding(reference)
    if not (
        resource.get("status") == "conditional_ram_cap_cpu_schedule_blocked_no_execution_authority"
        and resource.get("resource_decision", {}).get("proposed_ram_limit_mib") == 4096
        and resource.get("authorization_boundary", {}).get("request_grants_native_execution") is False
        and resource.get("authorization_boundary", {}).get("runtime_namespace_created") is False
    ):
        raise PermissionError("R008 resource admission evidence no longer matches this one-case preflight")
    probe = capability.get("probe", {})
    assessment = capability.get("assessment", {})
    if not (
        capability.get("schema") == "core.cfd.f8_r008_rootless_cgroup_memory_capability_probe.v1"
        and probe.get("systemd_memory_max_bytes") == MEMORY_MAX_BYTES
        and probe.get("cgroup_memory_max_bytes") == MEMORY_MAX_BYTES
        and probe.get("parent_and_child_same_cgroup") is True
        and assessment.get("requested_cap_applied_to_test_scope") is True
        and assessment.get("native_workload_peak_rss_measured") is False
        and capability.get("execution_controls", {}).get("runtime_namespace_created") is False
    ):
        raise PermissionError("rootless cgroup probe does not establish the exact 4 GiB parent/child scope")

    if not (
        review.get("schema") == "core.cfd.f8.r008_independent_static_review.v1"
        and review.get("scope_id") == request.get("scope_id")
        and review.get("verdict") == "pass-with-gaps"
        and review.get("status") == "r008_static_design_conditionally_passed_cpu_native_preflight_only"
        and review.get("reviewer", {}).get("requested_model") == "gpt-5.6-terra"
        and review.get("reviewer", {}).get("requested_reasoning_effort") == "high"
        and review.get("review_scope", {}).get("runtime_tools_invoked") is False
        and review.get("decision_boundary", {}).get("may_prepare_separate_one_shot_cpu_native_authorization") is True
        and review.get("decision_boundary", {}).get("execution_authorized_by_this_review") is False
        and review.get("decision_boundary", {}).get("solver_authorized") is False
        and review.get("decision_boundary", {}).get("t1_t2_or_qualification_credit") == 0
        and review.get("verified", {}).get("r008_input_bindings_verified") == 94
        and review.get("verified", {}).get("r008_source_bindings_verified") == 24
        and review.get("execution_controls", {}).get("gencase_invoked") is False
    ):
        raise PermissionError("independent R008 static review is absent, changed, or exceeds its conditional CPU/native-only verdict")

    r007_hard = r007_auth.get("hard_gates", {})
    r007_generated = r007_receipt.get("generated_geometry_audit", {}).get("generated_geometry", {})
    r008_definition = LAB / target["definition"]["path"]
    r007_definition = LAB / resource["analogue"]["geometry_comparison"]["r007_definition"]
    if not (
        r007_auth.get("status") == "authorized_for_exactly_one_r007_cpu_native_preflight"
        and r007_receipt.get("status") == "cpu_native_preflight_passed_zero_credit"
        and resource.get("analogue", {}).get("geometry_comparison", {}).get("parsed_geometry_subtrees_identical") is True
        and _xml_subtree(r008_definition, "./casedef/geometry") == _xml_subtree(r007_definition, "./casedef/geometry")
        and r007_generated.get("fixed_boundary_particles") == 4096
        and r007_generated.get("fluid_particles") == 6656
        and r007_generated.get("total_particles_header") == 10752
    ):
        raise ValueError("R007 geometry analogue no longer proves the frozen R008 anchor geometry")

    hard_gate_keys = (
        "generated_fixed_boundary_particles_exact", "generated_fluid_particles_exact",
        "generated_hdp_surface_points_exact", "generated_hdp_surface_z_planes_m",
        "generated_total_particles_exact", "generated_z_wall_plane_particle_counts",
        "native_boundary_inward_normal_z_component_minimum_m",
        "native_boundary_normal_count_exact", "native_boundary_normals_finite_and_minimum_magnitude",
        "native_boundary_particles_exact", "native_boundary_z_wall_plane_particle_counts",
        "native_fluid_mass_kg_expected", "native_fluid_particle_count_exact",
    )
    hard_gates = {key: r007_hard[key] for key in hard_gate_keys}
    if any(key not in hard_gates for key in hard_gate_keys):
        raise ValueError("R007 audit contract is incomplete for R008 geometry checks")
    return request, resource, capability, review, {"hard_gates": hard_gates, "r007_auth": r007_auth, "r007_receipt": r007_receipt}


def _unique_bindings(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for item in candidates:
        previous = by_path.get(item["path"])
        if previous is None:
            by_path[item["path"]] = item
        elif (previous["sha256"], previous["bytes"]) != (item["sha256"], item["bytes"]):
            raise ValueError(f"conflicting identities for bound source: {item['path']}")
        else:
            roles = set(previous.get("also_roles", [previous.get("role")]))
            roles.add(item["role"])
            previous["also_roles"] = sorted(role for role in roles if role)
    return [by_path[path] for path in sorted(by_path)]


def build_authorization() -> dict[str, Any]:
    request, resource, capability, review, audit = validate_predecessors()
    runtime_namespace = LAB / request["proposed_preflight_only"]["runtime_output_namespace"]
    if runtime_namespace.exists() or runtime_namespace.is_symlink():
        raise FileExistsError(f"R008 runtime output namespace must remain unused: {runtime_namespace}")

    binaries = request["proposed_preflight_only"]["cpu_native_tools_inherited_as_metadata_only"]
    gencase = binaries["gencase_binary"]
    decoder = binaries["native_decoder"]
    if ("/" not in str(gencase["path"]) or Path(gencase["path"]).is_absolute()
            or Path(decoder["path"]).is_absolute()):
        raise ValueError("native binary request paths must be lab-relative")
    for item in (gencase, decoder):
        verify_binding(item)

    systemd_path = shutil.which("systemd-run")
    if not systemd_path:
        raise FileNotFoundError("systemd-run is required for the 4 GiB rootless cgroup scope")
    systemctl_path = shutil.which("systemctl")
    if not systemctl_path:
        raise FileNotFoundError("systemctl is required to check the rootless user manager")
    candidates = [
        binding(REQUEST, "immutable R008 v3 absolute-path request"),
        binding(RESOURCE, "conditional R008 RAM-cap and transient scheduling admission"),
        binding(CAPABILITY, "verified rootless systemd cgroup-v2 process-tree capability"),
        binding(INDEPENDENT_REVIEW, "independent conditional R008 design review for CPU/native preflight only"),
        binding(R007_AUTH, "zero-credit R007 geometry audit contract and historical one-shot closure"),
        binding(R007_PREFLIGHT, "passed R007 native geometry analogue; never reused as credit"),
        binding(SCOPED_COMMAND, "R008 capped-scope child runner and memory telemetry"),
        binding(EXECUTOR, "R008 resource-gated one-shot CPU/native executor"),
        binding(BUILDER, "R008 one-shot authorization builder"),
        binding(TESTS, "R008 authorization, gate, and fail-closed tests"),
        binding(AUDIT_HELPERS, "audited generated geometry and decoded native-array checks"),
        binding(NATIVE_HELPERS, "pinned BI4 native array reader and particle-group parser"),
        binding(NATIVE_RUNNER, "pinned native BI4 audit dependency"),
        binding(GEOMETRY_REVIEW, "pinned R007 binary-VTK geometry parser"),
        binding(Path("tests/test_f8_r006_cpu_native_preflight_v1.py"), "tests for inherited geometry/native hard gates"),
        binding(Path("tests/test_f8_r007_cpu_native_preflight_v1.py"), "tests for prior R007 one-shot audit contract"),
        binding(Path("tests/test_f8_r003_cpu_native_preflight_v1.py"), "tests for inherited BI4 native array reader"),
        binding(Path("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"), "official CPU GenCase binary"),
        binding(Path("campaigns/l1-resume/artifacts/bi4_dump"), "pinned native BI4 decoder binary"),
    ]
    candidates.extend(request["source_bindings"])
    candidates.extend(request["all_r008_inputs"]["bindings"])
    candidates.extend((gencase, decoder))
    bindings = _unique_bindings(candidates)
    for item in bindings:
        verify_binding(item)

    runtime = {
        "systemd_run": binding(Path(systemd_path), "rootless systemd-run used to apply MemoryMax"),
        "systemctl": binding(Path(systemctl_path), "read-only probe of the rootless systemd user manager"),
        "python_interpreter": binding(Path(sys.executable).resolve(), "Python interpreter for scoped telemetry wrapper"),
    }
    templates = request["proposed_preflight_only"]["argv_templates_not_executed"]
    return {
        "schema": SCHEMA,
        "record_id": "f8-oscillatory-pressure-channel-r008-cpu-native-preflight-authorization-v1",
        "scope_id": request["scope_id"],
        "status": "authorized_for_exactly_one_r008_cpu_native_preflight",
        "authorization_basis": {
            "principal": "user",
            "user_statement": "你不需要再询问我，你接下来的任务探索的授权我都批准了。",
            "scope_interpretation": "This approval is applied narrowly to one representative CPU GenCase plus native BI4 decode, solely to measure cap behavior and validate generated/native input geometry.",
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
        "request_reference": binding(REQUEST, "request being granted this separate one-shot authority"),
        "independent_review_reference": binding(INDEPENDENT_REVIEW, "Terra-model independent static design review; model identity not separately attested"),
        "target_case": request["target_case"],
        "output_namespace": {
            "path": request["proposed_preflight_only"]["runtime_output_namespace"],
            "must_be_absent_before_start": True,
            "reuse_or_retry_allowed": False,
        },
        "native_tools": {
            "gencase": gencase,
            "native_decoder": decoder,
            "gencase_argv_template": templates["gencase"],
            "native_decode_argv_template": templates["native_decode"],
            "working_directory": templates["working_directory"],
            "max_gencase_invocations": 1,
            "max_native_decode_invocations": 1,
        },
        "hard_gates": audit["hard_gates"],
        "resource_scope": {
            "memory_max_bytes": MEMORY_MAX_BYTES,
            "memory_accounting": True,
            "cpu_only": True,
            "native_child_cpu_affinity": "one CPU from current affinity mask; descendants inherit",
            "gpu": False,
            "max_concurrent_native_processes": 1,
            "gencase_timeout_seconds": 900,
            "native_decode_timeout_seconds": 300,
            "capture_cgroup_memory_peak": True,
            "capture_memory_events": True,
            "capture_sampled_cgroup_process_tree_rss": True,
            "cap_pressure_or_oom_fails_preflight": True,
            "prelaunch_gates": {
                "cpu_affinity_count_minimum": 1,
                "load_average_1m_maximum": "cpu_affinity_count",
                "available_memory_bytes_minimum": MIN_AVAILABLE_MEMORY_BYTES,
                "free_disk_bytes_minimum": MIN_FREE_DISK_BYTES,
                "f3_material_row30_worker_must_be_absent": True,
                "systemd_user_manager_must_be_responsive": True,
                "transient_scope_names_must_be_unused": True,
                "cgroup_v2_and_systemd_run_must_be_available": True,
            },
        },
        "permissions": {
            "cpu_gencase": True,
            "native_decode": True,
            "solver": False,
            "gpu": False,
            "queue": False,
            "scheduler": False,
            "worker": False,
            "registry": False,
            "ledger": False,
            "training": False,
            "qualification": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_policy": {
            "exactly_one_gencase_before_any_native_decode": True,
            "at_most_one_native_decode": True,
            "decode_only_after_gencase_geometry_and_control_copy_gates_pass": True,
            "fail_closed_on_any_error_timeout_cap_pressure_or_oom": True,
            "same_input_retry_forbidden": True,
            "output_reuse_forbidden": True,
            "resource_block_defers_without_output_namespace_or_lock": True,
            "resource_gate_rechecked_immediately_before_lock": True,
            "no_solver_gpu_queue_worker_registry_ledger_training_or_qualification": True,
        },
        "geometry_analogue": {
            "r007_geometry_subtree_matches_r008_anchor": True,
            "r007_passed_native_preflight_is_audit_contract_only": True,
            "r007_outputs_not_reused": True,
        },
        "runtime_bindings": runtime,
        "bindings": bindings,
    }


def write_authorization(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    target = target.resolve()
    if target != (LAB / OUTPUT).resolve():
        raise ValueError("only the registered immutable R008 authorization path is permitted")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to replace immutable F8 R008 authorization: {target}")
    value = build_authorization()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, target)
    partial.unlink()
    parent_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return value


if __name__ == "__main__":
    authorization = write_authorization()
    print(json.dumps({key: authorization[key] for key in ("schema", "status", "scope_id", "qualification_credit", "output_namespace", "resource_scope", "permissions")}, indent=2))
