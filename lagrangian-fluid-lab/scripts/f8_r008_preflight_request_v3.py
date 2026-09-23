#!/usr/bin/env python3
"""Build a zero-authority F8 R008 request with absolute native-tool paths.

The unexecuted v2 request is retained as a superseded audit artifact: its
native argv used repository-relative paths despite declaring a nested working
directory.  This builder closes that ambiguity without invoking any tool.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_r008_preflight_request_v2 as request_v2


LAB = request_v2.LAB
ROOT = request_v2.ROOT
REQUEST_V2 = ROOT / "cpu-native-preflight-request-v2/request.json"
BUILDER = Path("scripts/f8_r008_preflight_request_v3.py")
TESTS = Path("tests/test_f8_r008_preflight_request_v3.py")
REQUEST = ROOT / "cpu-native-preflight-request-v3/request.json"
RUNTIME_NAMESPACE = ROOT / "cpu-native-preflight-v3"
SCHEMA = "core.cfd.f8.r008_cpu_native_preflight_request.v3"
RAM_LIMIT_BYTES = 4096 * 1024**2


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


def _verify_reference(item: dict[str, Any]) -> Path:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ValueError("a hash-bound source reference is required")
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"source reference escapes the lab root: {relative}")
    path = LAB / relative
    if (not path.is_file() or path.stat().st_size != item.get("bytes")
            or sha256(path) != item.get("sha256")):
        raise ValueError(f"bound source changed: {relative}")
    return path


def _bound_sources(base: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        *base["source_bindings"],
        reference(LAB / REQUEST_V2, "superseded, unexecuted R008 v2 request"),
        reference(LAB / BUILDER, "R008 v3 absolute-path request builder"),
        reference(LAB / TESTS, "R008 v3 path and zero-execution tests"),
    ]
    by_path: dict[str, dict[str, Any]] = {}
    for item in candidates:
        previous = by_path.get(item["path"])
        if previous is None:
            by_path[item["path"]] = item
            continue
        if (previous["bytes"], previous["sha256"]) != (item["bytes"], item["sha256"]):
            raise ValueError(f"duplicate source path has conflicting identities: {item['path']}")
        roles = set(previous.get("also_roles", [previous.get("role")]))
        roles.add(item["role"])
        previous["also_roles"] = sorted(role for role in roles if role)
    sources = list(by_path.values())
    for item in sources:
        _verify_reference(item)
    return sources


def build_request() -> dict[str, Any]:
    """Return a hash-closed v3 request; do not create runtime state or execute."""
    base = request_v2.build_request()
    v2_path = LAB / REQUEST_V2
    if not v2_path.is_file():
        raise FileNotFoundError(f"superseded v2 request is missing: {v2_path}")
    v2_record = json.loads(v2_path.read_text(encoding="utf-8"))
    if not isinstance(v2_record, dict) or v2_record.get("request_only") is not True:
        raise ValueError("the superseded R008 v2 request is not a request-only record")

    if RUNTIME_NAMESPACE.exists() or RUNTIME_NAMESPACE.is_symlink():
        raise FileExistsError(f"fresh R008 v3 runtime namespace is occupied: {RUNTIME_NAMESPACE}")

    target = base["target_case"]
    definition_ref = target["definition"]
    bound_definition = next(
        (item for item in base["all_r008_inputs"]["bindings"]
         if item["path"] == definition_ref["path"]),
        None,
    )
    if not bound_definition or any(
        bound_definition.get(key) != definition_ref.get(key)
        for key in ("bytes", "sha256")
    ):
        raise ValueError("R008 representative Definition is not the exact hash-bound input")

    gencase = (LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64").resolve()
    decoder = (LAB / "campaigns/l1-resume/artifacts/bi4_dump").resolve()
    definition_prefix = (LAB / definition_ref["path"]).resolve().with_suffix("")
    output_prefix = (LAB / RUNTIME_NAMESPACE / "generated" / target["case_id"]).resolve()
    decoded_output = (LAB / RUNTIME_NAMESPACE / "native-initial").resolve()
    working_directory = str((LAB / definition_ref["path"]).resolve().parent)

    result = json.loads(json.dumps(base))
    result.update({
        "schema": SCHEMA,
        "record_id": "f8-oscillatory-pressure-channel-r008-cpu-native-preflight-request-v3",
        "status": "request_ready_with_cgroup_cap_probe_verified_absolute_paths_peak_unmeasured",
        "supersedes": {
            "request": reference(v2_path, "superseded, unexecuted R008 v2 request"),
            "status": "superseded_not_executed",
            "reason": (
                "v2 native argv used repository-relative paths while declaring a nested "
                "Definition working directory; v3 uses absolute executable, input, and output paths"
            ),
            "v2_native_tool_invocations": 0,
            "v2_runtime_namespace_created": False,
        },
        "request_only": True,
        "authorization": {
            "this_request_grants_execution": False,
            "separate_explicit_runtime_authorization_required_before_native_tools": True,
            "qualification_claim": "none",
            "qualification_credit": 0,
        },
    })
    proposed = result["proposed_preflight_only"]
    proposed["runtime_output_namespace"] = str(RUNTIME_NAMESPACE)
    proposed["runtime_output_namespace_must_be_absent_before_future_authorized_start"] = True
    proposed["runtime_output_namespace_created_by_this_request"] = False
    proposed["working_directory_is_informational_absolute_paths_do_not_depend_on_it"] = True
    proposed["argv_templates_not_executed"] = {
        "gencase": [
            "systemd-run", "--user", "--scope",
            "--unit=f8-r008-cpu-preflight-v3-gencase",
            f"--property=MemoryMax={RAM_LIMIT_BYTES}",
            "--property=MemoryAccounting=yes", "--",
            str(gencase), str(definition_prefix), str(output_prefix), "-save:all",
        ],
        "native_decode": [
            "systemd-run", "--user", "--scope",
            "--unit=f8-r008-cpu-preflight-v3-native-decode",
            f"--property=MemoryMax={RAM_LIMIT_BYTES}",
            "--property=MemoryAccounting=yes", "--",
            str(decoder), str(output_prefix.with_suffix(".bi4")), str(decoded_output),
        ],
        "working_directory": working_directory,
    }
    result["source_bindings"] = _bound_sources(base)
    result["source_binding_count"] = len(result["source_bindings"])
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
    return result


def write_request() -> Path:
    path = LAB / REQUEST
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 v3 request: {path}")
    if path.parent.exists() or path.parent.is_symlink():
        raise FileExistsError(f"refusing to reuse R008 v3 request directory: {path.parent}")
    value = build_request()
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
