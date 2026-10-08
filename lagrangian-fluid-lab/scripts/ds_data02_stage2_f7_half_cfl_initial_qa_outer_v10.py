#!/usr/bin/env python3
"""Parent-guarded outer entry for the F7 v8 initial typed QA.

The consumed v8 worker performs the two native frame-0 decodes and motion
staging.  This forward outer contract adds the XML/GenCase identity gate,
post-decode decoder-header/constant checks, and binds the literal v8 request,
worker and all ten input roles.  ``build-request`` and ``preflight`` read only
JSON/XML/stat metadata; in particular neither raw BI4 payload is hashed there.
``run --io-slot-approved`` is the only path that invokes the v8 worker and
therefore must be dispatched by the shared parent CPU guard.  Its fresh
``{attempt_root}/qa`` output is on the parent's Home filesystem.  It never
launches GenCase, a solver, CFD, GPU, or HDF5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import struct
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f7_half_cfl_initial_qa_v8.py"
V8_REQUEST = (SCRIPT_DIR.parent / "campaigns/ds-data-02/stage2/native-reconstruction/"
              "f7-half-cfl-v1/request-007-f7-v8-initial-qa/"
              "f7-s2-half-cfl-initial-typed-qa-request-v8-001.json")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DEFAULT_OUTPUT_TEMPLATE = "{attempt_root}/qa"
SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-outer-request.v10"
REPORT_SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-outer-report.v10"
V8_SCHEMA = "ds02.stage2.f7-half-cfl-initial-typed-qa-request.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HALF_EXPECTED = {
    "np": 70179, "nb": 29479, "nbf": 27495, "cflnumber": 0.1,
    "dp_m": 0.02, "motion_duration_s": 12.0,
    "blocks": {"fixed": {"begin": 0, "count": 27495, "mk": 10},
               "moving": {"begin": 27495, "count": 1984, "mk": 12},
               "fluid": {"begin": 29479, "count": 40700, "mk": 2}},
}
BASE_EXPECTED = dict(HALF_EXPECTED, cflnumber=0.2)
XML_CONSTANT_EXPECTED = {
    "Dp": 0.02,
    "Rhop0": 1000.0,
    "Gamma": 7.0,
    "B": 554965.71429,
    "MassBound": 0.008,
    "MassFluid": 0.008,
}
XML_CONSTANT_KEYS = tuple(XML_CONSTANT_EXPECTED)
BI4_ROLES = {"half_generated_bi4", "baseline_generated_bi4"}


class OuterQAError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OuterQAError(f"JSON object required: {path}")
    return value


def _snapshot(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns), "inode": int(stat.st_ino),
            "device": int(stat.st_dev), "mode": int(stat.st_mode)}


def _xml_semantics(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//execution/particles") or root.find(".//particles")
    if particles is None:
        raise OuterQAError(f"XML lacks particles block: {path}")
    constants = (root.find(".//execution/constants")
                 or root.find(".//constants")
                 or root.find(".//casedef/constantsdef"))
    definition = root.find(".//casedef/geometry/definition")
    cfl_node = constants.find("cflnumber") if constants is not None else None
    motion = root.find(".//casedef/motion/objreal/mvrotfile")
    blocks: dict[str, dict[str, int]] = {}
    for name in ("fixed", "moving", "fluid"):
        child = particles.find(name)
        if child is None:
            raise OuterQAError(f"XML lacks particle block {name}: {path}")
        mk_key = "mk" if child.get("mk") is not None else "mkbound" if child.get("mkbound") is not None else "mkfluid"
        blocks[name] = {"begin": int(child.get("begin")), "count": int(child.get("count")),
                        "mk": int(child.get(mk_key))}
    values: dict[str, float | None] = {}
    if constants is not None:
        for key, tag in (("Rhop0", "rhop0"), ("Gamma", "gamma"),
                         ("B", "b"), ("MassBound", "massbound"),
                         ("MassFluid", "massfluid")):
            node = constants.find(tag)
            if node is not None and node.get("value") is not None:
                values[key] = float(node.get("value"))
    dp_node = definition if definition is not None and definition.get("dp") is not None else (
        constants.find("dp") if constants is not None else None)
    if dp_node is not None:
        values["Dp"] = float(dp_node.get("dp") or dp_node.get("value"))
    result = {"np": int(particles.get("np")), "nb": int(particles.get("nb")),
              "nbf": int(particles.get("nbf")),
              "cflnumber": float(cfl_node.get("value")) if cfl_node is not None else None,
              "dp_m": float(definition.get("dp")) if definition is not None else None,
              "motion_duration_s": float(motion.get("duration")) if motion is not None else None,
              "blocks": blocks, "xml_constants": values}
    return result


def _assert_semantics(actual: Mapping[str, Any], expected: Mapping[str, Any], role: str) -> None:
    for key in ("np", "nb", "nbf"):
        if actual.get(key) != expected.get(key):
            raise OuterQAError(f"{role} XML {key} differs from frozen identity")
    for key in ("cflnumber", "dp_m", "motion_duration_s"):
        if actual.get(key) != expected.get(key):
            raise OuterQAError(f"{role} XML {key} differs from frozen control")
    if actual.get("blocks") != expected.get("blocks"):
        raise OuterQAError(f"{role} XML particle block identity differs")
    constants = actual.get("xml_constants")
    if not isinstance(constants, Mapping):
        raise OuterQAError(f"{role} XML constants are missing")
    for key, value in XML_CONSTANT_EXPECTED.items():
        observed = constants.get(key)
        if not isinstance(observed, (int, float)) or not math.isclose(
                float(observed), value, rel_tol=0.0, abs_tol=_float_storage_tolerance(value)):
            raise OuterQAError(f"{role} XML {key} differs from frozen scale")


def _float_storage_tolerance(value: float) -> float:
    """Allow only the representation error of a binary32/64 source value."""
    packed = struct.pack("<f", float(value))
    single = struct.unpack("<f", packed)[0]
    return max(abs(single - float(value)) + 2.0 * math.ulp(single),
               2.0 * math.ulp(float(value)), 1.0e-12)


def _input_bindings(inner: Mapping[str, Any], *, verify_content: bool = False) -> list[dict[str, Any]]:
    inputs = inner.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "half_generated_xml", "baseline_generated_xml", "half_gencase_receipt",
        "half_gencase_stdout", "F7_motion_control", "v5_same_cfl_receipt",
        "v5_same_cfl_RunPARTs", "pinned_native_bi4_decoder", "half_generated_bi4",
        "baseline_generated_bi4"}:
        raise OuterQAError("inner v8 ten-role closure differs")
    result = []
    for role in sorted(inputs):
        item = inputs[role]
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        if not path.is_file() or item.get("role") != role:
            raise OuterQAError(f"inner source is missing or role differs: {role}")
        stat = _snapshot(path)
        expected = {key: int(item[key]) for key in ("bytes", "mtime_ns", "ctime_ns", "inode", "device", "mode")}
        if stat != expected:
            raise OuterQAError(f"inner source stat differs: {role}")
        expected_sha = item.get("sha256")
        if role == "half_generated_bi4":
            if expected_sha is not None or item.get("content_scope") != "PARENT_GUARD_CONTENT_HASH_REQUIRED":
                raise OuterQAError("half BI4 must remain deferred to the parent worker")
        elif role == "baseline_generated_bi4":
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise OuterQAError("baseline BI4 must retain its known producer SHA")
        else:
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise OuterQAError(f"inner source SHA missing: {role}")
        # A metadata build/preflight may stat raw BI4 and carry its known
        # producer SHA, but it must never hash either payload.  The worker
        # invoked after the parent slot is approved performs those reads.
        if verify_content and role in BI4_ROLES:
            observed = sha256_file(path)
            if role == "baseline_generated_bi4" and observed != expected_sha:
                raise OuterQAError("baseline BI4 content SHA differs")
            expected_sha = observed
        elif verify_content and role not in BI4_ROLES:
            if sha256_file(path) != expected_sha:
                raise OuterQAError(f"inner source SHA differs: {role}")
        result.append({"role": role, "path": str(path), **stat,
                       "sha256": expected_sha,
                       "expected_sha256": item.get("sha256"),
                       "content_scope": ("metadata_only_stat_known_sha" if role in BI4_ROLES
                                         else item.get("content_scope")),
                       "content_verified": bool(verify_content and (role in BI4_ROLES or role not in BI4_ROLES))})
    return result


def _validate_inner(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    inner = load_json(path)
    if inner.get("schema") != V8_SCHEMA or inner.get("sha256") != canonical_sha(inner):
        raise OuterQAError("inner v8 request is noncanonical")
    if inner.get("status") != "PENDING_PARENT_IO_SLOT" or inner.get("launch_allowed") is not False:
        raise OuterQAError("inner v8 request is not pending development QA")
    execution = inner.get("execution", {})
    if (inner.get("qualification") != UNKNOWN
            or execution.get("model_invoked") is not False
            or execution.get("cfd_invoked") is not False):
        raise OuterQAError("inner v8 request has unsafe scope")
    half_xml = Path(str(inner["inputs"]["half_generated_xml"]["path"])).expanduser().resolve()
    baseline_xml = Path(str(inner["inputs"]["baseline_generated_xml"]["path"])).expanduser().resolve()
    half_sem = _xml_semantics(half_xml)
    base_sem = _xml_semantics(baseline_xml)
    _assert_semantics(half_sem, HALF_EXPECTED, "half")
    _assert_semantics(base_sem, BASE_EXPECTED, "baseline")
    for key in ("np", "nb", "nbf", "dp_m", "motion_duration_s", "blocks"):
        if half_sem[key] != base_sem[key]:
            raise OuterQAError(f"baseline/half initial identity differs in {key}")
    if half_sem["cflnumber"] == base_sem["cflnumber"]:
        raise OuterQAError("half/baseline CFL did not differ")
    return inner, {"half": half_sem, "baseline": base_sem}, _input_bindings(inner)


def build_request(*, inner_request: Path = V8_REQUEST, output: Path,
                  output_dir_template: str = DEFAULT_OUTPUT_TEMPLATE,
                  request_id: str = "f7-s2-half-cfl-initial-typed-qa-outer-v10-003") -> dict[str, Any]:
    inner_request = inner_request.expanduser().resolve()
    if not inner_request.is_file() or output.exists():
        raise OuterQAError("missing inner request or existing outer output")
    inner, xml_semantics, inputs = _validate_inner(inner_request)
    if output_dir_template != DEFAULT_OUTPUT_TEMPLATE:
        raise OuterQAError("v10 output must be the parent Home attempt-root/qa namespace")
    worker_stat = _snapshot(V8_SCRIPT)
    worker = {"role": "f7_initial_qa_worker_v8", "path": str(V8_SCRIPT.resolve()),
              **worker_stat, "sha256": sha256_file(V8_SCRIPT), "content_scope": "source_content"}
    outer_stat = _snapshot(Path(__file__))
    outer = {"role": "f7_initial_qa_outer_v10", "path": str(Path(__file__).resolve()),
             **outer_stat, "sha256": sha256_file(Path(__file__)), "content_scope": "source_content"}
    inner_binding = {"role": "f7_initial_qa_request_v8", "path": str(inner_request),
                     **_snapshot(inner_request), "sha256": sha256_file(inner_request),
                     "content_scope": "source_content"}
    value: dict[str, Any] = {
        "schema": SCHEMA, "request_id": request_id,
        "status": "READY_FOR_PARENT_CPU_GUARD", "role": "DEVELOPMENT", "family_id": "F7",
        "case_id": inner.get("case_id"), "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False, "launch_allowed": False,
        "inner_request": {"path": str(inner_request), "sha256": inner["sha256"],
                          "schema": inner["schema"], "immutable": True},
        "source_bindings": [inner_binding, outer, worker, *inputs],
        "xml_semantics": xml_semantics,
        "identity_gate": {
            "checks": ["decoder header CaseNp/Np/Nb/Nbf when present", "Np", "Nb", "Nbf", "dp", "CFL", "motion duration",
                        "fixed/moving/fluid begin/count/MK"],
            "half_expected": HALF_EXPECTED, "baseline_expected": BASE_EXPECTED,
            "xml_constant_expected": XML_CONSTANT_EXPECTED,
            "decoder_constant_keys": list(XML_CONSTANT_KEYS),
            "header_missing_field_policy": "report_not_present; do not claim that field was verified",
            "float_storage_tolerance": "binary32 round-trip plus two ulps only",
            "same_initial_identity_required": True,
            "decoded_arrays_remain_authoritative": True,
        },
        "execution": {
            "python": str(VENV_PYTHON),
            "command": [str(VENV_PYTHON), "-B", str(Path(__file__).resolve()), "run",
                        "--request", "<request>", "--io-slot-approved",
                        "--output-dir", "<attempt-root>/qa"],
            "inner_command": [str(VENV_PYTHON), "-B", str(V8_SCRIPT), "run",
                              "--request", str(inner_request), "--io-slot-approved",
                              "--output-dir", "<runtime-output-dir>"],
            "output_dir_template": output_dir_template,
            "output_filesystem": "home",
            "requires_shared_four_guard": True,
            "hdf5": False, "solver": False, "cfd": False, "gpu": False,
            "model_invoked": False, "original_path_fallback": "FORBIDDEN",
            "parent_supervised": True,
        },
        "resource_request": {
            "cpu_threads": 1, "max_wall_seconds": 900,
            "max_rss_bytes": 512 * 1024**2, "new_storage_budget_bytes": 512 * 1024**2,
            "source_read_scope": "two frame-0 BI4 files and decoder scratch; no H5/solver",
            "parent_guard_required": True, "qualification": "DEVELOPMENT_UNKNOWN",
        },
        "motion_stage": {
            "source": inner["inputs"]["F7_motion_control"]["path"],
            "source_sha256": inner["inputs"]["F7_motion_control"]["sha256"],
            "target_relative": "solver_input/motion_obstacle_quintic.dat",
            "copy_target_hash_required": True, "solver_launch_allowed": False,
        },
        "parent_accounting": {
            "same_parent_ledger": True, "output_filesystem": "home",
            "attempt_root_placeholder": "{attempt_root}",
            "output_dir_template": output_dir_template,
            "output_must_be_fresh_child": True,
            "external_output_namespace": False,
            "static_source_hashes_are_parent_guarded": True,
            "half_bi4_content_sha_deferred_to_worker": True,
        },
        "limitations": [
            "This outer request adds XML and post-decode header/constant identity checks but does not replace the v8 decoded-array comparison.",
            "No GenCase, solver, CFD, GPU, or HDF5 execution is performed by build/preflight.",
            "Both BI4 payloads are stat-only during build/preflight; their content is read only after the parent-approved CPU worker starts.",
            "The baseline BI4 producer SHA is a known binding, while the half BI4 content hash remains unknown until the worker reads it.",
            "The concrete output directory must be supplied by the parent under its Home attempt root; an NVMe or /var/tmp output is rejected.",
            "The result remains DEVELOPMENT/UNKNOWN and requires a new solver request after QA and motion staging.",
        ],
    }
    value["sha256"] = canonical_sha(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return value


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _validate_home_output(request: Mapping[str, Any], output_dir: Path) -> Path:
    """Validate the concrete Home attempt-root/qa overlay supplied by the parent."""
    output_dir = output_dir.expanduser()
    if output_dir.is_symlink():
        raise OuterQAError("concrete Home QA output may not be a symlink")
    output_dir = output_dir.resolve()
    accounting = request.get("parent_accounting", {})
    execution = request.get("execution", {})
    if accounting.get("output_filesystem") != "home" or execution.get("output_filesystem") != "home":
        raise OuterQAError("v10 requires the parent Home output filesystem")
    if execution.get("output_dir_template") != DEFAULT_OUTPUT_TEMPLATE:
        raise OuterQAError("v10 output template differs from the frozen attempt-root/qa contract")
    if output_dir.name != "qa" or output_dir.parent == output_dir:
        raise OuterQAError("concrete output must be the qa child of a parent attempt root")
    if str(output_dir).startswith("/var/tmp/") or str(output_dir).startswith("/tmp/"):
        raise OuterQAError("v10 QA output may not use an external temporary filesystem")
    if not output_dir.parent.is_dir() or output_dir.parent.is_symlink():
        raise OuterQAError("parent attempt root must already be a real directory")
    if _path_exists(output_dir):
        raise OuterQAError(f"refusing existing Home QA output namespace: {output_dir}")
    return output_dir


def _decoder_scalar(element: ET.Element) -> Any:
    value = element.get("v")
    if value is None:
        return None
    tag = element.tag.rsplit("}", 1)[-1].lower()
    if tag in {"bool", "boolean"}:
        return value.lower() in {"1", "true", "yes"}
    if tag in {"int", "uint", "int32", "uint32", "int64", "uint64", "long"}:
        try:
            return int(value)
        except ValueError:
            return value
    if tag in {"float", "double", "real"}:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _decoder_named_values(node: ET.Element | None) -> dict[str, Any]:
    if node is None:
        return {}
    return {item.get("name"): _decoder_scalar(item)
            for item in node if item.tag.rsplit("}", 1)[-1] != "item" and item.get("name")}


def _decoder_header(output_dir: Path, tag: str) -> dict[str, Any]:
    xml_path = output_dir / "decoder-scratch" / tag / "frame_0000.xml"
    if not xml_path.is_file():
        raise OuterQAError(f"{tag} decoder header is missing: {xml_path}")
    root = ET.parse(xml_path).getroot()
    outer = root.find("item")
    particle = root.find(".//item/item")
    return {"path": str(xml_path), "sha256": sha256_file(xml_path),
            "outer": _decoder_named_values(outer),
            "particle": _decoder_named_values(particle)}


def _header_value(header: Mapping[str, Any], key: str) -> tuple[Any, str | None]:
    for scope in ("outer", "particle"):
        values = header.get(scope, {})
        if isinstance(values, Mapping) and key in values:
            return values[key], scope
    return None, None


def _header_identity_gate(output_dir: Path, semantics: Mapping[str, Any]) -> dict[str, Any]:
    headers = {tag: _decoder_header(output_dir, tag) for tag in ("half", "baseline")}
    expected_fields = {"CaseNp": "np", "Np": "np", "Nb": "nb", "Nbf": "nbf"}
    fields: dict[str, Any] = {}
    for field, semantic_key in expected_fields.items():
        values = {tag: _header_value(header, field) for tag, header in headers.items()}
        present = {tag: value for tag, (value, scope) in values.items() if scope is not None}
        if not present:
            fields[field] = {"status": "not_present", "scope": None,
                             "expected": {tag: semantics[tag][semantic_key] for tag in headers}}
            continue
        if len(present) != 2:
            raise OuterQAError(f"decoder header {field} is present for only one initial frame")
        evidence: dict[str, Any] = {}
        for tag, (value, scope) in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
                raise OuterQAError(f"decoder header {tag} {field} is not an integer")
            expected = int(semantics[tag][semantic_key])
            if int(value) != expected:
                raise OuterQAError(f"decoder header {tag} {field} differs from XML identity")
            evidence[tag] = {"value": int(value), "scope": scope, "expected": expected}
        fields[field] = {"status": "verified", "evidence": evidence}

    constants: dict[str, Any] = {}
    for field in XML_CONSTANT_KEYS:
        values = {tag: _header_value(header, field) for tag, header in headers.items()}
        present = {tag: value for tag, (value, scope) in values.items() if scope is not None}
        if not present:
            constants[field] = {"status": "not_present"}
            continue
        if len(present) != 2:
            raise OuterQAError(f"decoder constant {field} is present for only one initial frame")
        evidence: dict[str, Any] = {}
        for tag, (value, scope) in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise OuterQAError(f"decoder {tag} constant {field} is not finite numeric")
            expected = float(semantics[tag].get("xml_constants", {}).get(field, XML_CONSTANT_EXPECTED[field]))
            tolerance = _float_storage_tolerance(expected)
            if not math.isclose(float(value), expected, rel_tol=0.0, abs_tol=tolerance):
                raise OuterQAError(f"decoder {tag} constant {field} differs from XML scale")
            evidence[tag] = {"value": float(value), "scope": scope,
                             "xml_value": expected, "abs_tolerance": tolerance}
        constants[field] = {"status": "verified", "evidence": evidence}
    return {"headers": headers, "identity_fields": fields, "decoder_constants": constants,
            "only_fields_present_are_gated": True}


def preflight(request_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != SCHEMA or request.get("sha256") != canonical_sha(request):
        raise OuterQAError("outer request is noncanonical")
    inner_path = Path(str(request["inner_request"]["path"])).expanduser().resolve()
    inner, semantics, inputs = _validate_inner(inner_path)
    if request["inner_request"].get("sha256") != inner.get("sha256"):
        raise OuterQAError("outer inner request SHA differs")
    if request.get("xml_semantics") != semantics:
        raise OuterQAError("outer XML semantic snapshot differs")
    for item in request.get("source_bindings", []):
        path = Path(str(item["path"])).expanduser().resolve()
        if not path.is_file() or _snapshot(path) != {key: int(item[key]) for key in ("bytes", "mtime_ns", "ctime_ns", "inode", "device", "mode")}:
            raise OuterQAError(f"outer source stat differs: {path}")
        # Raw BI4 payloads are intentionally metadata-only at this stage.  A
        # known baseline SHA is carried as an immutable producer claim and is
        # checked by the approved worker; preflight must not read the payload.
        if item.get("role") in BI4_ROLES:
            if item.get("content_scope") != "metadata_only_stat_known_sha":
                raise OuterQAError(f"BI4 binding is not metadata-only: {path}")
            if item.get("role") == "baseline_generated_bi4" and not isinstance(item.get("sha256"), str):
                raise OuterQAError("baseline BI4 known SHA is missing")
        elif item.get("sha256") != sha256_file(path):
            raise OuterQAError(f"outer source SHA differs: {path}")
    return {"status": "READY_FOR_PARENT_CPU_SLOT", "inner_sha256": inner["sha256"],
            "source_count": len(request.get("source_bindings", [])), "xml_semantics": semantics,
            "output_dir_template": request["execution"]["output_dir_template"],
            "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
            "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def run(request_path: Path, *, io_slot_approved: bool,
        output_dir: Path | None = None) -> dict[str, Any]:
    request = load_json(request_path)
    checked = preflight(request_path)
    if not io_slot_approved:
        return checked
    if output_dir is None:
        raise OuterQAError("--output-dir is required after the parent I/O slot is approved")
    output_dir = _validate_home_output(request, output_dir)
    command = [str(item).replace("<request>", str(request["inner_request"]["path"]))
               .replace("<runtime-output-dir>", str(output_dir))
               for item in request["execution"]["inner_command"]]
    # The v8 command already contains the output directory; this explicit
    # subprocess boundary keeps import caches and source paths closed.
    started = time.monotonic()
    completed = subprocess.run(command, cwd=str(SCRIPT_DIR.parents[1]),
                                capture_output=True, text=True,
                                timeout=float(request["resource_request"]["max_wall_seconds"]))
    status = "PASS_INITIAL_TYPED_QA_DEVELOPMENT_UNKNOWN" if completed.returncode == 0 else "FAILED_INITIAL_TYPED_QA"
    identity_gate: dict[str, Any] | None = None
    identity_error: str | None = None
    if completed.returncode == 0:
        try:
            identity_gate = _header_identity_gate(output_dir, checked["xml_semantics"])
        except OuterQAError as error:
            status = "FAILED_DECODER_IDENTITY_GATE"
            identity_error = str(error)
    report = {"schema": REPORT_SCHEMA,
              "status": status,
              "request_sha256": request.get("sha256"), "inner_request_sha256": checked["inner_sha256"],
              "returncode": completed.returncode, "elapsed_seconds": time.monotonic() - started,
              "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-4000:],
              "output_dir": str(output_dir), "output_filesystem": "home",
              "parent_guard": request["parent_accounting"],
              "decoder_identity_gate": identity_gate,
              "decoder_identity_error": identity_error,
              "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    report["sha256"] = canonical_sha(report)
    path = output_dir / "f7-s2-half-cfl-initial-typed-qa-v10-outer-report.json"
    if path.exists():
        raise OuterQAError("refusing existing outer report")
    if not output_dir.is_dir():
        raise OuterQAError("inner worker did not create its output namespace")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--inner-request", type=Path, default=V8_REQUEST)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--output-dir-template", default=DEFAULT_OUTPUT_TEMPLATE)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(inner_request=args.inner_request, output=args.output,
                                  output_dir_template=args.output_dir_template)
            result = {"status": value["status"], "sha256": value["sha256"],
                      "source_count": len(value["source_bindings"])}
        elif args.command == "preflight":
            result = preflight(args.request)
        else:
            result = run(args.request, io_slot_approved=args.io_slot_approved,
                         output_dir=args.output_dir)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if not str(result.get("status", "")).startswith("FAILED") else 2
    except (OuterQAError, OSError, ValueError, TypeError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
