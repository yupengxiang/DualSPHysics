#!/usr/bin/env python3
"""Build a static, zero-authority request for one F8 R008 CPU/native preflight.

This module reads only JSON, XML, CSV, and source text.  It verifies the
hash-closed R008 Definition/control pack and proposes a bounded GenCase/native
decode check, but grants no permission and invokes no native or runtime tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCOPE_RECEIPT = ROOT / "t1-scope-design-v1/receipt.json"
PACK_RECEIPT = ROOT / "definition-control-pack-v1/receipt.json"
R007_AUTHORIZATION = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r007/"
    "cpu-native-preflight-authorization-v1/authorization.json"
)
REQUEST = ROOT / "cpu-native-preflight-request-v1/request.json"
RUNTIME_NAMESPACE = ROOT / "cpu-native-preflight-v1"
REPRESENTATIVE_CASE_ID = "space-q0p5-dp0p0075"
SCHEMA = "core.cfd.f8.r008_cpu_native_preflight_request.v1"
BUILDER = Path("scripts/f8_r008_preflight_request_v1.py")
TESTS = Path("tests/test_f8_r008_preflight_request_v1.py")
ALLOWED_INPUT_SUFFIXES = {".xml", ".csv"}
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".npz"}


def _absolute(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (LAB / candidate).resolve()


def _relative(path: str | Path) -> str:
    return str(_absolute(path).relative_to(LAB))


def _sha256(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValueError(f"static request builder refuses binary trajectory access: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = _absolute(path)
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {resolved}")
    return value


def _reference(path: str | Path, role: str) -> dict[str, Any]:
    resolved = _absolute(path)
    if resolved.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValueError(f"static request builder refuses binary trajectory binding: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved.relative_to(LAB)),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
        "role": role,
    }


def _verify_declared_binding(item: dict[str, Any], role: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("declared binding must be an object")
    raw_path = item.get("path")
    if not isinstance(raw_path, str):
        raise ValueError("declared binding path must be a string")
    resolved = _absolute(raw_path)
    suffix = resolved.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        raise ValueError(f"R008 static request may not read or bind trajectory data: {raw_path}")
    if suffix not in ALLOWED_INPUT_SUFFIXES and role == "R008 Definition/control input":
        raise ValueError(f"unexpected R008 input type: {raw_path}")
    observed = _reference(resolved, role)
    if (observed["bytes"] != item.get("bytes")
            or observed["sha256"] != item.get("sha256")):
        raise ValueError(f"R008 static binding changed: {raw_path}")
    return observed


def _verify_source_binding(item: dict[str, Any]) -> dict[str, Any]:
    observed = _verify_declared_binding(item, "R008 static source dependency")
    if observed["path"] != _relative(item["path"]):
        raise ValueError("source dependency path normalization changed")
    return observed


def _require_absent_runtime_namespace() -> None:
    target = LAB / RUNTIME_NAMESPACE
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"fresh R008 preflight namespace is occupied: {RUNTIME_NAMESPACE}")


def _validate_predecessors() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scope = _load_json(SCOPE_RECEIPT)
    pack = _load_json(PACK_RECEIPT)
    r007 = _load_json(R007_AUTHORIZATION)
    if not (
        scope.get("scope_id") == SCOPE_ID
        and scope.get("status") == "static_scope_design_candidate_ready_for_independent_review"
        and scope.get("qualification_credit") == 0
        and scope.get("qualification_claim") == "none"
        and scope.get("lineage_and_execution_boundary", {}).get("execution_authority_granted") is False
        and scope.get("lineage_and_execution_boundary", {}).get("r007_native_preflight_reused_as_T1_credit") is False
    ):
        raise PermissionError("R008 scope receipt is not the expected static zero-credit candidate")
    if not (
        pack.get("schema") == "core.cfd.f8.r008_definition_control_pack.v1"
        and pack.get("scope_id") == SCOPE_ID
        and pack.get("status") == "static_definition_control_pack_materialized_no_execution_authority"
        and pack.get("qualification_credit") == 0
        and pack.get("execution_authority", {}).get("gencase_authorized") is False
        and pack.get("execution_authority", {}).get("native_decoder_authorized") is False
        and pack.get("execution_authority", {}).get("solver_authorized") is False
        and pack.get("execution_authority", {}).get("t1_qualification_authorized") is False
        and pack.get("execution_controls", {}).get("gencase_invoked") is False
        and pack.get("execution_controls", {}).get("native_decode_invoked") is False
        and pack.get("execution_controls", {}).get("solver_invoked") is False
    ):
        raise PermissionError("R008 Definition/control pack is not a static zero-credit materialization")
    if not (
        r007.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R007"
        and r007.get("status") == "authorized_for_exactly_one_r007_cpu_native_preflight"
        and r007.get("qualification_credit") == 0
        and r007.get("permissions", {}).get("solver") is False
        and r007.get("permissions", {}).get("gpu") is False
    ):
        raise ValueError("R007 tool-reference record is not the expected historical authorization")
    return scope, pack, r007


def build_request() -> dict[str, Any]:
    scope, pack, r007 = _validate_predecessors()
    _require_absent_runtime_namespace()

    declared_inputs = pack.get("input_bindings")
    if not isinstance(declared_inputs, list) or len(declared_inputs) != 94:
        raise ValueError("R008 pack must bind exactly 94 Definition/control input files")
    inputs = [_verify_declared_binding(item, "R008 Definition/control input")
              for item in declared_inputs]
    input_paths = [item["path"] for item in inputs]
    if len(set(input_paths)) != 94:
        raise ValueError("R008 input bindings must be unique")
    if any(not item["path"].startswith(str(ROOT) + "/") for item in inputs):
        raise ValueError("R008 input binding points outside the fresh R008 pack")

    declared_sources = pack.get("source_bindings")
    if not isinstance(declared_sources, list) or len(declared_sources) != 12:
        raise ValueError("R008 pack source closure must contain exactly 12 source bindings")
    sources = [_verify_source_binding(item) for item in declared_sources]
    sources.extend([
        _reference(SCOPE_RECEIPT, "frozen R008 T1 scope and qualification matrix"),
        _reference(PACK_RECEIPT, "hash-closed R008 Definition/control pack receipt"),
        _reference(R007_AUTHORIZATION, "historical R007 native-tool hash reference only"),
        _reference(BUILDER, "static R008 preflight-request generator"),
        _reference(TESTS, "static request and no-binary-access tests"),
    ])

    case = next((item for item in pack.get("cases", [])
                 if item.get("case_id") == REPRESENTATIVE_CASE_ID), None)
    if case is None or not case.get("qualification_only"):
        raise ValueError("R008 representative anchor case is missing or not qualification-only")
    definition = _verify_declared_binding(case["definition"], "R008 representative Definition")
    control = _verify_declared_binding(case["control"], "R008 colocated acceleration control")
    if definition["path"] not in input_paths or control["path"] not in input_paths:
        raise ValueError("representative Definition/control pair is not part of the 94-file pack")

    tool_entry = r007["cpu_native_entry"]
    gen_case = dict(tool_entry["gencase_binary"])
    decoder = dict(tool_entry["native_decoder"])
    if not (
        gen_case.get("path") == "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
        and decoder.get("path") == "campaigns/l1-resume/artifacts/bi4_dump"
    ):
        raise ValueError("historical pinned CPU native-tool identities changed")

    _require_absent_runtime_namespace()
    return {
        "schema": SCHEMA,
        "record_id": "f8-oscillatory-pressure-channel-r008-cpu-native-preflight-request-v1",
        "scope_id": SCOPE_ID,
        "status": "request_ready_requires_separate_explicit_runtime_authorization",
        "request_only": True,
        "authorization": {
            "this_request_grants_execution": False,
            "separate_explicit_user_authorization_required_before_any_native_tool": True,
            "qualification_claim": "none",
            "qualification_credit": 0,
        },
        "target_case": {
            "case_id": REPRESENTATIVE_CASE_ID,
            "qualification_only": True,
            "q": case["q"],
            "dp_m": case["dp_m"],
            "kind": case["kind"],
            "definition": definition,
            "control": control,
            "full_native_output_rows_to_timemax": case["full_native_output_rows_to_timemax"],
            "observation_output_count": case["expected_observation_output_count"],
            "native_output_samples_per_period": case["native_output_samples_per_period"],
        },
        "all_r008_inputs": {
            "definition_count": 47,
            "control_count": 47,
            "input_count": len(inputs),
            "bindings": inputs,
            "source_binding_count": len(sources),
            "source_bindings": sources,
        },
        "proposed_preflight_only": {
            "intent": "one representative R008 native geometry/input preflight; not a solver run or T1 qualification",
            "max_gencase_invocations": 1,
            "max_native_decode_invocations": 1,
            "solver_invocations": 0,
            "case_count": 1,
            "runtime_output_namespace": str(RUNTIME_NAMESPACE),
            "runtime_output_namespace_must_be_absent_before_future_authorized_start": True,
            "runtime_output_namespace_created_by_this_request": False,
            "retries_or_output_reuse_allowed": False,
            "argv_templates_not_executed": {
                "gencase": [
                    gen_case["path"],
                    definition["path"][:-4],
                    f"{RUNTIME_NAMESPACE}/generated/{REPRESENTATIVE_CASE_ID}",
                    "-save:all",
                ],
                "native_decode": [
                    decoder["path"],
                    f"{RUNTIME_NAMESPACE}/generated/{REPRESENTATIVE_CASE_ID}.bi4",
                    f"{RUNTIME_NAMESPACE}/native-initial",
                ],
                "working_directory": str(Path(definition["path"]).parent),
            },
            "cpu_native_tools_inherited_as_metadata_only": {
                "gencase_binary": gen_case,
                "native_decoder": decoder,
                "hashes_must_be_revalidated_before_any_future_execution": True,
            },
            "proposed_resource_envelope": {
                "cpu_workers": 1,
                "max_concurrent_native_processes": 1,
                "gpu_allowed": False,
                "queue_or_scheduler": False,
                "gencase_timeout_seconds": 900,
                "native_decode_timeout_seconds": 300,
                "ram_limit_mib": None,
                "ram_limit_note": "not measured for this R008 case; must be set by a separate resource-admission decision",
            },
            "proposed_fail_closed_checks": [
                "revalidate the exact R008 Definition/control and pinned binary hashes before any future authorized start",
                "require the generated acceleration control copy to match the bound R008 CSV bytes exactly",
                "require GenCase output to be readable and reconcile generated fluid/boundary identities with this Definition",
                "require native decode arrays to be finite, particle IDs unique, and boundary normals finite/nonzero",
                "stop before solver execution on any mismatch; preserve failure and grant zero T1/T2 credit",
            ],
        },
        "lineage_exclusions": {
            "r007_inputs_reused_as_r008_inputs": False,
            "r007_native_outputs_reused": False,
            "prior_r001_to_r007_same_input_retry_allowed": False,
            "production_cases_in_preflight": False,
        },
        "permissions": {
            "gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "worker": False,
            "queue": False,
            "scheduler": False,
            "registry": False,
            "ledger": False,
            "training": False,
            "qualification": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_controls": {
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
        },
    }


def write_request() -> Path:
    path = LAB / REQUEST
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 request: {path}")
    if path.parent.exists() or path.parent.is_symlink():
        raise FileExistsError(f"refusing to reuse R008 request directory: {path.parent}")
    request = build_request()
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the static request once")
    args = parser.parse_args(argv)
    if args.write:
        print(str(write_request().relative_to(LAB)))
    else:
        print(json.dumps(build_request(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
