#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Validate overlay labels against the actual V8 request and XML semantics.

The consumed overlay observer request records CLI label/value strings, but a
label is only meaningful when the terminal request's study metadata, solver
plan, command, and one-variable XML overlay agree.  This additive validator
performs that small-source check before an observer is allowed to consume a
terminal request.  It never opens BI4, native Part, HDF5, or full reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f3-s2.overlay-control-binding.v3"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
_FLOAT_TOLERANCE = 1.0e-12


def _resolved(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path is missing")
    return Path(value).expanduser().resolve()


def _regular(path: Path, label: str, *, max_bytes: int = 2 * 1024 * 1024) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{label} exceeds bounded source limit: {path.stat().st_size}")
    return path.resolve()


def _stat_tuple(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_ctime_ns), int(stat.st_dev), int(stat.st_ino)


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat_tuple(path)
    data = path.read_bytes()
    after = _stat_tuple(path)
    if before != after:
        raise ValueError(f"{label} changed while being read")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "stat_before": before, "stat_after": after, "stable_read": True}


def _source_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat_tuple(path)
    data = path.read_bytes()
    after = _stat_tuple(path)
    if before != after:
        raise ValueError(f"{label} changed while being read")
    return data, {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "stat_before": before, "stat_after": after, "stable_read": True}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{label} is not finite numeric data")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not finite numeric data") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} is not finite numeric data")
    return parsed


def _same_float(actual: Any, expected: float, label: str) -> float:
    value = _finite(actual, label)
    if abs(value - expected) > _FLOAT_TOLERANCE:
        raise ValueError(f"{label}={value} differs from expected {expected}")
    return value


def _sha256_file(path: Path, label: str) -> str:
    data, record = _source_bytes(path, label)
    return record["sha256"]


def _source_path(source: dict[str, Any], key: str, label: str) -> Path:
    item = source.get(key)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ValueError(f"{label} source path is missing")
    return _regular(Path(item["path"]), label)


def _declared_sha(source: dict[str, Any], key: str, actual: str, label: str) -> None:
    item = source.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"{label} source metadata is missing")
    declared = item.get("sha256")
    if not isinstance(declared, str) or declared.lower() != actual:
        raise ValueError(f"{label} source SHA differs")


def _command_value(command: Any, flag: str, label: str) -> str:
    if not isinstance(command, list):
        raise ValueError(f"{label} command is missing")
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"{label} command lacks {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"{label} command has no value after {flag}")
    return str(command[index + 1])


def _parameter(root: ET.Element, key: str, label: str) -> ET.Element:
    matches = [item for item in root.iter("parameter") if item.attrib.get("key") == key]
    if len(matches) != 1:
        raise ValueError(f"{label} expected one parameter {key!r}, got {len(matches)}")
    return matches[0]


def _cfl_values(root: ET.Element, label: str) -> list[float]:
    values = [_finite(item.attrib.get("value"), f"{label} cflnumber") for item in root.iter("cflnumber")]
    if not values:
        raise ValueError(f"{label} has no cflnumber elements")
    if any(abs(value - values[0]) > _FLOAT_TOLERANCE for value in values[1:]):
        raise ValueError(f"{label} has inconsistent cflnumber elements")
    return values


def _semantic_signature(element: ET.Element, variable: str) -> tuple[Any, ...]:
    attrs = dict(element.attrib)
    if variable == "CFLnumber" and element.tag == "cflnumber":
        attrs.pop("value", None)
    if variable == "TimeOut" and element.tag == "parameter" and attrs.get("key") == "TimeOut":
        attrs.pop("value", None)
    text = "" if element.text is None else " ".join(element.text.split())
    return (
        element.tag,
        tuple(sorted(attrs.items())),
        text,
        tuple(_semantic_signature(child, variable) for child in list(element)),
    )


def _load_xml(path: Path, label: str) -> tuple[ET.Element, dict[str, Any]]:
    data, record = _source_bytes(path, label)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"{label} is not valid XML") from exc
    return root, record


def _expected(label: str) -> dict[str, Any]:
    if label == "same_cfl_baseline":
        return {"study": None, "variable": "none", "base_cfl": 0.05, "overlay_cfl": 0.05, "base_tout": 0.01, "overlay_tout": 0.01, "value": "0.05/0.01"}
    if label == "half_cfl":
        return {"study": "ROOT173", "variable": "CFLnumber", "base_cfl": 0.05, "overlay_cfl": 0.025, "base_tout": 0.01, "overlay_tout": 0.01, "value": "0.025"}
    if label == "half_output":
        return {"study": "ROOT174", "variable": "TimeOut", "base_cfl": 0.05, "overlay_cfl": 0.05, "base_tout": 0.01, "overlay_tout": 0.005, "value": "0.005"}
    raise ValueError(f"unknown overlay label {label!r}")


