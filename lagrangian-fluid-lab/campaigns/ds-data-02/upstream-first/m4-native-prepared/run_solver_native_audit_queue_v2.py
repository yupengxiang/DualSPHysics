#!/usr/bin/env python3
"""Root-reviewable sequential M4 solver and native-audit queue (v2).

The queue has two modes.  The default mode writes one immutable plan below
this directory and performs no launch.  ``--launch`` is root controlled and
requires an explicit confirmation.  It then executes exactly one case in the
following order::

    existing solver request/grant
      -> charged native-integrity preparation
      -> native-integrity audit
      -> charged native-frame preparation
      -> full 241-frame native identity/finite audit

All execution goes through the batch-2 runtime.  This file never edits the
shared ledger and never leases a GPU.  The frozen
``prepare_m4_additional_audits.py`` worker remains the only producer of the
native audit candidates; its output is constrained to the existing
``m4-additional-definitions/prepared`` directory.

This v2 handoff accepts the actual frozen-worker candidate shape.  The worker
intentionally omits flat ``time_max_s``, ``time_out_s`` and ``dp_m`` fields
from native-audit candidates.  The queue derives that recipe from the actual
generated XML, the immutable child manifest, and the immutable solver request;
optional candidate copies are checked when present.  A completed v1
preparation stage is reused byte-for-byte and is never regenerated.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping


SCRIPT = Path(__file__).resolve()
LEGACY_SCRIPT = SCRIPT.with_name("run_solver_native_audit_queue.py")
UPSTREAM = SCRIPT.parents[1]
ROOT = UPSTREAM.parents[3]
PREPARED_ROOT = SCRIPT.parent
ADDITIONAL = UPSTREAM / "m4-additional-definitions"
HELPER = ADDITIONAL / "prepare_m4_additional_audits.py"
HELPER_OUTPUT = ADDITIONAL / "prepared"
RUNS = Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1")
REQUESTS = UPSTREAM / "requests"
GRANTS = UPSTREAM / "batch2-runtime" / "grants"
ADMISSION = UPSTREAM / "batch2-runtime" / "root-batch-2-admission.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_V2 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V6_BATCH2 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6_batch2.py"
M2 = ADDITIONAL.parent / "m2" / "upstream_conversion"
M3 = UPSTREAM / "m3"
BI4_DECODER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/"
    "l1-resume/artifacts/bi4_dump"
)
DS_CONFIG = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
)
PARTVTK = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
)

EXPECTED_FRAMES = 241
SOLVER_STORAGE = 9 * 1024**3
PREPARATION_STORAGE = 64 * 1024**2
PREPARATION_TEMP = 64 * 1024**2
NATIVE_INTEGRITY_STORAGE = 64 * 1024**2
NATIVE_INTEGRITY_TEMP = 16 * 1024**2
NATIVE_FRAME_STORAGE = 640 * 1024**2
NATIVE_FRAME_TEMP = 512 * 1024**2
NATIVE_INTEGRITY_MAX_WALL = 300
NATIVE_FRAME_MAX_WALL = 3600
TIME_MAX_S = 6.0
TIME_OUT_S = 0.025
DP_M = 0.01
CONFIRMATION = "ROOT_APPROVED_M4_NATIVE_SOLVER_AUDIT"
PLAN_SCHEMA = "ds-data-02.m4.native-solver-audit-queue-plan.v3"
REQUEST_SCHEMA = "ds-data-02.runner.request.v1"
GRANT_SCHEMA = "ds02.upstream-first.batch-request-grant.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
FRAME_RE = re.compile(r"^Part_\d+\.bi4$", re.ASCII)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)

CASES = {
    "UF_F1_MDBC_DP010_H052": {"suffix": "H052", "depth_m": 0.52},
    "UF_F1_MDBC_DP010_H058": {"suffix": "H058", "depth_m": 0.58},
}


class QueueError(RuntimeError):
    """Raised for a failed gate or an unsafe launch/promotion."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str, *, required: bool = True) -> Path | None:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        if required:
            raise QueueError(f"{label} is not a regular non-symlink file: {path}")
        return None
    return path.resolve()


def _directory(path: Path, label: str) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise QueueError(f"{label} is not a regular non-symlink directory: {path}")
    return path.resolve()


def _load(path: Path, label: str) -> dict[str, Any]:
    _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QueueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QueueError(f"{label} must be a JSON object: {path}")
    return value


