#!/usr/bin/env python3
"""Validate F8 r007's sealed admission and construct argv without execution."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from scripts import f8_r007_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r007_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
ROOT = design.ROOT
AUTHORIZATION = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
OUTPUT = LAB / design.PREFLIGHT_ROOT
SCOPE = design.SCOPE


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(text: str) -> Path:
    path = Path(text)
    return (path if path.is_absolute() else LAB / path).resolve()


def validate_authorization(value: dict[str, Any]) -> None:
    if not (
        value.get("schema") == "core.cfd.f8.r007_cpu_native_preflight_authorization.v1"
        and value.get("scope_id") == SCOPE
        and value.get("status") == "authorized_for_exactly_one_r007_cpu_native_preflight"
        and value.get("qualification_credit") == 0
        and value.get("retained_previous_failure", {}).get("scope_id", "").endswith("R006")
        and value.get("retained_previous_failure", {}).get("same_input_retry_forbidden") is True
    ):
        raise PermissionError("F8 r007 authorization is not a fresh, zero-credit one-shot admission")
    permissions, policy = value.get("permissions", {}), value.get("execution_policy", {})
    if not (
        permissions.get("cpu_gencase") is True and permissions.get("native_decode") is True
        and all(permissions.get(key) is False for key in (
            "solver", "gpu", "queue", "worker", "registry", "ledger", "training", "qualification"
        ))
        and all(permissions.get(key) == 0 for key in (
            "queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"
        ))
        and policy.get("exactly_one_cpu_gencase") is True
        and policy.get("at_most_one_native_decode") is True
        and policy.get("generated_geometry_and_control_gates_before_decode") is True
        and policy.get("fail_closed_on_any_failure") is True
        and policy.get("same_input_retry_forbidden") is True
        and policy.get("preflight_output_reuse_forbidden") is True
    ):
        raise PermissionError("F8 r007 authorization opens a prohibited execution surface or lacks fail-closed policy")
    for item in value.get("bindings", []):
        path = resolve(str(item.get("path", "")))
        if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            raise ValueError(f"F8 r007 authorization binding changed: {path}")


def build_execution_plan(output: Path = OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output != OUTPUT.resolve():
        raise ValueError("only the registered F8 r007 output namespace is permitted")
    if output.exists():
        raise RuntimeError("F8 r007 output already exists; retry or reuse is forbidden")
    value = authorization.load(AUTHORIZATION)
    validate_authorization(value)
    definition = resolve(value["single_input"]["definition"]["path"])
    control = resolve(value["single_input"]["control"]["path"])
    prefix = output / "generated" / SCOPE
    return {
        "authorization": str(AUTHORIZATION), "output_namespace": str(output),
        "input": {"definition": str(definition), "control": str(control)},
        "generated": {
            "prefix": str(prefix), "definition": str(prefix.with_suffix(".xml")),
            "bi4": str(prefix.with_suffix(".bi4")), "bound_vtk": str(prefix) + "_Bound.vtk",
            "fluid_vtk": str(prefix) + "_Fluid.vtk", "hdp_actual_vtk": str(prefix) + "_hdp_Actual.vtk",
            "control_copy": str(prefix.parent / control.name),
        },
        "commands": {
            "cpu_gencase": [
                str(resolve(value["cpu_native_entry"]["gencase_binary"]["path"])),
                str(definition.with_suffix("")), str(prefix), "-save:all",
            ],
            "native_decode": [
                str(resolve(value["cpu_native_entry"]["native_decoder"]["path"])),
                str(prefix.with_suffix(".bi4")), str(output / "native-initial"),
            ],
        },
    }


if __name__ == "__main__":
    print(build_execution_plan())