def validate_overlay_binding(request_path: Path, overlay_label: str, overlay_variable: str, overlay_value: str) -> dict[str, Any]:
    """Validate CLI overlay metadata against the actual terminal q and XML."""

    expected = _expected(overlay_label)
    request, request_record = _small_json(request_path, "terminal overlay request")
    if request.get("schema") != "ds02.stage2.external-solver-request.v5":
        raise ValueError("terminal overlay request schema is not external-solver-request.v5")
    if request.get("physical_case_id") not in {None, PHYSICAL_CASE_ID}:
        raise ValueError("terminal overlay request physical case differs")
    source = request.get("source_provenance")
    if not isinstance(source, dict):
        raise ValueError("terminal overlay request lacks source_provenance")
    base_path = _source_path(source, "generated_xml", "base generated XML")
    base_bytes, base_record = _source_bytes(base_path, "base generated XML")
    base_sha = base_record["sha256"]
    _declared_sha(source, "generated_xml", base_sha, "base generated XML")
    input_sha = request.get("input_sha256")
    if not isinstance(input_sha, dict):
        raise ValueError("terminal overlay request lacks input_sha256")
    if input_sha.get(str(base_path)) != base_sha:
        raise ValueError("base generated XML SHA is absent or differs in request input_sha256")
    base_root = ET.fromstring(base_bytes)
    base_cfl = _cfl_values(base_root, "base generated XML")
    base_tout = _finite(_parameter(base_root, "TimeOut", "base generated XML").attrib.get("value"), "base generated XML TimeOut")

    plan = request.get("solver_plan")
    if not isinstance(plan, dict):
        raise ValueError("terminal overlay request lacks solver_plan")
    if plan.get("cflnumber") is None:
        if expected["study"] is not None:
            raise ValueError("overlay solver_plan lacks cflnumber")
        if plan.get("cfl_mode") != "same_cfl":
            raise ValueError("baseline solver_plan does not declare same_cfl")
    else:
        _same_float(plan.get("cflnumber"), expected["overlay_cfl"], "solver_plan.cflnumber")
    _same_float(plan.get("tout_s"), expected["overlay_tout"], "solver_plan.tout_s")
    command_xml = _resolved(_command_value(request.get("command"), "--generated-xml", "terminal overlay"), "command generated XML")
    if expected["study"] is None:
        if request.get("study") is not None:
            raise ValueError("baseline request unexpectedly declares an overlay study")
        if command_xml != base_path:
            raise ValueError("baseline command does not use base generated XML")
        overlay_path = base_path
    else:
        study = request.get("study")
        if not isinstance(study, dict):
            raise ValueError("overlay request lacks study metadata")
        if study.get("study_id") != expected["study"] or study.get("variable") != expected["variable"]:
            raise ValueError("overlay study label/variable does not match actual request metadata")
        if study.get("only_semantic_change") is not True:
            raise ValueError("overlay request does not declare one semantic change")
        _same_float(study.get("base_value"), expected["base_cfl"] if expected["variable"] == "CFLnumber" else expected["base_tout"], "study.base_value")
        _same_float(study.get("overlay_value"), expected["overlay_cfl"] if expected["variable"] == "CFLnumber" else expected["overlay_tout"], "study.overlay_value")
        overlay_path = _source_path(source, "overlay_generated_xml", "overlay generated XML")
        if command_xml != overlay_path:
            raise ValueError("overlay command does not use the declared overlay XML")
        overlay_item = source.get("overlay_generated_xml")
        overlay_bytes, overlay_record = _source_bytes(overlay_path, "overlay generated XML")
        if not isinstance(overlay_item, dict) or overlay_item.get("sha256") != overlay_record["sha256"]:
            raise ValueError("overlay generated XML SHA differs from request source metadata")
        if input_sha.get(str(overlay_path)) != overlay_record["sha256"]:
            raise ValueError("overlay generated XML SHA is absent or differs in request input_sha256")
        overlay_root = ET.fromstring(overlay_bytes)
        if _semantic_signature(base_root, expected["variable"]) != _semantic_signature(overlay_root, expected["variable"]):
            raise ValueError("overlay XML changes semantics beyond the registered one-variable value")
        overlay_cfl = _cfl_values(overlay_root, "overlay generated XML")
        overlay_tout = _finite(_parameter(overlay_root, "TimeOut", "overlay generated XML").attrib.get("value"), "overlay generated XML TimeOut")
    if any(abs(value - expected["base_cfl"]) > _FLOAT_TOLERANCE for value in base_cfl):
        raise ValueError("base generated XML cflnumber does not match source control")
    if expected["study"] is None:
        overlay_cfl = base_cfl
        overlay_tout = base_tout
    _same_float(base_cfl[0], expected["base_cfl"], "base XML cflnumber")
    _same_float(base_tout, expected["base_tout"], "base XML TimeOut")
    _same_float(overlay_cfl[0], expected["overlay_cfl"], "overlay XML cflnumber")
    _same_float(overlay_tout, expected["overlay_tout"], "overlay XML TimeOut")
    if overlay_variable != expected["variable"]:
        raise ValueError("CLI overlay variable does not match actual q study")
    if str(overlay_value) != expected["value"]:
        raise ValueError("CLI overlay value does not match the registered source value")
    command_tout = _finite(_command_value(request.get("command"), "--tout", "terminal overlay"), "command --tout")
    _same_float(command_tout, expected["overlay_tout"], "command --tout")
    return {
        "schema": SCHEMA,
        "status": "PASS_OVERLAY_CONTROL_BOUND_TO_TERMINAL_REQUEST_AND_XML",
        "request": request_record,
        "overlay": {"label": overlay_label, "variable": overlay_variable, "value": str(overlay_value)},
        "study_id": expected["study"],
        "base_xml": base_record,
        "overlay_xml": base_record if expected["study"] is None else overlay_record,
        "verified_values": {"base_cflnumber": base_cfl[0], "overlay_cflnumber": overlay_cfl[0], "base_tout_s": base_tout, "overlay_tout_s": overlay_tout, "command_tout_s": command_tout},
        "only_semantic_change": expected["study"] is not None,
        "payload_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({key: item for key, item in value.items() if key != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _fixture_self_test() -> None:
    xml_base = "<case><cflnumber value=\"0.05\"/><execution><parameter key=\"TimeOut\" value=\"0.01\"/><parameter key=\"StepAlgorithm\" value=\"2\"/></execution></case>"
    xml_overlay = "<case><cflnumber value=\"0.025\"/><execution><parameter key=\"TimeOut\" value=\"0.01\"/><parameter key=\"StepAlgorithm\" value=\"2\"/></execution></case>"
    with tempfile.TemporaryDirectory(prefix="f3-overlay-control-v3-") as root_text:
        root = Path(root_text); base = root / "base.xml"; overlay = root / "overlay.xml"; q = root / "q.json"
        base.write_text(xml_base, encoding="utf-8"); overlay.write_text(xml_overlay, encoding="utf-8")
        base_sha = _sha256_file(base, "fixture base"); overlay_sha = _sha256_file(overlay, "fixture overlay")
        q_value = {"schema": "ds02.stage2.external-solver-request.v5", "physical_case_id": PHYSICAL_CASE_ID, "command": ["materializer", "--generated-xml", str(overlay), "--tout", "0.01"], "input_sha256": {str(base): base_sha, str(overlay): overlay_sha}, "source_provenance": {"generated_xml": {"path": str(base), "sha256": base_sha}, "overlay_generated_xml": {"path": str(overlay), "sha256": overlay_sha}}, "study": {"study_id": "ROOT173", "variable": "CFLnumber", "base_value": 0.05, "overlay_value": 0.025, "only_semantic_change": True}, "solver_plan": {"cflnumber": 0.025, "tout_s": 0.01}}
        q.write_text(json.dumps(q_value, sort_keys=True), encoding="utf-8")
        validate_overlay_binding(q, "half_cfl", "CFLnumber", "0.025")
        for mutation in ("label", "value", "xml"):
            bad = json.loads(q.read_text())
            if mutation == "label":
                bad["study"]["study_id"] = "ROOT174"
            elif mutation == "value":
                bad["study"]["overlay_value"] = 0.05
            else:
                bad["solver_plan"]["cflnumber"] = 0.05
            bad_path = root / f"bad-{mutation}.json"; bad_path.write_text(json.dumps(bad, sort_keys=True), encoding="utf-8")
            try:
                validate_overlay_binding(bad_path, "half_cfl", "CFLnumber", "0.025")
            except ValueError:
                pass
            else:
                raise AssertionError(f"negative fixture {mutation} was accepted")


def self_test() -> dict[str, Any]:
    _fixture_self_test()
    return {"status": "PASS", "schema": SCHEMA, "negative_fixtures": ["label", "value", "solver_plan"], "payload_read": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--overlay-label")
    parser.add_argument("--overlay-variable")
    parser.add_argument("--overlay-value")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.request is None or args.overlay_label is None or args.overlay_variable is None or args.overlay_value is None:
        parser.error("validation requires --request, --overlay-label, --overlay-variable, and --overlay-value")
    print(json.dumps(validate_overlay_binding(args.request, args.overlay_label, args.overlay_variable, args.overlay_value), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