def _binding(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)  # type: ignore[assignment]
    assert path is not None
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    try:
        path.relative_to(PREPARED_ROOT.resolve())
    except ValueError as exc:
        raise QueueError(f"launcher-owned immutable output escaped its subtree: {path}") from exc
    if path.exists() or path.is_symlink():
        raise QueueError(f"refusing to overwrite immutable launcher output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_json_bytes(value).decode("utf-8"))


def _case_id(value: str) -> str:
    value = value.strip()
    if value in CASES:
        return value
    suffix = value.upper()
    if suffix in {"H052", "H058"}:
        return f"UF_F1_MDBC_DP010_{suffix}"
    raise QueueError(f"unsupported M4 native queue case: {value}")


def _paths(case: str) -> dict[str, Path]:
    case = _case_id(case)
    run = RUNS / case
    return {
        "run": run,
        "gencase_root": run / "gencase-001",
        "gencase_receipt": run / "gencase-001" / "execution-receipt.json",
        "generated_xml": run / "gencase-001" / f"{case}.xml",
        "generated_bi4": run / "gencase-001" / f"{case}.bi4",
        "solver_root": run / "solver-001",
        "solver_receipt": run / "solver-001" / "execution-receipt.json",
        "solver_data": run / "solver-001" / "data",
        "integrity_root": run / "native-integrity-001",
        "integrity_receipt": run / "native-integrity-001" / "execution-receipt.json",
        "integrity_report": run / "native-integrity-001" / "integrity.json",
        "frame_root": run / "native-frame-scan-001",
        "frame_receipt": run / "native-frame-scan-001" / "execution-receipt.json",
        "frame_report": run / "native-frame-scan-001" / "frame-identity-scan.json",
        "definition": ADDITIONAL / f"{case}_Def.xml",
        "case_manifest": ADDITIONAL / "manifests" / f"{case}.json",
        "solver_request": REQUESTS / f"{case}-solver-001.json",
        "solver_grant": GRANTS / f"{case}-solver-001.json",
        # The original v1/v2 handoffs are immutable; this is a fresh v3
        # review artifact for the frozen-worker candidate shape.
        "plan": PREPARED_ROOT / "plans" / f"{case}-solver-native-audit.plan-v3.json",
    }


def _attempt_paths(case: str, attempt: str) -> tuple[Path, Path, Path]:
    p = _paths(case)
    root = p["run"] / attempt
    return root, root / "execution-receipt.json", root / "stdout.log"


def _receipt_state(path: Path, case: str, attempt: str) -> tuple[str, dict[str, Any] | None]:
    """Return absent/completed/running/failed/invalid without changing anything."""
    if not path.exists() and not path.is_symlink():
        return "absent", None
    if path.is_symlink() or not path.is_file():
        return "invalid", None
    try:
        receipt = _load(path, f"{attempt} execution receipt")
    except QueueError:
        return "invalid", None
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return "invalid", receipt
    request = receipt.get("request")
    request_case = receipt.get("case_id")
    request_attempt = receipt.get("attempt_id")
    if isinstance(request, Mapping):
        request_case = request_case or request.get("case_id")
        request_attempt = request_attempt or request.get("attempt_id")
    if request_case != case or request_attempt != attempt:
        return "invalid", receipt
    status = receipt.get("status")
    if status == "completed" and receipt.get("returncode") == 0:
        return "completed", receipt
    if status == "running":
        return "running", receipt
    if status == "failed":
        return "failed", receipt
    return "invalid", receipt


def _require_completed_receipt(path: Path, case: str, attempt: str) -> dict[str, Any]:
    state, receipt = _receipt_state(path, case, attempt)
    if state != "completed" or receipt is None:
        raise QueueError(f"{case}/{attempt} is {state}; completed receipt required: {path}")
    return receipt


def _assert_receipt_request_binding(
    receipt: Mapping[str, Any], request_path: Path, case: str, attempt: str
) -> None:
    """Require a terminal receipt to name the exact immutable request bytes.

    The runner records ``request_sha256`` in every terminal execution receipt.
    Treating a missing value as acceptable would let an old or hand-written
    receipt pass the queue's postcondition, so this check deliberately uses an
    exact equality rather than an optional comparison.
    """

    request = _regular(request_path, f"immutable request for {case}/{attempt}")
    expected = _sha256(request)
    actual = receipt.get("request_sha256")
    if not isinstance(actual, str) or not SHA256_RE.fullmatch(actual) or actual != expected:
        raise QueueError(
            f"{case}/{attempt} receipt request_sha256 does not equal the immutable request hash"
        )
    nested = receipt.get("request")
    if isinstance(nested, Mapping):
        if nested.get("case_id") not in (None, case) or nested.get("attempt_id") not in (None, attempt):
            raise QueueError(f"{case}/{attempt} receipt request identity is not case-bound")


def _assert_runner_report_binding(
    case: str, attempt: str, report_path: Path, receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind an auditor report to its execution receipt and stdout.

    The frame auditor writes the full report to stdout.  The integrity auditor
    intentionally writes a compact ``{path,status}`` summary because its
    report can be large.  Both forms are checked against the runner's
    ``stdout_sha256``; neither check reads or hashes native frame payloads.
    """

    p = _paths(case)
    attempt_root = p["integrity_root"] if attempt == "native-integrity-001" else p["frame_root"]
    stdout_path = _regular(attempt_root / "stdout.log", f"{case}/{attempt} stdout")
    report = _regular(report_path, f"{case}/{attempt} report")
    stdout_hash = _sha256(stdout_path)
    if receipt.get("stdout_sha256") != stdout_hash:
        raise QueueError(f"{case}/{attempt} execution receipt stdout_sha256 is stale")
    try:
        stdout_payload = json.loads(stdout_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QueueError(f"{case}/{attempt} stdout is not JSON report evidence") from exc
    report_payload = _load(report, f"{case}/{attempt} report")
    if attempt == "native-frame-scan-001":
        if stdout_payload != report_payload:
            raise QueueError("native-frame report is not the full stdout report bound by its receipt")
    else:
        if not isinstance(stdout_payload, Mapping):
            raise QueueError("native-integrity stdout summary is not an object")
        if stdout_payload.get("path") != str(report.resolve()) or stdout_payload.get("status") != report_payload.get("status"):
            raise QueueError("native-integrity stdout summary is not bound to its report")
    if receipt.get("output_root") != str(attempt_root.resolve()):
        raise QueueError(f"{case}/{attempt} receipt output_root differs from its case attempt")
    return {
        "execution_receipt_sha256": _sha256(p["integrity_receipt"] if attempt == "native-integrity-001" else p["frame_receipt"]),
        "stdout_sha256": stdout_hash,
        "report_sha256": _sha256(report),
    }


def _all_solver_files(case: str) -> list[Path]:
    root = _directory(_paths(case)["solver_root"], "completed solver attempt")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise QueueError(f"completed solver attempt contains a symbolic link: {path}")
        if path.is_file():
            files.append(_regular(path, "completed solver regular file"))  # type: ignore[arg-type]
    required = {
        root / "execution-receipt.json",
        root / "Run.out",
        root / "RunPARTs.csv",
        root / "data" / "PartInfo.ibi4",
        root / "data" / "PartOut_000.obi4",
    }
    missing = sorted(str(path) for path in required if path not in files)
    if missing:
        raise QueueError("completed solver attempt lacks required regular files: " + ", ".join(missing))
    return files


def _solver_request(case: str) -> dict[str, Any]:
    p = _paths(case)
    request = _load(p["solver_request"], "root solver request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise QueueError("root solver request schema is not ds-data-02.runner.request.v1")
    if (request.get("family_id"), request.get("case_id"), request.get("attempt_id")) != ("F1", case, "solver-001"):
        raise QueueError("root solver request identity differs from the requested case")
    if request.get("kind") != "qualification" or request.get("output_storage") != "upstream_nas":
        raise QueueError("root solver request is not the qualified NAS solver request")
    if request.get("estimated_storage_bytes") != SOLVER_STORAGE:
        raise QueueError("root solver request does not retain the exact 9 GiB reservation")
    if request.get("expected_frames") != EXPECTED_FRAMES:
        raise QueueError("root solver request does not retain the 241-frame contract")
    if float(request.get("time_max_s", -1)) != TIME_MAX_S or float(request.get("time_out_s", -1)) != TIME_OUT_S:
        raise QueueError("root solver request does not retain TimeMax=6 and TimeOut=.025")
    if float(request.get("dp_m", -1)) != DP_M:
        raise QueueError("root solver request does not retain dp=.01")
    command = request.get("command")
    if not isinstance(command, list) or not command or "-gpu" not in command or "-cpu" in command:
        raise QueueError("root solver request is not the approved GPU solver command")
    if request.get("gencase_receipt_sha256") is None or not isinstance(request.get("actual_gencase_binding"), Mapping):
        raise QueueError("root solver request lacks its actual GenCase/cohort binding")
    return request


def _number(value: Any, label: str) -> float:
    """Parse one finite recipe number without accepting booleans or NaN."""

    if isinstance(value, bool):
        raise QueueError(f"{label} is not numeric: {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QueueError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise QueueError(f"{label} is not finite: {value!r}")
    return number


def _recipe_from_xml(case: str) -> dict[str, Any]:
    """Derive the child recipe from the actual generated XML metadata."""

    path = _regular(_paths(case)["generated_xml"], "actual generated XML")
    assert path is not None
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise QueueError(f"actual generated XML is not parseable: {path}") from exc
    definition = root.find(".//definition")
    if definition is None or definition.get("dp") is None:
        raise QueueError("actual generated XML lacks definition@dp")
    parameters = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }
    for key in ("TimeMax", "TimeOut"):
        if parameters.get(key) is None:
            raise QueueError(f"actual generated XML lacks execution parameter {key}")
    return {
        "dp_m": _number(definition.get("dp"), "actual XML definition dp"),
        "time_max_s": _number(parameters["TimeMax"], "actual XML TimeMax"),
        "time_out_s": _number(parameters["TimeOut"], "actual XML TimeOut"),
        "source": str(path.resolve()),
    }


def _recipe_from_manifest(case: str) -> dict[str, Any]:
    """Read the immutable child-manifest recipe contract."""

    path = _regular(_paths(case)["case_manifest"], "immutable child case manifest")
    assert path is not None
    manifest = _load(path, "immutable child case manifest")
    if manifest.get("case_id") != case:
        raise QueueError("immutable child case manifest is not case-bound")
    recipe = manifest.get("numerical_output_recipe")
    if not isinstance(recipe, Mapping):
        raise QueueError("immutable child case manifest lacks numerical_output_recipe")
    expected_frames = recipe.get("expected_frames")
    if type(expected_frames) is not int or expected_frames <= 0:
        raise QueueError("immutable child case manifest has no positive expected frame count")
    return {
        "dp_m": _number(recipe.get("dp_m"), "case manifest dp_m"),
        "time_max_s": _number(recipe.get("time_max_s"), "case manifest time_max_s"),
        "time_out_s": _number(recipe.get("candidate_time_out_s"), "case manifest candidate_time_out_s"),
        "expected_frames": expected_frames,
        "source_time_out_s": _number(recipe.get("source_time_out_s"), "case manifest source_time_out_s"),
        "source": str(path.resolve()),
    }


def _recipe_from_solver_request(case: str) -> dict[str, Any]:
    """Read the already-bound immutable root solver request recipe."""

    request = _solver_request(case)
    frames = request.get("expected_frames")
    if type(frames) is not int or frames <= 0:
        raise QueueError("immutable solver request has no positive expected frame count")
    return {
        "dp_m": _number(request.get("dp_m"), "immutable solver request dp_m"),
        "time_max_s": _number(request.get("time_max_s"), "immutable solver request time_max_s"),
        "time_out_s": _number(request.get("time_out_s"), "immutable solver request time_out_s"),
        "expected_frames": frames,
        "source": str(_paths(case)["solver_request"].resolve()),
    }


def _assert_recipe_value(actual: Any, expected: float, label: str) -> None:
    value = _number(actual, label)
    if not math.isclose(value, expected, abs_tol=1e-9, rel_tol=0.0):
        raise QueueError(f"{label} differs from the bound recipe: {value!r} != {expected!r}")


def _assert_recipe_consensus(case: str, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Close recipe provenance across XML, child manifest, and solver request.

    Native candidates from the frozen worker do not carry flat recipe fields.
    If a future worker adds any of the optional fields, they are checked rather
    than required.  The recursive check covers nested metadata without making
    a scientific claim from an unbound candidate copy.
    """

    xml_recipe = _recipe_from_xml(case)
    manifest_recipe = _recipe_from_manifest(case)
    solver_recipe = _recipe_from_solver_request(case)
    for field in ("dp_m", "time_max_s", "time_out_s"):
        expected = xml_recipe[field]
        for label, source in (("case manifest", manifest_recipe), ("solver request", solver_recipe)):
            if not math.isclose(source[field], expected, abs_tol=1e-9, rel_tol=0.0):
                raise QueueError(f"{label} {field} disagrees with actual XML recipe")
    if manifest_recipe["expected_frames"] != solver_recipe["expected_frames"]:
        raise QueueError("case manifest and solver request expected frame counts disagree")
    if manifest_recipe["expected_frames"] != EXPECTED_FRAMES:
        raise QueueError("bound recipe does not retain the 241-frame contract")

    optional_numeric = {
        "dp_m": xml_recipe["dp_m"],
        "time_max_s": xml_recipe["time_max_s"],
        "time_out_s": xml_recipe["time_out_s"],
        "candidate_time_out_s": xml_recipe["time_out_s"],
        "expected_frames": float(manifest_recipe["expected_frames"]),
        "estimated_saved_frames": float(manifest_recipe["expected_frames"]),
        "minimum_time_end_s": xml_recipe["time_max_s"],
    }
    optional_source_time = manifest_recipe["source_time_out_s"]

    def check_optional(value: Any, location: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in optional_numeric:
                    expected = optional_numeric[key]
                    if key in {"expected_frames", "estimated_saved_frames"}:
                        if type(nested) is not int or nested != int(expected):
                            raise QueueError(f"optional candidate recipe field {location}.{key} disagrees")
                    else:
                        _assert_recipe_value(nested, expected, f"optional candidate recipe field {location}.{key}")
                elif key == "source_time_out_s":
                    _assert_recipe_value(nested, optional_source_time, f"optional candidate recipe field {location}.{key}")
                check_optional(nested, f"{location}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                check_optional(nested, f"{location}[{index}]")

    check_optional(candidate, "candidate")
    return {
        "dp_m": xml_recipe["dp_m"],
        "time_max_s": xml_recipe["time_max_s"],
        "time_out_s": xml_recipe["time_out_s"],
        "expected_frames": manifest_recipe["expected_frames"],
        "source_time_out_s": manifest_recipe["source_time_out_s"],
        "sources": {
            "actual_generated_xml": xml_recipe["source"],
            "case_manifest": manifest_recipe["source"],
            "solver_request": solver_recipe["source"],
        },
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _payload_hash(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("payload_sha256", None)
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def _validate_grant(grant_path: Path, request_path: Path, case: str, attempt: str) -> dict[str, Any]:
    grant = _load(grant_path, "root request grant")
    if grant.get("schema") != GRANT_SCHEMA or grant.get("status") != "granted" or grant.get("issuer") != "root" or grant.get("immutable") is not True:
        raise QueueError(f"root grant is not immutable/granted: {grant_path}")
    if grant.get("request_path") != str(request_path.resolve()):
        raise QueueError(f"root grant request path mismatch: {grant_path}")
    if grant.get("request_sha256") != _sha256(request_path):
        raise QueueError(f"root grant request hash mismatch: {grant_path}")
    expected_attempt = f"F1/{case}/{attempt}"
    if grant.get("attempt_id") != expected_attempt:
        raise QueueError(f"root grant attempt mismatch: {grant_path}")
    if grant.get("payload_sha256") != _payload_hash(grant):
        raise QueueError(f"root grant payload hash mismatch: {grant_path}")
    return grant


def _validate_solver_grant(case: str, request: Mapping[str, Any]) -> dict[str, Any]:
    p = _paths(case)
    _regular(p["solver_grant"], "root solver grant")
    return _validate_grant(p["solver_grant"], p["solver_request"], case, "solver-001")


def _receipt_binding(path: Path, case: str, attempt: str) -> dict[str, Any]:
    receipt = _require_completed_receipt(path, case, attempt)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": _sha256(path), "status": receipt.get("status")}


def _static_audit_sources(case: str, mode: str) -> list[Path]:
    """The complete small source contract the frozen helper/auditor consumes."""
    suffix = "native-integrity-001" if mode == "exclusions" else "native-frame-scan-001"
    frozen_manifest = M2 / "manifests" / f"UF_F1_MDBC_DAMBREAK3D-{suffix}.json"
    frozen_request = M2 / "requests" / f"UF_F1_MDBC_DAMBREAK3D-{suffix}.json"
    paths = [
        UPSTREAM / "M4_PHYSICAL_DESIGN.json",
        UPSTREAM / "m4" / "m4-condition-template.json",
        ADDITIONAL / "definition-verification.json",
        ADDITIONAL / "semantic-diff.json",
        ADDITIONAL / "manifests" / f"{case}.json",
        ADDITIONAL / "requests" / f"{case}-solver.template.json",
        ADDITIONAL / "requests" / f"{case}-gencase.template.json",
        M3 / "fine-mother-acceptance-decision.json",
        M3 / "fine-mother-declared-use-acceptance.json",
        M3 / "fine-mother-evidence-index.json",
        UPSTREAM / "m3" / "derivative-design.json",
        UPSTREAM / "m1" / "observation-contract.md",
        frozen_manifest,
        frozen_request,
        M2 / "native-integrity-manifest.schema.json",
        M2 / "native-frame-scan-manifest.schema.json",
        M2 / "native-lifecycle-records.schema.json",
        M2 / "native_integrity_audit.py",
        M2 / "native_frame_identity_scan.py",
        RUNTIME_V2,
        RUNTIME_V6,
        RUNTIME_V6_BATCH2,
        HELPER,
        LEGACY_SCRIPT,
        SCRIPT,
        DS_CONFIG,
        PARTVTK,
    ]
    if mode == "frames":
        paths.extend([BI4_DECODER, ROOT / "lagrangian-fluid-lab/scripts/ds_data02_f5_bi4.py", ROOT / "lagrangian-fluid-lab/scripts/__init__.py"])
    return list(dict.fromkeys(paths))


def _source_inputs_for_prep(case: str, mode: str) -> list[Path]:
    p = _paths(case)
    _require_completed_receipt(p["gencase_receipt"], case, "gencase-001")
    _require_completed_receipt(p["solver_receipt"], case, "solver-001")
    files = [
        p["gencase_receipt"], p["generated_xml"], p["generated_bi4"],
        p["solver_receipt"], p["definition"],
    ]
    files.extend(_static_audit_sources(case, mode))
    files.extend(_all_solver_files(case))
    if mode == "frames":
        _require_completed_receipt(p["integrity_receipt"], case, "native-integrity-001")
        files.extend([p["integrity_receipt"], p["integrity_report"]])
    unique: list[Path] = []
    for path in files:
        path = Path(path).resolve()
        if path not in unique:
            unique.append(path)
    for path in unique:
        _regular(path, "preparation input")
    return unique


def _prep_attempt(case: str, mode: str) -> str:
    return f"native-preparation-{'integrity' if mode == 'exclusions' else 'frames'}-001"


def _audit_attempt(mode: str) -> str:
    return "native-integrity-001" if mode == "exclusions" else "native-frame-scan-001"


def _prep_candidate_path(case: str, mode: str) -> Path:
    return PREPARED_ROOT / "requests" / f"{case}-{_prep_attempt(case, mode)}.candidate.json"


def _audit_candidate_paths(case: str, mode: str) -> tuple[Path, Path]:
    branch = "native-exclusions" if mode == "exclusions" else "native-frames"
    suffix = "native-integrity-001" if mode == "exclusions" else "native-frame-scan-001"
    return (
        HELPER_OUTPUT / branch / f"{case}-{suffix}-manifest.json",
        HELPER_OUTPUT / branch / f"{case}-{suffix}-request.json",
    )


def _root_request_path(case: str, attempt: str) -> Path:
    return REQUESTS / f"{case}-{attempt}.json"


def _root_grant_path(case: str, attempt: str) -> Path:
    return GRANTS / f"{case}-{attempt}.json"


def _build_preparation_request(case: str, mode: str) -> dict[str, Any]:
    p = _paths(case)
    inputs = _source_inputs_for_prep(case, mode)
    command_stage = "native-exclusions" if mode == "exclusions" else "native-frames"
    attempt = _prep_attempt(case, mode)
    return {
        "schema": REQUEST_SCHEMA,
        "status": "root_review_candidate_pending_preparation",
        "family_id": "F1",
        "case_id": case,
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "max_wall_seconds": 3600,
        "estimated_storage_bytes": PREPARATION_STORAGE,
        "estimated_temp_peak_bytes": PREPARATION_TEMP,
        "estimated_deferred_read_bytes": 0,
        "output_storage": "upstream_nas",
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "command": [
            str(PYTHON), str(HELPER), command_stage,
            "--case", case,
            "--output-dir", str(HELPER_OUTPUT),
        ],
        "input_files": [str(path) for path in inputs],
        "helper_output_contract": {
            "worker": str(HELPER),
            "output_root": str(HELPER_OUTPUT),
            "must_remain_inside_additional_definitions_prepared": True,
            "candidate_only_until_root_promotion": True,
            "all_completed_solver_regular_files_hashed_by_worker": True,
            "native_frame_files_are_hashed_during_preparation": True,
        },
        "solver_source_contract": {
            "solver_root": str(p["solver_root"]),
            "all_regular_files_input_and_worker_bound": True,
            "frame_count_expected": EXPECTED_FRAMES,
            "time_max_s": TIME_MAX_S,
            "time_out_s": TIME_OUT_S,
            "dp_m": DP_M,
        },
        "gpu_reservation": {"required": False, "gpu_seconds": 0, "runner_owns_gpu_leases": True},
        "launch_authorization": "root-controlled; preparation candidate only; no launch implied",
        "qualification": "receipt-bound native-audit candidate preparation; no scientific credit",
    }


def _validate_preparation_request(request: Mapping[str, Any], case: str, mode: str) -> None:
    attempt = _prep_attempt(case, mode)
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F1" or request.get("case_id") != case or request.get("attempt_id") != attempt:
        raise QueueError("preparation request identity/schema mismatch")
    if request.get("kind") != "cpu" or request.get("cpu_task_kind") != "conversion" or request.get("cpu_threads") != 1:
        raise QueueError("preparation is not a one-thread batch conversion")
    if request.get("max_wall_seconds") != 3600 or request.get("estimated_storage_bytes") != PREPARATION_STORAGE:
        raise QueueError("preparation does not retain the 3600 s/64 MiB contract")
    if request.get("estimated_temp_peak_bytes") != PREPARATION_TEMP or request.get("output_storage") != "upstream_nas":
        raise QueueError("preparation does not retain the NAS/64 MiB temporary-output contract")
    if request.get("cwd") != str(ROOT) or request.get("worktree_root") != str(ROOT):
        raise QueueError("preparation cwd/worktree is not the campaign root")
    if request.get("estimated_deferred_read_bytes") != 0:
        raise QueueError("preparation must bind all solver files rather than defer them")
    gpu = request.get("gpu_reservation")
    if (
        "estimated_peak_gpu_mib" in request
        or not isinstance(gpu, Mapping)
        or gpu.get("required") is not False
        or gpu.get("gpu_seconds") != 0
        or gpu.get("runner_owns_gpu_leases") is not True
    ):
        raise QueueError("preparation request carries an extra GPU reservation")
    command = request.get("command")
    expected_command = [
        str(PYTHON), str(HELPER),
        "native-exclusions" if mode == "exclusions" else "native-frames",
        "--case", case, "--output-dir", str(HELPER_OUTPUT),
    ]
    if command != expected_command:
        raise QueueError("preparation command differs from the frozen helper invocation")
    inputs = request.get("input_files")
    if not isinstance(inputs, list) or not inputs:
        raise QueueError("preparation request has no input files")
    for value in inputs:
        if not isinstance(value, str):
            raise QueueError("preparation input file is not a string")
        _regular(Path(value), "preparation input")


def _assert_completed_preparation_script_binding(
    request: Mapping[str, Any], receipt: Mapping[str, Any], case: str, attempt: str
) -> None:
    """Bind a completed preparation to this v2 file or the consumed v1 file.

    The preparation runner records hashes for every request input both before
    and after execution.  Reuse is therefore allowed only when the immutable
    request names the exact current v2 script or the preserved v1 script and
    both receipt maps carry that script's current digest.  A queue-looking
    path from any other location is rejected instead of being treated as
    equivalent provenance.
    """

    inputs = request.get("input_files")
    if not isinstance(inputs, list):
        raise QueueError(f"{case}/{attempt} preparation input_files is not a list")
    allowed = {SCRIPT.resolve(), LEGACY_SCRIPT.resolve()}
    bound: set[Path] = set()
    for value in inputs:
        if not isinstance(value, str):
            raise QueueError(f"{case}/{attempt} preparation input file is not a string")
        path = Path(value).expanduser().resolve()
        if path.name.startswith("run_solver_native_audit_queue") and path not in allowed:
            raise QueueError(f"{case}/{attempt} preparation binds an unexpected queue script: {path}")
        if path in allowed:
            bound.add(path)
    if not bound:
        raise QueueError(
            f"{case}/{attempt} completed preparation does not bind the current or preserved queue script"
        )

    launch = receipt.get("input_hashes_at_launch")
    after_run = receipt.get("input_hashes_after_run")
    if not isinstance(launch, Mapping) or not isinstance(after_run, Mapping):
        raise QueueError(
            f"{case}/{attempt} completed preparation receipt lacks input launch/after-run hashes"
        )
    for path in sorted(bound, key=str):
        expected = _sha256(_regular(path, f"{case}/{attempt} queue script") or path)
        key = str(path)
        if launch.get(key) != expected or after_run.get(key) != expected:
            raise QueueError(
                f"{case}/{attempt} completed preparation receipt does not bind the current bytes of {path}"
            )


def _reuse_completed_preparation(case: str, mode: str) -> tuple[Path, Path] | None:
    """Reuse an already completed preparation without changing its bytes.

    H052's integrity preparation was consumed by the v1 queue before this v2
    shape fix.  Its request/grant/receipt and old queue-script input are an
    immutable historical stage.  A v2 launch may consume that stage, while a
    preparation created by this file may bind the current v2 script.  Neither
    case is regenerated or accepted without receipt-bound script hashes.
    """

    p = _paths(case)
    attempt = _prep_attempt(case, mode)
    request_path = _root_request_path(case, attempt)
    grant_path = _root_grant_path(case, attempt)
    receipt_path = p["run"] / attempt / "execution-receipt.json"
    request_exists = request_path.exists() or request_path.is_symlink()
    grant_exists = grant_path.exists() or grant_path.is_symlink()
    state, receipt = _receipt_state(receipt_path, case, attempt)
    if not request_exists and not grant_exists and state == "absent":
        attempt_root = p["run"] / attempt
        if attempt_root.exists() or attempt_root.is_symlink():
            raise QueueError(f"{case}/{attempt} has an attempt directory without a terminal receipt; refusing duplicate")
        return None
    if not (request_exists and grant_exists):
        raise QueueError(f"{case}/{attempt} has a partial root request/grant; refusing duplicate")
    if state != "completed" or receipt is None:
        raise QueueError(f"{case}/{attempt} is {state}; completed preparation required before reuse")
    request = _load(request_path, "existing completed preparation request")
    _validate_preparation_request(request, case, mode)
    command = request.get("command")
    _assert_completed_preparation_script_binding(request, receipt, case, attempt)
    if command != [
        str(PYTHON), str(HELPER),
        "native-exclusions" if mode == "exclusions" else "native-frames",
        "--case", case, "--output-dir", str(HELPER_OUTPUT),
    ]:
        raise QueueError("completed preparation does not invoke the frozen preparation worker")
    _validate_grant(grant_path, request_path, case, attempt)
    _assert_receipt_request_binding(receipt, request_path, case, attempt)
    # The worker's candidate is the source for the next stage; require it to
    # exist but never rewrite it or compare it to a newly synthesized request.
    if mode == "exclusions":
        _regular(_audit_candidate_paths(case, mode)[1], "completed native-integrity candidate")
    return request_path, grant_path


def _prepare_or_reuse(case: str, mode: str) -> tuple[Path, Path]:
    reused = _reuse_completed_preparation(case, mode)
    if reused is not None:
        return reused
    return _promote_preparation_candidate(case, mode)


def _write_preparation_candidate(case: str, mode: str) -> Path:
    output = _prep_candidate_path(case, mode)
    expected = _build_preparation_request(case, mode)
    if output.exists() or output.is_symlink():
        existing = _load(output, "existing preparation request candidate")
        _validate_preparation_request(existing, case, mode)
        if existing != expected:
            raise QueueError(f"existing preparation candidate differs; refusing overwrite: {output}")
        return output
    _validate_preparation_request(expected, case, mode)
    _write_immutable(output, expected)
    return output


PROMOTION_FIELDS = {
    "status",
    "candidate_only",
    "submission_forbidden",
    "native_audit_launch_forbidden",
    "root_review_required",
    "no_launch_performed",
    "launch_authorization",
    "input_files",
    "input_bindings",
}


def _assert_only_promotion_fields_changed(candidate: Mapping[str, Any], promoted: Mapping[str, Any]) -> None:
    for key in set(candidate) | set(promoted):
        if key in PROMOTION_FIELDS:
            continue
        if candidate.get(key) != promoted.get(key):
            raise QueueError(f"promotion changed non-authorization candidate field: {key}")


def _append_required_audit_inputs(candidate: Mapping[str, Any], case: str, mode: str) -> dict[str, Any]:
    promoted = copy.deepcopy(dict(candidate))
    current = promoted.get("input_files")
    if not isinstance(current, list) or any(not isinstance(item, str) for item in current):
        raise QueueError("prepared native candidate input_files is malformed")
    input_files = list(dict.fromkeys(current))
    required = [str(RUNTIME_V2), str(RUNTIME_V6), str(RUNTIME_V6_BATCH2), str(SCRIPT), str(HELPER)]
    for value in required:
        if value not in input_files:
            input_files.append(value)
    if mode == "frames":
        for value in input_files:
            if FRAME_RE.fullmatch(Path(value).name):
                raise QueueError("native frame audit listed a Part_*.bi4 as an input_file; frames must be deferred")
        p = _paths(case)
        deferred = Path(str(promoted.get("deferred_source_root", ""))).expanduser().resolve()
        if deferred != p["solver_data"].resolve():
            raise QueueError("native frame candidate deferred_source_root is not the child solver data root")
        _directory(deferred, "deferred native frame source root")
        frame_paths: list[Path] = []
        for path in sorted(deferred.glob("Part_*.bi4")):
            if path.is_symlink() or not path.is_file() or FRAME_RE.fullmatch(path.name) is None:
                raise QueueError(f"deferred native frame is outside the regular Part_####.bi4 contract: {path}")
            frame_paths.append(path)
        indices = [int(FRAME_RE.fullmatch(path.name).group(0)[5:-4]) for path in frame_paths]
        if len(frame_paths) != EXPECTED_FRAMES or indices != list(range(EXPECTED_FRAMES)):
            raise QueueError("deferred native frame source is not exactly Part_0000.bi4 through Part_0240.bi4")
        expected_read = sum(path.stat().st_size for path in frame_paths)
        actual_read = promoted.get("estimated_deferred_read_bytes")
        if not isinstance(actual_read, int) or actual_read != expected_read or expected_read <= 0:
            raise QueueError("native frame candidate estimated_deferred_read_bytes is not source-bound")
    bindings = promoted.get("input_bindings")
    if not isinstance(bindings, dict):
        raise QueueError("prepared native candidate input_bindings is missing")
    for value in input_files:
        path = Path(value)
        bound = bindings.get(value)
        if bound is None:
            bindings[value] = _binding(path, "promoted native audit input")
            continue
        if (
            not isinstance(bound, Mapping)
            or bound.get("path") != str(path.resolve())
            or bound.get("bytes") != path.stat().st_size
            or bound.get("sha256") != _sha256(path)
        ):
            raise QueueError(f"prepared candidate input binding is stale: {path}")
    promoted["input_files"] = input_files
    promoted["input_bindings"] = bindings
    return promoted


def _validate_native_candidate(candidate_path: Path, manifest_path: Path, case: str, mode: str) -> dict[str, Any]:
    candidate = _load(candidate_path, "prepared native audit candidate")
    p = _paths(case)
    attempt = _audit_attempt(mode)
    if candidate.get("schema") != REQUEST_SCHEMA or candidate.get("family_id") != "F1" or candidate.get("case_id") != case or candidate.get("attempt_id") != attempt:
        raise QueueError("prepared native candidate identity/schema mismatch")
    if candidate.get("m4_additional") is not True or candidate.get("m3_completion_claim") is not False:
        raise QueueError("prepared native candidate lacks M4/no-M3 labels")
    if candidate.get("submission_forbidden") is not True or candidate.get("native_audit_launch_forbidden") is not True:
        raise QueueError("prepared native candidate is not still candidate-only")
    if candidate.get("kind") != "cpu" or candidate.get("cpu_task_kind") != "conversion" or candidate.get("cpu_threads") != 1:
        raise QueueError("native audit candidate is not a one-thread conversion")
    if candidate.get("output_storage") != "upstream_nas":
        raise QueueError("native audit candidate is not NAS bound")
    expected_wall = NATIVE_INTEGRITY_MAX_WALL if mode == "exclusions" else NATIVE_FRAME_MAX_WALL
    expected_storage = NATIVE_INTEGRITY_STORAGE if mode == "exclusions" else NATIVE_FRAME_STORAGE
    expected_temp = NATIVE_INTEGRITY_TEMP if mode == "exclusions" else NATIVE_FRAME_TEMP
    if (
        candidate.get("max_wall_seconds") != expected_wall
        or candidate.get("estimated_storage_bytes") != expected_storage
        or candidate.get("estimated_temp_peak_bytes") != expected_temp
        or candidate.get("cwd") != str(ROOT)
        or candidate.get("worktree_root") != str(ROOT)
    ):
        raise QueueError("native audit candidate does not retain the frozen resource contract")
    if mode == "exclusions" and candidate.get("estimated_deferred_read_bytes") != 0:
        raise QueueError("native exclusion candidate unexpectedly defers native frame reads")
    recipe = _assert_recipe_consensus(case, candidate)
    command = candidate.get("command")
    auditor = M2 / ("native_integrity_audit.py" if mode == "exclusions" else "native_frame_identity_scan.py")
    output_name = "integrity.json" if mode == "exclusions" else "frame-identity-scan.json"
    expected_command = [
        str(PYTHON), str(auditor), "--manifest", str(manifest_path),
        "--output", f"{{attempt_root}}/{output_name}",
    ]
    if mode == "frames":
        expected_command.extend(["--max-wall-seconds", "3600"])
    if command != expected_command:
        raise QueueError("native audit candidate command differs from the frozen auditor invocation")
    manifest = _load(manifest_path, "prepared native audit manifest")
    if manifest.get("case_id") != case or manifest.get("m4_additional") is not True or manifest.get("m3_completion_claim") is not False:
        raise QueueError("prepared native manifest lacks M4/no-M3 labels")
    if mode == "exclusions" and manifest.get("schema") != "ds-data-02.upstream-first.native-integrity-manifest.v1":
        raise QueueError("native exclusion manifest schema mismatch")
    if mode == "frames":
        if manifest.get("schema") != "ds-data-02.upstream-first.native-frame-scan-manifest.v1":
            raise QueueError("native frame manifest schema mismatch")
        if manifest.get("expected", {}).get("frame_count") != EXPECTED_FRAMES:
            raise QueueError("native frame manifest does not require 241 frames")
        if Path(str(manifest.get("data_root", ""))).resolve() != p["solver_data"].resolve():
            raise QueueError("native frame manifest data_root is not the child solver data root")
    if Path(str(manifest.get("solver_root", ""))).resolve() != p["solver_root"].resolve():
        raise QueueError("native audit manifest solver_root is not the child solver attempt")
    solver_receipt = _require_completed_receipt(p["solver_receipt"], case, "solver-001")
    _assert_receipt_request_binding(solver_receipt, p["solver_request"], case, "solver-001")
    prepared_frame_sequence = _assert_prepared_solver_binding(candidate, case, mode)
    gencase_hash = _sha256(p["gencase_receipt"])
    if candidate.get("actual_gencase_receipt_sha256") != gencase_hash:
        raise QueueError("prepared native candidate GenCase receipt binding is stale")
    source_key = "source" if mode == "exclusions" else "sources"
    if not isinstance(manifest.get(source_key), Mapping):
        raise QueueError("prepared native manifest lacks source bindings")
    _assert_exact_native_source_bindings(manifest, case, mode, source_field=source_key)
    return {
        "candidate": candidate,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "candidate_path": candidate_path,
        "solver_receipt": solver_receipt,
        "prepared_frame_hash_sequence_sha256": prepared_frame_sequence,
        "recipe": recipe,
    }


def _promote_native_candidate(case: str, mode: str) -> tuple[Path, Path]:
    manifest_path, candidate_path = _audit_candidate_paths(case, mode)
    _regular(manifest_path, "prepared native manifest")
    _regular(candidate_path, "prepared native candidate")
    validated = _validate_native_candidate(candidate_path, manifest_path, case, mode)
    candidate = validated["candidate"]
    promoted = _append_required_audit_inputs(candidate, case, mode)
    promoted.update({
        "status": "root_authorized_actual_completed_source",
        "candidate_only": False,
        "submission_forbidden": False,
        "native_audit_launch_forbidden": False,
        "root_review_required": False,
        "no_launch_performed": True,
        "launch_authorization": "root-controlled; explicit sequential native-audit queue; shared batch-2 runner only",
    })
    _assert_only_promotion_fields_changed(candidate, promoted)
    attempt = _audit_attempt(mode)
    request_path = _root_request_path(case, attempt)
    grant_path = _root_grant_path(case, attempt)
    if request_path.exists() or request_path.is_symlink():
        existing = _load(request_path, "existing promoted native request")
        if existing != promoted:
            raise QueueError(f"existing root native request differs; refusing overwrite: {request_path}")
    else:
        request_path.parent.mkdir(parents=True, exist_ok=True)
        with request_path.open("x", encoding="utf-8") as stream:
            stream.write(_json_bytes(promoted).decode("utf-8"))
    if grant_path.exists() or grant_path.is_symlink():
        _validate_grant(grant_path, request_path, case, attempt)
    else:
        _create_root_grant(request_path)
        _validate_grant(grant_path, request_path, case, attempt)
    return request_path, grant_path


def _promote_preparation_candidate(case: str, mode: str) -> tuple[Path, Path]:
    candidate_path = _write_preparation_candidate(case, mode)
    candidate = _load(candidate_path, "preparation request candidate")
    _validate_preparation_request(candidate, case, mode)
    promoted = copy.deepcopy(candidate)
    promoted.update({
        "status": "root_authorized_actual_completed_source",
        "candidate_only": False,
        "submission_forbidden": False,
        "root_review_required": False,
        "no_launch_performed": True,
        "launch_authorization": "root-controlled; explicit sequential native-audit queue; shared batch-2 runner only",
    })
    _assert_only_promotion_fields_changed(candidate, promoted)
    attempt = _prep_attempt(case, mode)
    request_path = _root_request_path(case, attempt)
    grant_path = _root_grant_path(case, attempt)
    if request_path.exists() or request_path.is_symlink():
        existing = _load(request_path, "existing promoted preparation request")
        if existing != promoted:
            raise QueueError(f"existing root preparation request differs; refusing overwrite: {request_path}")
    else:
        request_path.parent.mkdir(parents=True, exist_ok=True)
        with request_path.open("x", encoding="utf-8") as stream:
            stream.write(_json_bytes(promoted).decode("utf-8"))
    if grant_path.exists() or grant_path.is_symlink():
        _validate_grant(grant_path, request_path, case, attempt)
    else:
        _create_root_grant(request_path)
        _validate_grant(grant_path, request_path, case, attempt)
    return request_path, grant_path


def _create_root_grant(request_path: Path) -> Path:
    """Create a missing grant only during explicit root launch."""
    if not request_path.is_file() or request_path.is_symlink():
        raise QueueError(f"cannot grant missing/non-regular root request: {request_path}")
    sys.path.insert(0, str(UPSTREAM / "batch2-runtime"))
    try:
        from grant_request import grant

        path = Path(grant(request_path))
    except Exception as exc:  # grant validation supplies the detailed error
        raise QueueError(f"root grant creation refused for {request_path}: {exc}") from exc
    return path


def _run_shared(request_path: Path, grant_path: Path, case: str, attempt: str) -> None:
    summary = PREPARED_ROOT / "summaries" / f"{case}-{attempt}-runner-summary.json"
    if summary.exists() or summary.is_symlink():
        raise QueueError(f"refusing to overwrite launcher runner summary: {summary}")
    summary.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(PYTHON), str(RUNTIME_V6_BATCH2), "run",
        "--request", str(request_path),
        "--batch-admission", str(ADMISSION),
        "--batch-grant", str(grant_path),
    ]
    with summary.open("x", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, check=True)


def _run_or_require_completed(case: str, attempt: str, request_path: Path, grant_path: Path) -> dict[str, Any]:
    p = _paths(case)
    attempt_root = p["run"] / attempt
    receipt_path = attempt_root / "execution-receipt.json"
    state, receipt = _receipt_state(receipt_path, case, attempt)
    if state == "completed" and receipt is not None:
        _assert_receipt_request_binding(receipt, request_path, case, attempt)
        return receipt
    if state != "absent":
        raise QueueError(f"{case}/{attempt} is {state}; refusing to wait, overwrite, or duplicate")
    if attempt_root.exists() or attempt_root.is_symlink():
        raise QueueError(f"{case}/{attempt} has an attempt directory without a terminal receipt; refusing duplicate launch")
    _validate_grant(grant_path, request_path, case, attempt)
    _run_shared(request_path, grant_path, case, attempt)
    receipt = _require_completed_receipt(receipt_path, case, attempt)
    _assert_receipt_request_binding(receipt, request_path, case, attempt)
    return receipt


def _expected_native_source_paths(case: str, mode: str) -> dict[str, Path]:
    """Return the exact source files a child auditor is allowed to report."""

    p = _paths(case)
    sources = {
        "dsph_config": DS_CONFIG,
        "gencase_receipt": p["gencase_receipt"],
        "generated_xml": p["generated_xml"],
        "part_info": p["solver_data"] / "PartInfo.ibi4",
        "partvtk": PARTVTK,
        "raw_partout": p["solver_data"] / "PartOut_000.obi4",
        "run_out": p["solver_root"] / "Run.out",
        "runparts": p["solver_root"] / "RunPARTs.csv",
        "solver_receipt": p["solver_receipt"],
        "source_definition": p["definition"],
    }
    if mode == "frames":
        sources["native_integrity"] = p["integrity_report"]
    return sources


def _assert_exact_native_source_bindings(
    report: Mapping[str, Any], case: str, mode: str, *, source_field: str = "source_bindings"
) -> dict[str, dict[str, Any]]:
    sources = report.get(source_field)
    if not isinstance(sources, Mapping):
        raise QueueError("native audit report lacks source_bindings")
    expected = _expected_native_source_paths(case, mode)
    if set(sources) != set(expected):
        raise QueueError(
            f"native {mode} report source keys differ from the exact child contract"
        )
    rebound: dict[str, dict[str, Any]] = {}
    for key, path in expected.items():
        value = sources.get(key)
        if not isinstance(value, Mapping):
            raise QueueError(f"native {mode} source binding is malformed: {key}")
        source = _regular(path, f"expected native {mode} source {key}")
        expected_path = str(source.resolve())
        if value.get("path") != expected_path:
            raise QueueError(f"native {mode} source path is not the exact child file: {key}")
        if value.get("bytes") != source.stat().st_size:
            raise QueueError(f"native {mode} source byte count is stale: {key}")
        digest = value.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise QueueError(f"native {mode} source hash is malformed: {key}")
        if digest != _sha256(source):
            raise QueueError(f"native {mode} source hash is stale: {key}")
        rebound[key] = dict(value)
    return rebound


def _prepared_frame_hash_sequence(candidate: Mapping[str, Any], case: str) -> str:
    """Derive the scanner's frame sequence from prepared metadata only.

    The preparation helper already hashes each regular solver file.  Reusing
    those bindings avoids opening or rehashing any of the deferred BI4 frame
    payloads in the launcher while still closing the exact 241-frame identity
    contract.
    """

    p = _paths(case)
    actual = candidate.get("actual_solver_binding")
    if not isinstance(actual, Mapping):
        raise QueueError("prepared frame candidate lacks actual_solver_binding")
    regular = actual.get("regular_native_solver_files")
    if not isinstance(regular, list):
        raise QueueError("prepared frame candidate lacks regular solver bindings")
    frame_bindings: dict[str, Mapping[str, Any]] = {}
    for item in regular:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise QueueError("prepared solver binding is malformed")
        path = Path(str(item["path"])).expanduser().resolve()
        if path.parent != p["solver_data"].resolve() or FRAME_RE.fullmatch(path.name) is None:
            continue
        if path.name in frame_bindings:
            raise QueueError(f"prepared solver bindings duplicate frame: {path.name}")
        if type(item.get("bytes")) is not int or item["bytes"] <= 0:
            raise QueueError(f"prepared frame binding has invalid byte count: {path.name}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise QueueError(f"prepared frame binding has invalid hash: {path.name}")
        frame_bindings[path.name] = item
    expected_names = [f"Part_{index:04d}.bi4" for index in range(EXPECTED_FRAMES)]
    if sorted(frame_bindings) != expected_names:
        raise QueueError("prepared frame bindings are not exactly Part_0000.bi4 through Part_0240.bi4")
    deferred = actual.get("frame_files_deferred_from_input_files")
    expected_paths = [str((p["solver_data"] / name).resolve()) for name in expected_names]
    if deferred != expected_paths:
        raise QueueError("prepared frame deferred-source list is not the exact case data root")
    digest = hashlib.sha256()
    for name in expected_names:
        item = frame_bindings[name]
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _assert_prepared_solver_binding(candidate: Mapping[str, Any], case: str, mode: str) -> str | None:
    p = _paths(case)
    actual = candidate.get("actual_solver_binding")
    if not isinstance(actual, Mapping):
        raise QueueError("prepared native candidate lacks actual solver binding")
    receipt = actual.get("receipt")
    if not isinstance(receipt, Mapping):
        raise QueueError("prepared native candidate lacks actual solver receipt binding")
    solver_hash = _sha256(p["solver_receipt"])
    if receipt.get("path") != str(p["solver_receipt"].resolve()) or receipt.get("bytes") != p["solver_receipt"].stat().st_size or receipt.get("sha256") != solver_hash:
        raise QueueError("prepared native candidate solver receipt binding is stale")
    if candidate.get("actual_solver_receipt_sha256") != solver_hash:
        raise QueueError("prepared native candidate solver receipt hash is stale")
    regular = actual.get("regular_native_solver_files")
    if not isinstance(regular, list) or not regular:
        raise QueueError("prepared native candidate lacks regular solver-file bindings")
    seen: set[str] = set()
    for item in regular:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise QueueError("prepared regular solver binding is malformed")
        path = Path(str(item["path"])).expanduser().resolve()
        try:
            path.relative_to(p["solver_root"].resolve())
        except ValueError as exc:
            raise QueueError(f"prepared solver binding escapes the case solver root: {path}") from exc
        if str(path) in seen:
            raise QueueError(f"prepared solver bindings duplicate a regular file: {path}")
        seen.add(str(path))
        if type(item.get("bytes")) is not int or item["bytes"] <= 0 or not SHA256_RE.fullmatch(str(item.get("sha256", ""))):
            raise QueueError(f"prepared solver binding is incomplete: {path}")
    if mode == "frames":
        return _prepared_frame_hash_sequence(candidate, case)
    return None


def _assert_integrity_report(case: str) -> dict[str, Any]:
    p = _paths(case)
    report = _load(p["integrity_report"], "native-integrity report")
    if report.get("schema") != "ds-data-02.upstream-first.f1-native-integrity.v1" or report.get("status") != "verified" or report.get("case_id") != case:
        raise QueueError("native-integrity report is not actual verified case-bound evidence")
    if report.get("fatal_findings") not in (None, [], {}):
        raise QueueError("native-integrity report contains fatal findings")
    p_solver_root = p["solver_root"].resolve()
    if Path(str(report.get("solver_root", ""))).expanduser().resolve() != p_solver_root:
        raise QueueError("native-integrity report solver_root is not the exact child solver root")
    _assert_exact_native_source_bindings(report, case, "exclusions")
    execution_receipt = _require_completed_receipt(p["integrity_receipt"], case, "native-integrity-001")
    _assert_receipt_request_binding(
        execution_receipt,
        _root_request_path(case, "native-integrity-001"),
        case,
        "native-integrity-001",
    )
    _assert_runner_report_binding(case, "native-integrity-001", p["integrity_report"], execution_receipt)
    return report


def _assert_frame_report(case: str, prepared_candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    p = _paths(case)
    report = _load(p["frame_report"], "native-frame report")
    coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
    finite = report.get("finite_field_audit") if isinstance(report.get("finite_field_audit"), Mapping) else {}
    identity = report.get("identity_axis") if isinstance(report.get("identity_axis"), Mapping) else {}
    if report.get("schema") != "ds-data-02.upstream-first.native-frame-identity-scan.v1" or report.get("status") != "verified" or report.get("case_id") != case:
        raise QueueError("native-frame report is not actual verified case-bound evidence")
    if report.get("fatal_findings") not in (None, [], {}):
        raise QueueError("native-frame report contains fatal findings")
    if Path(str(report.get("solver_root", ""))).expanduser().resolve() != p["solver_root"].resolve():
        raise QueueError("native-frame report solver_root is not the exact child solver root")
    if Path(str(report.get("native_data_root", ""))).expanduser().resolve() != p["solver_data"].resolve():
        raise QueueError("native-frame report native_data_root is not the exact child solver data root")
    if coverage.get("frame_count") != EXPECTED_FRAMES or coverage.get("first_frame") != "Part_0000.bi4" or coverage.get("last_frame") != "Part_0240.bi4":
        raise QueueError("native-frame report does not cover exactly Part_0000 through Part_0240")
    if coverage.get("raw_frames_staged_or_copied") is not False or not isinstance(coverage.get("frame_hash_sequence_sha256"), str) or not SHA256_RE.fullmatch(coverage["frame_hash_sequence_sha256"]):
        raise QueueError("native-frame report lacks actual deferred source frame hash output")
    if finite.get("frames_checked") != EXPECTED_FRAMES or finite.get("all_frames_checked") is not True:
        raise QueueError("native-frame finite audit did not verify all 241 frames")
    if identity.get("all_ids_unique_and_in_generated_cohort") is not True:
        raise QueueError("native-frame identity audit did not close the generated cohort")
    _assert_exact_native_source_bindings(report, case, "frames")
    if prepared_candidate is None:
        _, candidate_path = _audit_candidate_paths(case, "frames")
        prepared_candidate = _load(candidate_path, "prepared native-frame candidate")
    prepared_sequence = _assert_prepared_solver_binding(prepared_candidate, case, "frames")
    if coverage.get("frame_hash_sequence_sha256") != prepared_sequence:
        raise QueueError("native-frame report hash sequence differs from prepared solver source bindings")
    execution_receipt = _require_completed_receipt(p["frame_receipt"], case, "native-frame-scan-001")
    _assert_receipt_request_binding(
        execution_receipt,
        _root_request_path(case, "native-frame-scan-001"),
        case,
        "native-frame-scan-001",
    )
    _assert_runner_report_binding(case, "native-frame-scan-001", p["frame_report"], execution_receipt)
    return report


def _launch(case: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    case = _case_id(case)
    p = _paths(case)
    request = _solver_request(case)
    _validate_solver_grant(case, request)
    # The solver request and grant are root-owned immutable artifacts.  The
    # launcher never edits or regenerates either one.
    solver_receipt = _run_or_require_completed(case, "solver-001", p["solver_request"], p["solver_grant"])
    _assert_receipt_request_binding(solver_receipt, p["solver_request"], case, "solver-001")
    _regular(p["gencase_receipt"], "actual GenCase receipt")
    _regular(p["generated_xml"], "actual generated XML")
    _regular(p["generated_bi4"], "actual generated BI4")

    prep_request, prep_grant = _prepare_or_reuse(case, "exclusions")
    _run_or_require_completed(case, _prep_attempt(case, "exclusions"), prep_request, prep_grant)
    _, integrity_candidate = _audit_candidate_paths(case, "exclusions")
    _regular(integrity_candidate, "prepared native-integrity candidate")
    integrity_request, integrity_grant = _promote_native_candidate(case, "exclusions")
    _run_or_require_completed(case, "native-integrity-001", integrity_request, integrity_grant)
    _assert_integrity_report(case)
    integrity_binding = _assert_runner_report_binding(
        case,
        "native-integrity-001",
        p["integrity_report"],
        _load(p["integrity_receipt"], "native-integrity execution receipt"),
    )

    prep_request, prep_grant = _prepare_or_reuse(case, "frames")
    _run_or_require_completed(case, _prep_attempt(case, "frames"), prep_request, prep_grant)
    _, frame_candidate = _audit_candidate_paths(case, "frames")
    _regular(frame_candidate, "prepared native-frame candidate")
    frame_request, frame_grant = _promote_native_candidate(case, "frames")
    _run_or_require_completed(case, "native-frame-scan-001", frame_request, frame_grant)
    integrity = _assert_integrity_report(case)
    _, prepared_frame_candidate_path = _audit_candidate_paths(case, "frames")
    prepared_frame_candidate = _load(prepared_frame_candidate_path, "prepared native-frame candidate")
    frame = _assert_frame_report(case, prepared_frame_candidate)
    frame_binding = _assert_runner_report_binding(
        case,
        "native-frame-scan-001",
        p["frame_report"],
        _load(p["frame_receipt"], "native-frame execution receipt"),
    )
    return {
        "schema": PLAN_SCHEMA,
        "case_id": case,
        "status": "completed_verified_native_exclusion_and_241_frame_audit",
        "no_solver_or_audit_duplicate": True,
        "native_integrity": {"status": integrity.get("status"), "report": str(p["integrity_report"]), "receipt_binding": integrity_binding},
        "native_frame_scan": {"status": frame.get("status"), "frame_count": frame.get("coverage", {}).get("frame_count"), "report": str(p["frame_report"]), "receipt_binding": frame_binding},
    }


def _gate_summary(path: Path, case: str, attempt: str) -> dict[str, Any]:
    state, receipt = _receipt_state(path, case, attempt)
    result: dict[str, Any] = {"status": state, "path": str(path)}
    if state == "completed" and receipt is not None:
        result["sha256"] = _sha256(path)
        result["returncode"] = receipt.get("returncode")
    return result


def _plan(case: str) -> dict[str, Any]:
    case = _case_id(case)
    p = _paths(case)
    solver = _solver_request(case)
    grant = _validate_solver_grant(case, solver)
    recipe = _assert_recipe_consensus(case, {})
    static = []
    for mode in ("exclusions", "frames"):
        for path in _static_audit_sources(case, mode):
            if path not in static:
                _regular(path, "native queue static source")
                static.append(path)
    prep_specs = []
    for mode in ("exclusions", "frames"):
        attempt = _prep_attempt(case, mode)
        audit = _audit_attempt(mode)
        reused_paths = _reuse_completed_preparation(case, mode)
        reused = reused_paths is not None
        reuse_binding: dict[str, Any] = {}
        if reused_paths is not None:
            reused_request, reused_grant = reused_paths
            reuse_receipt = p["run"] / attempt / "execution-receipt.json"
            reuse_binding = {
                "request": _binding(reused_request, "reused preparation request"),
                "grant": _binding(reused_grant, "reused preparation grant"),
                "receipt": _binding(reuse_receipt, "reused preparation receipt"),
                "legacy_queue_script": str(LEGACY_SCRIPT),
            }
        prep_specs.append({
            "mode": mode,
            "attempt_id": attempt,
            "candidate_request": str(_prep_candidate_path(case, mode)),
            "root_request": str(_root_request_path(case, attempt)),
            "root_grant": str(_root_grant_path(case, attempt)),
            "helper_command": [str(PYTHON), str(HELPER), "native-exclusions" if mode == "exclusions" else "native-frames", "--case", case, "--output-dir", str(HELPER_OUTPUT)],
            "cpu_task_kind": "conversion",
            "cpu_threads": 1,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": PREPARATION_STORAGE,
            "gpu_reservation": False,
            "depends_on": ["solver-001"] + ([] if mode == "exclusions" else ["native-integrity-001"]),
            "produces_candidate": str(_audit_candidate_paths(case, mode)[1]),
            "audit_attempt_id": audit,
            "reuse_completed_preparation_if_present": reused,
            "reused_preparation_bindings": reuse_binding,
            "candidate_recipe_fields_optional": True,
        })
    gates = {
        "gencase": _gate_summary(p["gencase_receipt"], case, "gencase-001"),
        "solver": _gate_summary(p["solver_receipt"], case, "solver-001"),
        "native_integrity": _gate_summary(p["integrity_receipt"], case, "native-integrity-001"),
        "native_frame_scan": _gate_summary(p["frame_receipt"], case, "native-frame-scan-001"),
    }
    return {
        "schema": PLAN_SCHEMA,
        "status": "ready_for_root_review",
        "case_id": case,
        "family_id": "F1",
        "created_by": str(SCRIPT),
        "helper_binding": _binding(HELPER, "frozen native preparation helper"),
        "no_launch_performed": True,
        "launch_confirmation": CONFIRMATION,
        "shared_runtime": {
            "runtime_v2": _binding(RUNTIME_V2, "runtime v2"),
            "runtime_v6": _binding(RUNTIME_V6, "runtime v6"),
            "runtime_v6_batch2": _binding(RUNTIME_V6_BATCH2, "batch-2 runtime v6"),
            "batch_admission": _binding(ADMISSION, "immutable batch-2 admission"),
            "parent_budget_and_gpu_leases": "owned by shared batch-2 runner only",
        },
        "solver": {
            "request": _binding(p["solver_request"], "immutable root solver request"),
            "grant": _binding(p["solver_grant"], "immutable root solver grant"),
            "request_sha256": _sha256(p["solver_request"]),
            "grant_sha256": _sha256(p["solver_grant"]),
            "reused_unchanged": True,
            "recipe": {"solver_reservation_bytes": SOLVER_STORAGE, "time_max_s": TIME_MAX_S, "time_out_s": TIME_OUT_S, "dp_m": DP_M, "expected_frames": EXPECTED_FRAMES},
        },
        "derived_recipe": recipe,
        "source_gates": gates,
        "static_native_sources": [{"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size} for path in static],
        "preparation": {
            "output_root": str(HELPER_OUTPUT),
            "output_root_restriction": "frozen helper may write only below m4-additional-definitions/prepared",
            "charged_request_contract": {"cpu_task_kind": "conversion", "cpu_threads": 1, "max_wall_seconds": 3600, "estimated_storage_bytes": PREPARATION_STORAGE, "estimated_temp_peak_bytes": PREPARATION_TEMP, "no_gpu_reservation": True},
            "all_solver_regular_files_hashed_by_helper": True,
            "native_frames_deferred_only_after_promotion": True,
        },
        "sequence": ["solver-001", "native-preparation-integrity-001", "native-integrity-001", "native-preparation-frames-001", "native-frame-scan-001"],
        "preparation_stages": prep_specs,
        "final_assertions": {
            "native_integrity_status": "verified",
            "native_frame_scan_status": "verified",
            "frame_count": EXPECTED_FRAMES,
            "finite_fields": ["position", "velocity", "density"],
            "fatal_findings": [],
            "every_completed_stage_request_sha256_equals_immutable_request": True,
            "solver_request_sha256_is_required": True,
            "exact_case_source_bindings": True,
            "auditor_stdout_and_report_bound_to_execution_receipt": True,
            "frame_hash_sequence_matches_prepared_solver_bindings": True,
            "recipe_derived_from_actual_xml_manifest_and_immutable_solver_request": True,
            "optional_candidate_recipe_fields_must_match_if_present": True,
            "completed_preparation_reused_byte_for_byte": True,
        },
        "root_review_notes": [
            "The existing solver request/grant are immutable and reused byte-for-byte; this launcher never edits them.",
            "Preparation is a charged one-thread conversion under the same batch-2 single-heavy queue, with a 64 MiB output reservation and no GPU lease.",
            "Native exclusion runs before the frame preparation; frame files are deferred through deferred_source_root and estimated_deferred_read_bytes.",
            "Promotion changes pending authorization/provenance input fields only and refuses scientific or command changes.",
            "Running or failed receipts stop the queue; no attempt is overwritten or duplicated.",
            "Every terminal stage receipt must carry the exact immutable request hash; a missing solver hash is fatal.",
            "Native reports must bind the exact child receipts/files and auditor stdout; frame sequence output must equal the charged preparation metadata.",
        ],
        "launch_policy": {"default": "prepare_only", "explicit_launch": "--launch --root-launch-confirmation ROOT_APPROVED_M4_NATIVE_SOLVER_AUDIT", "launches_now": False},
    }


def _write_plan(case: str, plan_output: Path | None) -> Path:
    case = _case_id(case)
    output = (plan_output or _paths(case)["plan"]).expanduser().resolve()
    try:
        output.relative_to(PREPARED_ROOT.resolve())
    except ValueError as exc:
        raise QueueError(f"plan output must remain below m4-native-prepared: {output}") from exc
    plan = _plan(case)
    _write_immutable(output, plan)
    return output


def _load_plan(path: Path, case: str) -> dict[str, Any]:
    plan = _load(path, "native queue plan")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("case_id") != case or plan.get("created_by") != str(SCRIPT):
        raise QueueError("native queue plan schema/case/creator mismatch")
    if plan.get("no_launch_performed") is not True:
        raise QueueError("native queue plan does not record prepare-only review state")
    helper_binding = plan.get("helper_binding")
    if not isinstance(helper_binding, Mapping) or helper_binding.get("sha256") != _sha256(HELPER):
        raise QueueError("native queue helper changed since plan review")
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="H052/H058 or the full UF_F1_MDBC_DP010_H052/H058 id")
    parser.add_argument("--plan-output", type=Path, help="immutable plan path below m4-native-prepared")
    parser.add_argument("--launch", action="store_true", help="explicitly launch the reviewed sequential queue")
    parser.add_argument("--root-launch-confirmation", help=f"must equal {CONFIRMATION!r} with --launch")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    case = _case_id(args.case)
    if not args.launch:
        output = _write_plan(case, args.plan_output)
        print(json.dumps({"case_id": case, "status": "ready_for_root_review", "plan": str(output), "launches_now": False}, sort_keys=True))
        return 0
    if args.root_launch_confirmation != CONFIRMATION:
        raise QueueError(f"--launch requires --root-launch-confirmation {CONFIRMATION}")
    plan_path = (args.plan_output or _paths(case)["plan"]).expanduser().resolve()
    plan = _load_plan(plan_path, case)
    result = _launch(case, plan)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QueueError as exc:
        print(f"native solver/audit queue rejected: {exc}", file=sys.stderr)
        raise SystemExit(2)
