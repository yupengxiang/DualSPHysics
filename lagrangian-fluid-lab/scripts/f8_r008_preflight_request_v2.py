#!/usr/bin/env python3
"""Build a static F8 R008 preflight request with a tested 4-GiB cgroup cap.

This version reuses only the immutable request-v1 inputs.  It does not create
the runtime namespace, invoke GenCase/native decode, or grant execution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_r008_preflight_request_v1 as request_v1


LAB = request_v1.LAB
ROOT = request_v1.ROOT
REQUEST_V1 = ROOT / "cpu-native-preflight-request-v1/request.json"
RESOURCE_ADMISSION = ROOT / "resource-admission-v1/receipt.json"
CAPABILITY_PROBE = ROOT / "resource-capability-probe-v1/receipt.json"
BUILDER = Path("scripts/f8_r008_preflight_request_v2.py")
TESTS = Path("tests/test_f8_r008_preflight_request_v2.py")
REQUEST = ROOT / "cpu-native-preflight-request-v2/request.json"
RUNTIME_NAMESPACE = ROOT / "cpu-native-preflight-v2"
SCHEMA = "core.cfd.f8.r008_cpu_native_preflight_request.v2"
RAM_LIMIT_MIB = 4096
RAM_LIMIT_BYTES = RAM_LIMIT_MIB * 1024**2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reference(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {
        "path": str(path.relative_to(LAB)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "role": role,
    }


def _verify_reference(ref: dict[str, Any]) -> Path:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ValueError("a portable, hash-bound input reference is required")
    relative = Path(ref["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"input reference escapes the lab root: {relative}")
    path = LAB / relative
    if (not path.is_file() or path.stat().st_size != ref.get("bytes")
            or sha256(path) != ref.get("sha256")):
        raise ValueError(f"bound input changed: {relative}")
    return path


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def build_request() -> dict[str, Any]:
    """Validate v1 evidence and return an immutable, no-authority v2 request."""
    base = request_v1.build_request()
    if base.get("status") != "request_ready_requires_separate_explicit_runtime_authorization":
        raise ValueError("R008 v1 request is not the expected zero-authority source")
    if base.get("execution_controls", {}).get("gencase_invoked") is not False:
        raise ValueError("R008 v1 request records native execution unexpectedly")

    resource = _load_object(LAB / RESOURCE_ADMISSION)
    probe = _load_object(LAB / CAPABILITY_PROBE)
    probe_assessment = probe.get("assessment", {})
    probe_scope = probe.get("probe", {})
    if not (
        resource.get("schema") == "core.cfd.f8_r008_resource_admission.v1"
        and resource.get("resource_decision", {}).get("proposed_ram_limit_mib") == RAM_LIMIT_MIB
        and probe.get("schema") == "core.cfd.f8_r008_rootless_cgroup_memory_capability_probe.v1"
        and probe_scope.get("systemd_memory_max_bytes") == RAM_LIMIT_BYTES
        and probe_scope.get("cgroup_memory_max_bytes") == RAM_LIMIT_BYTES
        and probe_scope.get("parent_and_child_same_cgroup") is True
        and probe_assessment.get("cap_pressure_or_oom_behavior_tested") is False
        and probe_assessment.get("native_workload_peak_rss_measured") is False
    ):
        raise ValueError("R008 resource cap evidence is missing, mismatched, or overclaims the probe")

    v1_ref = reference(LAB / REQUEST_V1, "immutable zero-authority R008 v1 input request")
    resource_ref = reference(LAB / RESOURCE_ADMISSION, "conditional R008 resource admission decision")
    probe_ref = reference(LAB / CAPABILITY_PROBE, "rootless systemd cgroup capability probe")
    source_candidates = [
        *base["all_r008_inputs"]["source_bindings"],
        v1_ref,
        resource_ref,
        probe_ref,
        reference(LAB / BUILDER, "R008 v2 request builder"),
        reference(LAB / TESTS, "R008 v2 request and zero-execution tests"),
    ]
    source_by_path: dict[str, dict[str, Any]] = {}
    for item in source_candidates:
        previous = source_by_path.get(item["path"])
        if previous is None:
            source_by_path[item["path"]] = item
            continue
        if (previous["bytes"], previous["sha256"]) != (item["bytes"], item["sha256"]):
            raise ValueError(f"duplicate R008 source path has conflicting identities: {item['path']}")
        roles = set(previous.get("also_roles", [previous.get("role")]))
        roles.add(item["role"])
        previous["also_roles"] = sorted(role for role in roles if role)
    sources = list(source_by_path.values())
    for item in sources:
        _verify_reference(item)

    if RUNTIME_NAMESPACE.exists() or RUNTIME_NAMESPACE.is_symlink():
        raise FileExistsError(f"fresh R008 v2 runtime namespace is occupied: {RUNTIME_NAMESPACE}")

    result = json.loads(json.dumps(base))
    result.update({
        "schema": SCHEMA,
        "record_id": "f8-oscillatory-pressure-channel-r008-cpu-native-preflight-request-v2",
        "status": "request_ready_with_cgroup_cap_mechanism_verified_peak_unmeasured",
        "request_only": True,
        "authorization": {
            "this_request_grants_execution": False,
            "separate_explicit_runtime_authorization_required_before_native_tools": True,
            "qualification_claim": "none",
            "qualification_credit": 0,
        },
    })
    result["proposed_preflight_only"]["runtime_output_namespace"] = str(RUNTIME_NAMESPACE)
    result["proposed_preflight_only"]["runtime_output_namespace_must_be_absent_before_future_authorized_start"] = True
    result["proposed_preflight_only"]["runtime_output_namespace_created_by_this_request"] = False
    result["proposed_preflight_only"]["proposed_resource_envelope"].update({
        "ram_limit_mib": RAM_LIMIT_MIB,
        "ram_limit_bytes": RAM_LIMIT_BYTES,
        "ram_limit_semantics": "kernel-enforced cgroup-v2 MemoryMax for the complete transient systemd scope",
        "ram_cap_application_probe": probe_ref,
        "peak_capture": ["cgroup-v2 memory.peak", "sampled process-tree RSS", "memory.events"],
        "cap_pressure_tested": False,
        "native_peak_measured": False,
        "ram_limit_note": "systemd/cgroup application verified; R008 native-tool peak remains unmeasured",
    })
    base_commands = base["proposed_preflight_only"]["argv_templates_not_executed"]
    case_id = base["target_case"]["case_id"]
    gencase_argv = list(base_commands["gencase"])
    gencase_argv[2] = str(RUNTIME_NAMESPACE / "generated" / case_id)
    decoder_argv = list(base_commands["native_decode"])
    decoder_argv[1] = str(RUNTIME_NAMESPACE / "generated" / f"{case_id}.bi4")
    decoder_argv[2] = str(RUNTIME_NAMESPACE / "native-initial")
    result["proposed_preflight_only"]["argv_templates_not_executed"] = {
        "gencase": [
            "systemd-run", "--user", "--scope",
            "--unit=f8-r008-cpu-preflight-gencase",
            f"--property=MemoryMax={RAM_LIMIT_BYTES}",
            "--property=MemoryAccounting=yes", "--",
            *gencase_argv,
        ],
        "native_decode": [
            "systemd-run", "--user", "--scope",
            "--unit=f8-r008-cpu-preflight-native-decode",
            f"--property=MemoryMax={RAM_LIMIT_BYTES}",
            "--property=MemoryAccounting=yes", "--",
            *decoder_argv,
        ],
        "working_directory": base["proposed_preflight_only"]["argv_templates_not_executed"]["working_directory"],
    }
    result["proposed_preflight_only"]["runtime_output_namespace"] = str(RUNTIME_NAMESPACE)
    result["resource_admission_reference"] = resource_ref
    result["capability_probe_reference"] = probe_ref
    result["request_v1_reference"] = v1_ref
    result["source_bindings"] = sources
    result["execution_controls"] = {
        "request_builder_executed_native_tool": False,
        "gencase_invoked": False,
        "native_decode_invoked": False,
        "solver_invoked": False,
        "gpu_started": False,
        "worker_started": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "runtime_namespace_created": False,
        "qualification_credit": 0,
    }
    result["permissions"] = {
        "gencase": False, "native_decode": False, "solver": False, "gpu": False,
        "worker": False, "queue": False, "scheduler": False, "registry": False,
        "ledger": False, "training": False, "qualification": False,
        "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0,
        "denominator_mutation": 0,
    }
    result["lineage_exclusions"] = {
        "r001_to_r007_scopes_retried": False,
        "prior_outputs_reused": False,
        "qualification_only_case": True,
        "same_input_retry_allowed": False,
    }
    return result


def write_request() -> Path:
    path = LAB / REQUEST
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 v2 request: {path}")
    if path.parent.exists() or path.parent.is_symlink():
        raise FileExistsError(f"refusing to reuse R008 v2 request directory: {path.parent}")
    request = build_request()
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable static request once")
    args = parser.parse_args()
    if args.write:
        print(write_request().relative_to(LAB))
    else:
        print(json.dumps(build_request(), indent=2, sort_keys=True))
