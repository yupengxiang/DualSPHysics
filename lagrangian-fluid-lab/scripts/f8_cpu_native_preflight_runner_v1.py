#!/usr/bin/env python3
"""Build (but never execute) F8's one-shot CPU/native preflight argv.

This module has deliberately no process-launching API.  It validates the
immutable authorization receipt and an as-yet-unused output namespace, then
returns the two commands that a separately authorized execution step may use.
It does not create the namespace or any output file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
AUTHORIZATION = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
OUTPUT_DIR = LAB / ROOT / "cpu-native-preflight-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = LAB / path
    return path.resolve()


def load_authorization(path: Path = LAB / AUTHORIZATION) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("F8 CPU/native authorization must be a JSON object")
    return value


def validate_authorization(authorization: dict[str, Any]) -> None:
    if not (
        authorization.get("schema") == "core.cfd.f8.cpu_native_preflight_authorization.v1"
        and authorization.get("status") == "authorized_for_exactly_one_cpu_native_preflight"
        and authorization.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
        and authorization.get("qualification_claim") == "none"
        and authorization.get("qualification_credit") == 0
    ):
        raise PermissionError("F8 CPU/native authorization is not an active zero-credit one-shot authorization")
    permissions = authorization.get("permissions", {})
    if not (
        permissions.get("cpu_gencase") is True
        and permissions.get("native_decode") is True
        and all(permissions.get(key) is False for key in ("solver", "gpu", "queue", "registry", "ledger", "training", "qualification"))
        and all(permissions.get(key) == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"))
    ):
        raise PermissionError("F8 authorization opens a prohibited execution surface")
    policy = authorization.get("execution_policy", {})
    if not all(policy.get(key) is True for key in (
        "exactly_one_cpu_gencase", "exactly_one_native_decode", "fail_closed_on_any_failure",
        "same_input_retry_forbidden", "preflight_output_reuse_forbidden",
    )):
        raise PermissionError("F8 authorization does not freeze one-shot failure policy")
    for item in authorization.get("bindings", []):
        if not isinstance(item, dict):
            raise ValueError("F8 authorization binding is malformed")
        path = _resolve(str(item.get("path", "")))
        if not path.is_file():
            raise FileNotFoundError(f"F8 authorization binding is missing: {path}")
        if item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            raise ValueError(f"F8 authorization binding changed: {path}")


def validate_output_namespace(output_dir: Path) -> Path:
    output_dir = Path(output_dir).resolve()
    if output_dir != OUTPUT_DIR.resolve():
        raise ValueError("F8 runner only accepts its registered cpu-native-preflight-v1 namespace")
    if output_dir.exists():
        raise RuntimeError("F8 one-shot CPU/native preflight output already exists; retry or reuse is forbidden")
    return output_dir


def build_execution_plan(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    """Validate the closed receipt and construct commands without executing them."""
    authorization = load_authorization()
    validate_authorization(authorization)
    output = validate_output_namespace(output_dir)
    single_input = authorization["single_input"]
    definition = _resolve(single_input["definition"]["path"])
    control = _resolve(single_input["control"]["path"])
    binaries = authorization["cpu_native_entry"]
    gencase = _resolve(binaries["gencase_binary"]["path"])
    decoder = _resolve(binaries["native_decoder"]["path"])
    prefix = output / "generated" / "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
    native_output = output / "native-initial"
    return {
        "schema": "core.cfd.f8.cpu_native_preflight_runner_plan.v1",
        "status": "validated_argv_only_not_executed",
        "authorization": str(AUTHORIZATION),
        "input": {"definition": str(definition), "control": str(control)},
        "output_namespace": str(output),
        "commands": {
            "cpu_gencase": [str(gencase), str(definition.with_suffix("")), str(prefix), "-save:all"],
            "native_decode": [str(decoder), str(prefix.with_suffix(".bi4")), str(native_output)],
        },
        "execution_controls": {
            "cpu_gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
            "qualification_credit": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(build_execution_plan(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
