#!/usr/bin/env python3
"""Validate F8 r002's sealed admission and construct, but never run, argv."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002")
AUTHORIZATION = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
OUTPUT = LAB / ROOT / "cpu-native-preflight-v1"
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(text: str) -> Path:
    path = Path(text)
    return (path if path.is_absolute() else LAB / path).resolve()


def load_authorization(path: Path = LAB / AUTHORIZATION) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("F8 r002 authorization must be a JSON object")
    return value


def validate_authorization(value: dict[str, Any]) -> None:
    if not (value.get("schema") == "core.cfd.f8.r002_cpu_native_preflight_authorization.v1" and value.get("scope_id") == SCOPE and value.get("status") == "authorized_for_exactly_one_r002_cpu_native_preflight" and value.get("qualification_credit") == 0):
        raise PermissionError("F8 r002 authorization is not an active zero-credit one-shot admission")
    permissions = value.get("permissions", {})
    if not (permissions.get("cpu_gencase") is True and permissions.get("native_decode") is True and all(permissions.get(key) is False for key in ("solver", "gpu", "queue", "worker", "registry", "ledger", "training", "qualification")) and all(permissions.get(key) == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"))):
        raise PermissionError("F8 r002 authorization opens a prohibited execution surface")
    for item in value.get("bindings", []):
        path = _resolve(str(item.get("path", "")))
        if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            raise ValueError(f"F8 r002 authorization binding changed: {path}")


def build_execution_plan(output: Path = OUTPUT) -> dict[str, Any]:
    value = load_authorization()
    validate_authorization(value)
    output = Path(output).resolve()
    if output != OUTPUT.resolve():
        raise ValueError("only the registered F8 r002 output namespace is permitted")
    if output.exists():
        raise RuntimeError("F8 r002 output already exists; retry or reuse is forbidden")
    definition = _resolve(value["single_input"]["definition"]["path"])
    control = _resolve(value["single_input"]["control"]["path"])
    prefix = output / "generated" / SCOPE
    return {
        "authorization": str(AUTHORIZATION), "output_namespace": str(output),
        "input": {"definition": str(definition), "control": str(control)},
        "commands": {
            "cpu_gencase": [str(_resolve(value["cpu_native_entry"]["gencase_binary"]["path"])), str(definition.with_suffix("")), str(prefix), "-save:all"],
            "native_decode": [str(_resolve(value["cpu_native_entry"]["native_decoder"]["path"])), str(prefix.with_suffix(".bi4")), str(output / "native-initial")],
        },
    }
