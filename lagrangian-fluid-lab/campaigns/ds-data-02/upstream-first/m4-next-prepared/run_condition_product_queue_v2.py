#!/usr/bin/env python3
"""Prepare, and only when explicitly requested launch, one M4 condition pipeline.

This helper is the root-reviewable handoff for the fine ``.01/.025`` M4
conditions.  It is intentionally separate from the historical H050 queue and
the consumed v1 handoff.  This v2 preflight binds every completed source
receipt to its immutable request, checks exact generated/solver/data roots,
and validates the child recipe against the actual XML and manifest before an
immutable direct-conversion candidate can be reused or created.

``--launch`` is an explicit root-controlled operation.  It reuses an existing
H060 direct request/grant byte-for-byte, materializes later stage requests only
after their preceding receipt is completed, runs every heavy operation through
the batch-2 runner, and finally delegates to the root relocation queue v2.
There is no implicit launch, polling, raw-frame scan, or native-payload hash
in this file.  Only small metadata and known regular solver files are hashed;
the actual native frame sequence remains bound through the charged auditor
reports.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve()
BASE = SCRIPT.parents[1]
ROOT = BASE.parents[3]
PREP = BASE / "m4-next-prepared"
RUNS = Path("/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
ADMISSION = BASE / "batch2-runtime/root-batch-2-admission.json"
RUNTIME_V2 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V6_BATCH2 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6_batch2.py"
CONVERTER = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
CONVERTER_V2 = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert_v2.py"
L2_READER = ROOT / "lagrangian-fluid-lab/scripts/l2_reader.py"
PRODUCER = BASE / "m4/m4_direct_enrich.py"
ADAPTER = BASE / "m4/m4_portable_adapter.py"
INTERFACE_SCHEMA = BASE / "m4/native-conversion-interface.schema.json"
DS_CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
# The native auditors use the official PartVTKOut binary.  The product
# converter keeps ``PARTVTK`` above for compatibility with the existing H060
# candidate; report source bindings must nevertheless be checked against the
# binary that actually appeared in the immutable audit request.
AUDIT_PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
MOTHER_OWNER = BASE / "m2/upstream_conversion/official-mdbc-owner-metadata.json"
RELOCATION_QUEUE = BASE / "run_m4_relocation_queue_v2.py"
MOTHER_CASE = "UF_F1_MDBC_DAMBREAK3D"
EXPECTED_FRAMES = 241
DIRECT_ATTEMPT_BY_SUFFIX = {
    "H052": "m4-direct-conversion-001",
    "H058": "m4-direct-conversion-001",
    # Attempt 001 is preserved as an immutable terminal storage failure.
    "H060": "m4-direct-conversion-002",
}
ENRICH_ATTEMPT = "m4-enrichment-001"
PORTABLE_ATTEMPT = "m4-portable-build-001"
DIRECT_RESERVE = 12 * 1024**3
TEMP_RESERVE = 1024**3
CASE_SUFFIXES = ("H052", "H058", "H060")
REQUEST_SCHEMA = "ds-data-02.runner.request.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
OWNER_SCHEMA = "ds-data-02.m4.official-mdbc-owner-metadata.v1"
PHYSICAL_BINDING_SCHEMA = "ds-data-02.physical-binding.v1"
LINEAGE_GROUP_ID = "F1_official_v54_mdbc_dambreak3d_v1"
CONTROL_FAMILY_ID = "F1_OFFICIAL_MDBC_DAMBREAK3D_CONTROLS_V1"


def _direct_attempt(case: str) -> str:
    suffix = case.rsplit("_", 1)[-1]
    try:
        return DIRECT_ATTEMPT_BY_SUFFIX[suffix]
    except KeyError as exc:
        raise QueueError(f"no direct-conversion attempt mapping for {case}") from exc


class QueueError(RuntimeError):
    """A review or launch precondition failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str, *, required: bool = True) -> Path | None:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        if required:
            raise QueueError(f"{label} is not a regular file: {path}")
        return None
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


def _binding(path: Path, role: str, *, hash_bytes: bool = True) -> dict[str, Any]:
    path = _regular(path, role)  # type: ignore[assignment]
    result: dict[str, Any] = {"path": str(path), "role": role, "bytes": path.stat().st_size}
    if hash_bytes:
        result["sha256"] = _sha256(path)
    return result


def _json_hash(path: Path) -> str:
    return _sha256(path)


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise QueueError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _case_id(suffix: str) -> str:
    if suffix not in CASE_SUFFIXES:
        raise QueueError(f"unsupported condition suffix: {suffix}")
    return f"UF_F1_MDBC_DP010_{suffix}"


def _case_paths(case: str) -> dict[str, Path]:
    if not case.startswith("UF_F1_MDBC_DP010_"):
        raise QueueError(f"unsupported case: {case}")
    suffix = case.rsplit("_", 1)[-1]
    if suffix not in CASE_SUFFIXES:
        raise QueueError(f"unsupported case: {case}")
    direct_attempt = _direct_attempt(case)
    run = RUNS / case
    if suffix == "H060":
        evidence = BASE / "m3/f1-fine-dp010-t025"
    else:
        evidence = BASE / "m4-additional-definitions"
    return {
        "run": run,
        "owner": PREP / "owners" / f"{case}-owner-v1.json",
        "xml": run / "gencase-001" / f"{case}.xml",
        "gencase_receipt": run / "gencase-001/execution-receipt.json",
        "solver_receipt": run / "solver-001/execution-receipt.json",
        "integrity_receipt": run / "native-integrity-001/execution-receipt.json",
        "integrity_report": run / "native-integrity-001/integrity.json",
        "frame_receipt": run / "native-frame-scan-001/execution-receipt.json",
        "frame_report": run / "native-frame-scan-001/frame-identity-scan.json",
        "manifest": evidence / "manifests" / f"{case}.json",
        "semantic_diff": evidence / "semantic-diff.json",
        "definition": BASE / "m3/f1-fine-dp010-t025/input" / f"{case}_Def.xml"
        if suffix == "H060"
        else BASE / "m4-additional-definitions" / f"{case}_Def.xml",
        "direct_attempt": direct_attempt,
        "candidate": PREP / "requests" / f"{case}-{direct_attempt}.candidate.json",
        "root_direct_request": BASE / "requests" / f"{case}-{direct_attempt}.json",
        "root_direct_grant": BASE / "batch2-runtime/grants" / f"{case}-{direct_attempt}.json",
        "solver_request": BASE / "requests" / f"{case}-solver-001.json",
        "solver_grant": BASE / "batch2-runtime/grants" / f"{case}-solver-001.json",
    }


def _validate_evidence(case: str, paths: Mapping[str, Path], owner: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _load(paths["manifest"], "case manifest")
    diff = _load(paths["semantic_diff"], "semantic diff")
    if manifest.get("schema") != "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.case-manifest.v1":
        raise QueueError(f"unsupported manifest schema for {case}: {manifest.get('schema')!r}")
    if manifest.get("case_id") != case:
        raise QueueError(f"manifest case mismatch: {manifest.get('case_id')!r} != {case!r}")
    if diff.get("schema") != "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.semantic-diff.v1":
        raise QueueError(f"unsupported semantic diff schema for {case}: {diff.get('schema')!r}")
    comparisons = diff.get("comparisons")
    comparison = next((item for item in comparisons if isinstance(item, Mapping) and item.get("case_id") == case), None) \
        if isinstance(comparisons, list) else None
    if comparison is None:
        raise QueueError(f"semantic diff has no comparison for {case}")
    physical = manifest.get("physical_axis")
    numerical = manifest.get("numerical_output_recipe")
    if not isinstance(physical, Mapping) or not isinstance(numerical, Mapping):
        raise QueueError(f"manifest lacks physical or numerical recipe for {case}")
    depth = float(physical["candidate_value_m"])
    owner_depth = float(owner["physical_binding"]["parameters"]["initial_depth_m"])
    if abs(depth - owner_depth) > 1e-9:
        raise QueueError(f"owner depth {owner_depth} disagrees with manifest depth {depth}")
    expected_frames = numerical.get("expected_frames", numerical.get("estimated_saved_frames"))
    if float(numerical["candidate_time_out_s"]) != 0.025 or int(expected_frames) != EXPECTED_FRAMES:
        raise QueueError(f"unexpected candidate output recipe for {case}")
    if comparison.get("physical_change_count") != 1 or comparison.get("numerical_output_schedule_change_count") != 1:
        raise QueueError(f"physical/sampling difference counts are not exactly one for {case}")
    if comparison.get("all_non_allowed_semantics_equal") is not True:
        raise QueueError(f"non-allowed semantic equality is not verified for {case}")
    if comparison.get("fixed_controls_excluding_output_schedule_equal") is not True:
        raise QueueError(f"fixed controls are not verified for {case}")
    return {
        "case_manifest": _binding(paths["manifest"], "M3-compatible child case manifest"),
        "semantic_diff": _binding(paths["semantic_diff"], "M3-compatible semantic diff"),
        "physical_axis": {
            "name": physical.get("name"),
            "mother_value_m": float(physical["mother_value_m"]),
            "candidate_value_m": depth,
            "label": "physical initial fill depth difference",
        },
        "sampling_difference": {
            "mother_time_out_s": float(numerical["source_time_out_s"]),
            "candidate_time_out_s": float(numerical["candidate_time_out_s"]),
            "label": "output sampling difference; no retiming",
        },
        "scope": {
            "event_window_s": [0.0, 6.0],
            "expected_frames": EXPECTED_FRAMES,
            "primary_observations": ["H1", "H2", "H3", "H4"],
            "auxiliary_observations": [f"P{i}" for i in range(1, 9)],
            "comparison_role": "diagnostic differences; no acceptance threshold",
        },
        "m4_additional": case.endswith(("H052", "H058")),
        "m3_completion_claim": False if case.endswith(("H052", "H058")) else None,
    }


def _prepare_owner(case: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    existing = _regular(paths["owner"], "child owner metadata", required=False)
    if existing is None:
        command = [
            str(PYTHON), str(PRODUCER), "prepare-owner",
            "--owner-metadata", str(MOTHER_OWNER),
            "--generated-xml", str(paths["xml"]),
            "--case-manifest", str(paths["manifest"]),
            "--semantic-diff", str(paths["semantic_diff"]),
            "--output", str(paths["owner"]),
        ]
        for path, label in ((MOTHER_OWNER, "mother owner metadata"), (paths["xml"], "generated XML"),
                            (paths["manifest"], "case manifest"), (paths["semantic_diff"], "semantic diff"),
                            (PYTHON, "canonical Python"), (PRODUCER, "frozen M4 producer")):
            _regular(path, label)
        paths["owner"].parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as exc:
            raise QueueError(f"owner preparation failed for {case}: {exc.stderr.strip()}") from exc
        existing = _regular(paths["owner"], "prepared child owner metadata")
    owner = _load(existing, "prepared child owner metadata")
    if owner.get("case_id") != case or owner.get("condition_role") != "m3_depth_child":
        raise QueueError(f"owner metadata is not the expected depth child for {case}")
    generated = owner.get("generated_xml")
    if not isinstance(generated, Mapping) or generated.get("sha256") != _sha256(paths["xml"]):
        raise QueueError(f"owner generated XML binding does not match actual XML for {case}")
    return {"record": owner, "binding": _binding(existing, "immutable child owner metadata")}


def _receipt_identity_value(receipt: Mapping[str, Any], key: str) -> tuple[Any, bool]:
    """Return one unambiguous identity value from a receipt and its request."""
    request = receipt.get("request")
    values: list[Any] = []
    for container in (receipt, request if isinstance(request, Mapping) else {}):
        if key in container and container[key] is not None:
            values.append(container[key])
    if not values or any(value != values[0] for value in values[1:]):
        return None, False
    return values[0], True


def _receipt_identity_error(receipt: Mapping[str, Any], case: str, attempt: str) -> str | None:
    for key, expected in (("case_id", case), ("attempt_id", attempt)):
        actual, present = _receipt_identity_value(receipt, key)
        if not present or actual != expected:
            return f"receipt_{key}_missing_or_mismatch"
    return None


def _completed_returncode_is_zero(receipt: Mapping[str, Any]) -> bool:
    value = receipt.get("returncode")
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _receipt_gate(path: Path, case: str, attempt: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {"status": "missing", "path": str(path), "reason": f"missing_{attempt.replace('-', '_')}_receipt"}
    try:
        receipt = _load(path, f"{attempt} execution receipt")
    except QueueError as exc:
        return {"status": "invalid", "path": str(path), "reason": str(exc)}
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        return {"status": "invalid", "path": str(path), "reason": "unexpected_receipt_schema"}
    identity_error = _receipt_identity_error(receipt, case, attempt)
    if identity_error is not None:
        return {"status": "invalid", "path": str(path), "reason": identity_error}
    status = receipt.get("status")
    if status != "completed":
        return {"status": str(status or "unknown"), "path": str(path), "reason": f"receipt_not_completed_{status or 'unknown'}"}
    if not _completed_returncode_is_zero(receipt):
        return {"status": "invalid", "path": str(path), "reason": "completed_returncode_not_zero"}
    return {"status": "completed", "binding": _binding(path, f"completed {attempt} receipt"), "receipt": receipt}


def _source_gates(case: str, paths: Mapping[str, Path], owner: Mapping[str, Any]) -> dict[str, Any]:
    gates: dict[str, Any] = {
        "gencase": _receipt_gate(paths["gencase_receipt"], case, "gencase-001"),
        "solver": _receipt_gate(paths["solver_receipt"], case, "solver-001"),
        "native_integrity_receipt": _receipt_gate(paths["integrity_receipt"], case, "native-integrity-001"),
        "native_frame_scan_receipt": _receipt_gate(paths["frame_receipt"], case, "native-frame-scan-001"),
    }
    xml = _regular(paths["xml"], "actual generated XML", required=False)
    if xml is None:
        gates["generated_xml"] = {"status": "missing", "path": str(paths["xml"]), "reason": "missing_actual_generated_xml"}
    else:
        expected_xml = owner.get("generated_xml", {}).get("sha256") if isinstance(owner.get("generated_xml"), Mapping) else None
        actual_xml = _sha256(xml)
        gates["generated_xml"] = _binding(xml, "actual generated XML")
        if expected_xml != actual_xml:
            gates["generated_xml"]["status"] = "mismatch"
            gates["generated_xml"]["reason"] = "owner_generated_xml_hash_mismatch"
        else:
            gates["generated_xml"]["status"] = "verified"

    integrity = _regular(paths["integrity_report"], "native integrity report", required=False)
    if integrity is None:
        gates["native_integrity_report"] = {"status": "missing", "path": str(paths["integrity_report"]), "reason": "missing_native_integrity_report"}
    else:
        report = _load(integrity, "native integrity report")
        status = report.get("status")
        valid = status == "verified" and report.get("schema") == "ds-data-02.upstream-first.f1-native-integrity.v1" and report.get("case_id") == case
        gates["native_integrity_report"] = _binding(integrity, "verified native integrity report")
        gates["native_integrity_report"].update({"status": "verified" if valid else "invalid", "report_status": status})
        if valid:
            try:
                _assert_native_report_source_bindings(
                    report,
                    integrity,
                    gates["native_integrity_receipt"].get("receipt"),
                    case,
                    paths,
                    "integrity",
                )
            except QueueError as exc:
                valid = False
                gates["native_integrity_report"]["reason"] = str(exc)
                gates["native_integrity_report"]["status"] = "invalid"
        if not valid and "reason" not in gates["native_integrity_report"]:
            gates["native_integrity_report"]["reason"] = "native_integrity_report_not_verified"

    frame = _regular(paths["frame_report"], "native frame scan report", required=False)
    if frame is None:
        gates["native_frame_scan_report"] = {"status": "missing", "path": str(paths["frame_report"]), "reason": "missing_native_frame_scan_report"}
    else:
        report = _load(frame, "native frame scan report")
        coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
        finite = report.get("finite_field_audit") if isinstance(report.get("finite_field_audit"), Mapping) else {}
        identity = report.get("identity_axis") if isinstance(report.get("identity_axis"), Mapping) else {}
        valid = (
            report.get("schema") == "ds-data-02.upstream-first.native-frame-identity-scan.v1"
            and report.get("status") == "verified"
            and report.get("case_id") == case
            and not report.get("fatal_findings")
            and int(coverage.get("frame_count", -1)) == EXPECTED_FRAMES
            and str(coverage.get("first_frame")) == "Part_0000.bi4"
            and str(coverage.get("last_frame")) == "Part_0240.bi4"
            and int(finite.get("frames_checked", -1)) == EXPECTED_FRAMES
            and finite.get("all_frames_checked") is True
            and identity.get("all_ids_unique_and_in_generated_cohort") is True
            and coverage.get("raw_frames_staged_or_copied") is False
        )
        gates["native_frame_scan_report"] = _binding(frame, "verified native frame scan report")
        gates["native_frame_scan_report"].update({
            "status": "verified" if valid else "invalid",
            "frame_count": coverage.get("frame_count"),
            "frame_bytes_total": coverage.get("frame_bytes_total"),
            "frame_hash_sequence_sha256": coverage.get("frame_hash_sequence_sha256"),
        })
        if valid:
            try:
                _assert_native_report_source_bindings(
                    report,
                    frame,
                    gates["native_frame_scan_receipt"].get("receipt"),
                    case,
                    paths,
                    "frames",
                )
            except QueueError as exc:
                valid = False
                gates["native_frame_scan_report"]["reason"] = str(exc)
                gates["native_frame_scan_report"]["status"] = "invalid"
        if not valid and "reason" not in gates["native_frame_scan_report"]:
            gates["native_frame_scan_report"]["reason"] = "native_frame_scan_not_full_verified_241_frame_scope"

    required = ("gencase", "solver", "generated_xml", "native_integrity_receipt", "native_integrity_report",
                "native_frame_scan_receipt", "native_frame_scan_report")
    blockers: list[str] = []
    for key in required:
        gate = gates[key]
        if gate.get("status") != ("completed" if key in {"gencase", "solver", "native_integrity_receipt", "native_frame_scan_receipt"} else "verified"):
            blockers.append(str(gate.get("reason", f"{key}_gate_not_ready")))
    gates["status"] = "ready" if not blockers else "blocked"
    gates["blockers"] = list(dict.fromkeys(blockers))
    return gates


def _exact_path(value: Any, expected: Path, label: str) -> None:
    if not isinstance(value, str) or value != str(expected.resolve()):
        raise QueueError(f"{label} is not the exact expected path: {value!r} != {str(expected.resolve())!r}")


def _source_request_candidates(case: str, attempt: str) -> list[Path]:
    """Return immutable request locations in precedence order.

    GenCase/solver requests are root-promoted under ``requests``.  The H060
    native audit requests predate the M4 root handoff and remain immutable in
    the M3 audit evidence directory; future H052/H058 audit promotions use
    the root location first.  Missing requests are intentionally preserved as
    missing blockers rather than synthesized here.
    """
    candidates = [BASE / "requests" / f"{case}-{attempt}.json"]
    if attempt in {"native-integrity-001", "native-frame-scan-001"}:
        candidates.extend([
            BASE / "m4-native-prepared/requests" / f"{case}-{attempt}.json",
            BASE / "m4-additional-definitions/prepared/native-exclusions" / f"{case}-{attempt}-request.json",
            BASE / "m4-additional-definitions/prepared/native-frames" / f"{case}-{attempt}-request.json",
            BASE / "m3/f1-fine-dp010-t025/audits" / f"{case}-{attempt}-request.json",
        ])
    return candidates


def _source_request_path(case: str, attempt: str) -> Path:
    candidates = _source_request_candidates(case, attempt)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    return candidates[0].resolve()


def _source_roots(paths: Mapping[str, Path]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, path, role in (
        ("gencase_root", paths["gencase_receipt"].parent, "actual GenCase attempt root"),
        ("solver_root", paths["solver_receipt"].parent, "actual solver attempt root"),
        ("data_root", paths["solver_receipt"].parent / "data", "actual native solver data root"),
    ):
        if path.is_symlink() or not path.is_dir():
            result[key] = {"path": str(path.resolve()), "role": role, "status": "missing"}
        else:
            result[key] = {"path": str(path.resolve()), "role": role, "status": "ready"}
    return result


def _small_source_paths(paths: Mapping[str, Path]) -> dict[str, Path]:
    solver_root = paths["solver_receipt"].parent
    return {
        "generated_xml": paths["xml"],
        "gencase_receipt": paths["gencase_receipt"],
        "solver_receipt": paths["solver_receipt"],
        "run_csv": solver_root / "Run.csv",
        "run_out": solver_root / "Run.out",
        "run_parts_csv": solver_root / "RunPARTs.csv",
        "part_info": solver_root / "data/PartInfo.ibi4",
        "part_out_000": solver_root / "data/PartOut_000.obi4",
        "native_integrity_receipt": paths["integrity_receipt"],
        "native_integrity_report": paths["integrity_report"],
        "native_frame_scan_receipt": paths["frame_receipt"],
        "native_frame_scan_report": paths["frame_report"],
    }


def _small_source_bindings(paths: Mapping[str, Path]) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    for key, path in _small_source_paths(paths).items():
        if path.is_file() and not path.is_symlink():
            if key in {"part_info", "part_out_000"}:
                bindings[key] = {
                    "path": str(path.resolve()),
                    "role": f"actual small source {key}",
                    "bytes": path.stat().st_size,
                    "hash_policy": "stat-only; authoritative native-auditor charge binding",
                }
            else:
                bindings[key] = _binding(path, f"actual small source {key}")
        else:
            bindings[key] = {"path": str(path.resolve()), "role": f"actual small source {key}", "status": "missing"}
    return bindings


def _assert_source_receipt_request_binding(
    receipt: Mapping[str, Any], request_path: Path, case: str, attempt: str
) -> dict[str, Any]:
    """Require a completed source receipt to bind the exact immutable request."""
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise QueueError(f"{case}/{attempt} receipt schema is not {RECEIPT_SCHEMA}")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise QueueError(f"{case}/{attempt} source receipt is not completed with returncode 0")
    request = _load(request_path, f"immutable {attempt} request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise QueueError(f"{case}/{attempt} source request schema is not {REQUEST_SCHEMA}")
    if request.get("family_id") != "F1" or request.get("case_id") != case or request.get("attempt_id") != attempt:
        raise QueueError(f"{case}/{attempt} source request identity mismatch")
    actual_hash = receipt.get("request_sha256")
    expected_hash = _sha256(request_path)
    if not isinstance(actual_hash, str) or actual_hash != expected_hash:
        raise QueueError(f"{case}/{attempt} source receipt request_sha256 does not equal immutable request")
    nested = receipt.get("request")
    if isinstance(nested, Mapping) and (nested.get("case_id") not in {None, case} or nested.get("attempt_id") not in {None, attempt}):
        raise QueueError(f"{case}/{attempt} source receipt nested request identity mismatch")
    return request


def _validate_source_request(
    case: str,
    attempt: str,
    request: Mapping[str, Any],
    paths: Mapping[str, Path],
    manifest: Mapping[str, Any],
) -> None:
    """Check source request roots and recipe fields without native payload reads."""
    physical = manifest.get("physical_axis")
    numerical = manifest.get("numerical_output_recipe")
    if not isinstance(physical, Mapping) or not isinstance(numerical, Mapping):
        raise QueueError(f"{case} manifest lacks physical/numerical recipe")
    expected_depth = float(physical["candidate_value_m"])
    expected_dp = float(numerical["dp_m"])
    expected_time_max = float(numerical["time_max_s"])
    expected_time_out = float(numerical["candidate_time_out_s"])
    expected_frames = int(numerical.get("expected_frames", numerical.get("estimated_saved_frames", EXPECTED_FRAMES)))
    if request.get("physical_axis") not in {None, "initial_fill_height_m", "initial_water_depth_m"}:
        raise QueueError(f"{case}/{attempt} request physical axis mismatch")
    for key, expected in (("physical_axis_value_m", expected_depth), ("dp_m", expected_dp), ("time_max_s", expected_time_max), ("time_out_s", expected_time_out)):
        if key in request and float(request[key]) != expected:
            raise QueueError(f"{case}/{attempt} request {key} mismatch")
    request_frames = request.get("expected_frames", request.get("estimated_saved_frames"))
    if request_frames is not None and int(request_frames) != expected_frames:
        raise QueueError(f"{case}/{attempt} request frame-count recipe mismatch")
    input_files = request.get("input_files")
    if not isinstance(input_files, list) or any(not isinstance(item, str) for item in input_files):
        raise QueueError(f"{case}/{attempt} request input_files is malformed")
    expected_xml = paths["xml"].resolve()
    expected_gencase = paths["gencase_receipt"].resolve()
    expected_solver = paths["solver_receipt"].resolve()
    expected_data = (paths["solver_receipt"].parent / "data").resolve()
    for item in input_files:
        if Path(item).name.startswith("Part_") and Path(item).suffix == ".bi4":
            raise QueueError(f"{case}/{attempt} request lists a native payload frame")
    if attempt == "gencase-001":
        _exact_path(request.get("definition_copy"), paths["definition"], f"{case}/{attempt} definition_copy")
        if request.get("definition_copy_sha256") != _sha256(paths["definition"]):
            raise QueueError(f"{case}/{attempt} definition_copy hash mismatch")
        if str(expected_xml) in input_files or str(expected_data) in input_files:
            raise QueueError(f"{case}/{attempt} GenCase request binds a post-GenCase source")
    elif attempt == "solver-001":
        _exact_path(request.get("gencase_receipt"), expected_gencase, f"{case}/{attempt} gencase_receipt")
        if request.get("gencase_receipt_sha256") != _sha256(expected_gencase):
            raise QueueError(f"{case}/{attempt} gencase receipt hash mismatch")
        deferred = request.get("deferred_generated_inputs")
        generated_inputs = deferred if isinstance(deferred, list) else input_files
        if str(expected_xml) not in generated_inputs or str(expected_gencase) not in generated_inputs:
            raise QueueError(f"{case}/{attempt} deferred generated-input roots are not exact")
        prefix = request.get("generated_prefix")
        if prefix is not None:
            _exact_path(prefix, paths["gencase_receipt"].parent / case, f"{case}/{attempt} generated_prefix")
    elif attempt == "native-integrity-001":
        required = (expected_gencase, expected_xml, expected_solver, paths["solver_receipt"].parent / "Run.out", paths["solver_receipt"].parent / "RunPARTs.csv", expected_data / "PartInfo.ibi4", expected_data / "PartOut_000.obi4")
        if any(str(path.resolve()) not in input_files for path in required):
            raise QueueError(f"{case}/{attempt} native-integrity input roots are incomplete")
    elif attempt == "native-frame-scan-001":
        _exact_path(request.get("deferred_source_root"), expected_data, f"{case}/{attempt} deferred_source_root")
        required = (expected_xml, expected_solver, paths["solver_receipt"].parent / "Run.out", paths["solver_receipt"].parent / "RunPARTs.csv", expected_data / "PartInfo.ibi4", expected_data / "PartOut_000.obi4", paths["integrity_report"])
        if any(str(path.resolve()) not in input_files for path in required):
            raise QueueError(f"{case}/{attempt} native-frame input roots are incomplete")


def _native_report_source_paths(paths: Mapping[str, Path], mode: str) -> dict[str, Path]:
    """Return the exact small-file source contract emitted by native auditors.

    The report contracts intentionally exclude ``Part_*.bi4``.  Their large
    frame payloads remain charged to the native frame auditor; this preflight
    checks only the regular metadata files and the auditor's recorded hashes.
    """
    if mode not in {"integrity", "frames"}:
        raise QueueError(f"unsupported native report mode: {mode}")
    solver_root = paths["solver_receipt"].parent
    data_root = solver_root / "data"
    sources = {
        "dsph_config": DS_CONFIG,
        "gencase_receipt": paths["gencase_receipt"],
        "generated_xml": paths["xml"],
        "part_info": data_root / "PartInfo.ibi4",
        "partvtk": AUDIT_PARTVTK,
        "raw_partout": data_root / "PartOut_000.obi4",
        "run_out": solver_root / "Run.out",
        "runparts": solver_root / "RunPARTs.csv",
        "solver_receipt": paths["solver_receipt"],
        "source_definition": paths["definition"],
    }
    if mode == "frames":
        sources["native_integrity"] = paths["integrity_report"]
    return sources


def _assert_native_report_source_bindings(
    report: Mapping[str, Any],
    report_path: Path,
    execution_receipt: Mapping[str, Any] | None,
    case: str,
    paths: Mapping[str, Path],
    mode: str,
) -> None:
    """Close native report roots and metadata bindings without frame hashing."""
    if mode == "integrity":
        _exact_path(report.get("gencase_root"), paths["gencase_receipt"].parent, f"{case} native-integrity gencase_root")
    elif "gencase_root" in report:
        _exact_path(report.get("gencase_root"), paths["gencase_receipt"].parent, f"{case} native-frame gencase_root")
    _exact_path(report.get("solver_root"), paths["solver_receipt"].parent, f"{case} native-{mode} solver_root")
    if mode == "frames":
        _exact_path(report.get("native_data_root"), paths["solver_receipt"].parent / "data", f"{case} native-frame native_data_root")

    expected = _native_report_source_paths(paths, mode)
    source_bindings = report.get("source_bindings")
    if not isinstance(source_bindings, Mapping) or set(source_bindings) != set(expected):
        raise QueueError(f"{case} native-{mode} report source_bindings differ from the exact child contract")

    if not isinstance(execution_receipt, Mapping):
        raise QueueError(f"{case} native-{mode} report has no completed execution receipt")
    launch_hashes = execution_receipt.get("input_hashes_at_launch")
    after_hashes = execution_receipt.get("input_hashes_after_run")
    if not isinstance(launch_hashes, Mapping) or not isinstance(after_hashes, Mapping):
        raise QueueError(f"{case} native-{mode} receipt lacks input hash bindings")

    report_hashes = report.get("source_hashes")
    if mode == "integrity":
        expected_hash_keys = {f"{key}_sha256" for key in expected}
        if not isinstance(report_hashes, Mapping) or set(report_hashes) != expected_hash_keys:
            raise QueueError(f"{case} native-integrity source_hashes differ from the exact child contract")
    elif report_hashes is not None and not isinstance(report_hashes, Mapping):
        raise QueueError(f"{case} native-frame source_hashes are malformed")

    for key, expected_path in expected.items():
        source = _regular(expected_path, f"expected native {mode} source {key}")
        assert source is not None
        binding = source_bindings.get(key)
        if not isinstance(binding, Mapping):
            raise QueueError(f"{case} native-{mode} source binding is malformed: {key}")
        _exact_path(binding.get("path"), source, f"{case} native-{mode} source {key} path")
        if type(binding.get("bytes")) is not int or binding["bytes"] != source.stat().st_size:
            raise QueueError(f"{case} native-{mode} source byte count is stale: {key}")
        digest = binding.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise QueueError(f"{case} native-{mode} source hash is malformed: {key}")
        source_name = str(source)
        if launch_hashes.get(source_name) != digest or after_hashes.get(source_name) != digest:
            raise QueueError(f"{case} native-{mode} source execution hash is stale: {key}")
        if isinstance(report_hashes, Mapping) and mode == "integrity" and report_hashes.get(f"{key}_sha256") != digest:
            raise QueueError(f"{case} native-integrity source_hashes binding is stale: {key}")


def _strict_source_gates(
    case: str,
    paths: Mapping[str, Path],
    owner: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    gates = _source_gates(case, paths, owner)
    source_requests: dict[str, Any] = {}
    for key, attempt in (
        ("gencase", "gencase-001"),
        ("solver", "solver-001"),
        ("native_integrity_receipt", "native-integrity-001"),
        ("native_frame_scan_receipt", "native-frame-scan-001"),
    ):
        request_path = _source_request_path(case, attempt)
        source_requests[key] = {"path": str(request_path), "status": "ready" if request_path.is_file() and not request_path.is_symlink() else "missing"}
        gate = gates[key]
        if gate.get("status") != "completed":
            continue
        try:
            request = _assert_source_receipt_request_binding(gate["receipt"], request_path, case, attempt)
            _validate_source_request(case, attempt, request, paths, manifest)
            gate["request_binding"] = _binding(request_path, f"immutable {attempt} source request")
            gate["request"] = {"case_id": request.get("case_id"), "attempt_id": request.get("attempt_id"), "schema": request.get("schema")}
        except (KeyError, QueueError) as exc:
            gate["status"] = "invalid"
            gate["reason"] = str(exc)
    roots = _source_roots(paths)
    small = _small_source_bindings(paths)
    blockers: list[str] = []
    required_receipts = {"gencase", "solver", "native_integrity_receipt", "native_frame_scan_receipt"}
    required_reports = {"generated_xml", "native_integrity_report", "native_frame_scan_report"}
    for key in required_receipts | required_reports:
        expected_status = "completed" if key in required_receipts else "verified"
        if gates[key].get("status") != expected_status:
            blockers.append(str(gates[key].get("reason", f"{key}_gate_not_ready")))
    for key, value in roots.items():
        if value.get("status") != "ready":
            blockers.append(f"missing_actual_{key}")
    gates["source_request_bindings"] = source_requests
    gates["native_roots"] = roots
    gates["small_source_bindings"] = small
    gates["status"] = "ready" if not blockers else "blocked"
    gates["blockers"] = list(dict.fromkeys(blockers))
    return gates


def _xml_recipe(path: Path) -> dict[str, float]:
    _regular(path, "actual generated XML")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise QueueError(f"actual generated XML is not parseable: {path}") from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    depth: float | None = None
    dp: float | None = None
    time_max: float | None = None
    time_out: float | None = None
    for element in root.iter():
        tag = local(element.tag)
        if tag == "size" and "z" in element.attrib and depth is None:
            depth = float(element.attrib["z"])
        elif tag == "dp" and "value" in element.attrib and dp is None:
            dp = float(element.attrib["value"])
        elif tag == "parameter":
            key = element.attrib.get("key")
            if key == "TimeMax":
                time_max = float(element.attrib["value"])
            elif key == "TimeOut":
                time_out = float(element.attrib["value"])
    if None in {depth, dp, time_max, time_out}:
        raise QueueError(f"actual generated XML lacks depth/dp/TimeMax/TimeOut: {path}")
    return {"initial_depth_m": depth, "dp_m": dp, "time_max_s": time_max, "time_out_s": time_out}


def _validate_owner_recipe(
    case: str,
    paths: Mapping[str, Path],
    owner: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Cross-check owner semantics, XML values, and manifest recipe fields."""
    if owner.get("schema") != OWNER_SCHEMA:
        raise QueueError(f"{case} owner metadata schema mismatch")
    if owner.get("case_id") != case or owner.get("family_id") != "F1":
        raise QueueError(f"{case} owner metadata case/family mismatch")
    if owner.get("lineage_group_id") != LINEAGE_GROUP_ID:
        raise QueueError(f"{case} owner lineage_group_id mismatch")
    physical_binding = owner.get("physical_binding")
    if not isinstance(physical_binding, Mapping) or physical_binding.get("schema") != PHYSICAL_BINDING_SCHEMA:
        raise QueueError(f"{case} owner physical_binding schema mismatch")
    if physical_binding.get("physical_case_id") != case or physical_binding.get("family_id") != "F1":
        raise QueueError(f"{case} owner physical_binding case/family mismatch")
    if physical_binding.get("lineage_group_id") != LINEAGE_GROUP_ID:
        raise QueueError(f"{case} owner physical_binding lineage mismatch")
    if physical_binding.get("control_family_id") != CONTROL_FAMILY_ID or owner.get("control_family_id") != CONTROL_FAMILY_ID:
        raise QueueError(f"{case} owner control family mismatch")
    if manifest.get("schema") != "ds-data-02.upstream-first.m3.f1-fine-dp010-t025.case-manifest.v1":
        raise QueueError(f"{case} manifest schema mismatch")
    if manifest.get("case_id") != case or manifest.get("family_id") != "F1":
        raise QueueError(f"{case} manifest case/family mismatch")
    source_mother = manifest.get("source_mother")
    if not isinstance(source_mother, Mapping) or source_mother.get("case_id") != MOTHER_CASE:
        raise QueueError(f"{case} manifest mother reference mismatch")
    axis = manifest.get("physical_axis")
    numerical = manifest.get("numerical_output_recipe")
    owner_recipe = owner.get("numerical_output_recipe")
    owner_parameters = owner.get("parameter_values")
    bound_parameters = physical_binding.get("parameters")
    if not isinstance(axis, Mapping) or not isinstance(numerical, Mapping) or not isinstance(owner_recipe, Mapping) or not isinstance(owner_parameters, Mapping) or not isinstance(bound_parameters, Mapping):
        raise QueueError(f"{case} owner/manifest recipe fields are malformed")
    expected_depth = float(axis["candidate_value_m"])
    expected_dp = float(numerical["dp_m"])
    expected_time_max = float(numerical["time_max_s"])
    expected_time_out = float(numerical["candidate_time_out_s"])
    expected_frames = int(numerical.get("expected_frames", numerical.get("estimated_saved_frames", EXPECTED_FRAMES)))
    if expected_frames != EXPECTED_FRAMES:
        raise QueueError(f"{case} manifest frame recipe is not {EXPECTED_FRAMES}")
    values = {
        "initial_depth_m": expected_depth,
        "dp_m": expected_dp,
        "time_max_s": expected_time_max,
        "time_out_s": expected_time_out,
        "expected_frames": expected_frames,
    }
    if float(owner_recipe.get("dp_m", -1)) != expected_dp or float(owner_recipe.get("time_max_s", -1)) != expected_time_max or float(owner_recipe.get("time_out_s", -1)) != expected_time_out:
        raise QueueError(f"{case} owner numerical_output_recipe disagrees with manifest")
    if float(owner_parameters.get("initial_depth_m", -1)) != expected_depth or float(bound_parameters.get("initial_depth_m", -1)) != expected_depth:
        raise QueueError(f"{case} owner physical depth disagrees with manifest")
    xml_values = _xml_recipe(paths["xml"])
    for key, expected in (("initial_depth_m", expected_depth), ("dp_m", expected_dp), ("time_max_s", expected_time_max), ("time_out_s", expected_time_out)):
        if xml_values[key] != expected:
            raise QueueError(f"{case} generated XML {key} disagrees with manifest")
    generated = owner.get("generated_xml")
    if not isinstance(generated, Mapping) or generated.get("path") != str(paths["xml"].resolve()) or generated.get("sha256") != _sha256(paths["xml"]):
        raise QueueError(f"{case} owner generated XML binding is stale")
    return {"recipe": values, "xml": xml_values, "physical_axis": dict(axis), "numerical_output_recipe": dict(numerical)}


def _admission_binding() -> dict[str, Any]:
    return _binding(ADMISSION, "immutable batch-2 admission")


def _static_bindings() -> dict[str, dict[str, Any] | dict[str, Any]]:
    result: dict[str, dict[str, Any] | dict[str, Any]] = {}
    for name, path, role in (
        ("runtime_v2", RUNTIME_V2, "runtime v2"),
        ("runtime_v6", RUNTIME_V6, "runtime v6"),
        ("runtime_v6_batch2", RUNTIME_V6_BATCH2, "batch-2 runtime v6"),
        ("converter", CONVERTER, "direct converter"),
        ("converter_v2", CONVERTER_V2, "bounded-scratch direct converter v2"),
        ("producer", PRODUCER, "frozen M4 enrichment producer"),
        ("adapter", ADAPTER, "frozen M4 portable adapter"),
        ("interface_schema", INTERFACE_SCHEMA, "native interface schema"),
        ("l2_reader", L2_READER, "portable L2 reader"),
        ("dsph_config", DS_CONFIG, "canonical DsphConfig"),
        ("decoder", DECODER, "canonical BI4 decoder"),
        ("partvtk", PARTVTK, "canonical PartVTK"),
    ):
        result[name] = _binding(path, role)
    if RELOCATION_QUEUE.is_file() and not RELOCATION_QUEUE.is_symlink():
        result["relocation_queue_v2"] = _binding(RELOCATION_QUEUE, "root M4 relocation queue v2")
    else:
        result["relocation_queue_v2"] = {"path": str(RELOCATION_QUEUE), "role": "root M4 relocation queue v2", "status": "pending_root_file"}
    return result


def _native_files(paths: Mapping[str, Path]) -> dict[str, Any]:
    solver_root = paths["solver_receipt"].parent
    data_root = solver_root / "data"
    rows = []
    for filename, role in (
        ("Run.csv", "solver_run_ledger"),
        ("Run.out", "solver_log"),
        ("RunPARTs.csv", "solver_particle_output_ledger"),
        ("data/PartInfo.ibi4", "native_initial_particle_info"),
        ("data/PartOut_000.obi4", "native_partout_motive_source"),
    ):
        path = solver_root / filename
        if path.is_file() and not path.is_symlink():
            # Hash only the known small ledgers.  PartInfo/PartOut remain
            # stat-only and the shared auditor owns every raw-frame payload.
            row = {"path": str(path), "bytes": path.stat().st_size, "role": role}
            if filename not in {"data/PartInfo.ibi4", "data/PartOut_000.obi4"}:
                row["sha256"] = _sha256(path)
            else:
                row["hash_policy"] = "stat-only; authoritative native-auditor charge binding"
            rows.append(row)
    return {
        "files": rows,
        "required_relative_paths": ["Run.csv", "Run.out", "RunPARTs.csv", "data/PartInfo.ibi4", "data/PartOut_000.obi4"],
        "raw_frame_set": {"root": str(data_root), "pattern": "Part_*.bi4", "count": EXPECTED_FRAMES, "staged_or_copied": False},
        "hash_policy": "known regular solver metadata files are hashed here; native Part_*.bi4 payload hashes remain auditor-owned",
    }


def _source_bindings(paths: Mapping[str, Path], gates: Mapping[str, Any], owner_binding: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    bindings: dict[str, Any] = {
        "owner": dict(owner_binding),
        "generated_xml": gates["generated_xml"],
        "case_manifest": evidence["case_manifest"],
        "semantic_diff": evidence["semantic_diff"],
        "mother_owner": _binding(MOTHER_OWNER, "immutable mother reference metadata"),
    }
    for key in ("gencase", "solver", "native_integrity_receipt", "native_integrity_report", "native_frame_scan_receipt", "native_frame_scan_report"):
        gate = gates[key]
        if gate.get("status") in {"completed", "verified"}:
            # Receipt gates nest their immutable file binding under ``binding``;
            # report gates are already flattened binding dictionaries.
            binding = gate.get("binding") if isinstance(gate.get("binding"), Mapping) else gate
            if isinstance(binding, Mapping) and binding.get("sha256"):
                bindings[key] = dict(binding)
            request_binding = gate.get("request_binding")
            if isinstance(request_binding, Mapping):
                bindings[f"{key}_request"] = dict(request_binding)
    if isinstance(gates.get("source_request_bindings"), Mapping):
        bindings["source_request_bindings"] = copy.deepcopy(dict(gates["source_request_bindings"]))
    if isinstance(gates.get("native_roots"), Mapping):
        bindings["native_roots"] = copy.deepcopy(dict(gates["native_roots"]))
    if isinstance(gates.get("small_source_bindings"), Mapping):
        bindings["small_source_bindings"] = copy.deepcopy(dict(gates["small_source_bindings"]))
    return bindings


def _cohort_from_existing_request(case: str, paths: Mapping[str, Path], candidate: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    if candidate and isinstance(candidate.get("actual_generated_case_binding"), Mapping):
        binding = candidate["actual_generated_case_binding"]
        if isinstance(binding.get("cohort"), Mapping):
            return copy.deepcopy(dict(binding["cohort"]))
    if paths["solver_request"].is_file() and not paths["solver_request"].is_symlink():
        request = _load(paths["solver_request"], "solver request")
        for key in ("actual_generated_cohort", "actual_gencase_binding"):
            value = request.get(key)
            if key == "actual_gencase_binding" and isinstance(value, Mapping):
                value = value.get("cohort")
            if isinstance(value, Mapping):
                return copy.deepcopy(dict(value))
    return None


def _direct_command(case: str, paths: Mapping[str, Path]) -> list[str]:
    solver_root = paths["solver_receipt"].parent
    data_root = solver_root / "data"
    return [
        str(PYTHON), str(CONVERTER_V2), "--data-root", str(data_root),
        "--generated-xml", str(paths["xml"]), "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/direct-conversion-report.json", "--solver-log", str(solver_root / "Run.out"),
        "--solver-receipt", str(paths["solver_receipt"]), "--gencase-receipt", str(paths["gencase_receipt"]),
        "--owner-metadata", str(paths["owner"]), "--decoder", str(DECODER), "--partvtk", str(PARTVTK),
        "--validation-dir", "{attempt_root}/partvtk-validation", "--particle-chunk", "65536",
    ]


def _flatten_file_bindings(bindings: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten semantic source maps to the path-keyed input contract."""
    flattened: dict[str, dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        path = value.get("path")
        if isinstance(path, str) and type(value.get("bytes")) is int:
            flattened[path] = copy.deepcopy(dict(value))
        for child in value.values():
            if isinstance(child, Mapping):
                visit(child)

    visit(bindings)
    return flattened


def _build_direct_candidate(case: str, paths: Mapping[str, Path], owner_info: Mapping[str, Any], evidence: Mapping[str, Any], gates: Mapping[str, Any]) -> dict[str, Any] | None:
    if gates.get("status") != "ready":
        return None
    existing = _regular(paths["candidate"], "direct-conversion candidate", required=False)
    if existing is not None:
        candidate = _load(existing, "direct-conversion candidate")
        _validate_candidate_v2(candidate, case, paths, gates, owner_info["binding"])
        return {"path": str(existing), "binding": _binding(existing, "immutable direct-conversion candidate"), "record": candidate, "created": False}

    cohort = _cohort_from_existing_request(case, paths)
    if cohort is None:
        raise QueueError(f"actual generated fluid cohort binding is absent for {case}")
    xml_binding = gates["generated_xml"]
    frame = gates["native_frame_scan_report"]
    frame_bytes = int(frame.get("frame_bytes_total") or 0)
    frame_sequence = frame.get("frame_hash_sequence_sha256")
    if frame_bytes <= 0 or not isinstance(frame_sequence, str):
        raise QueueError(f"verified frame scan lacks deferred byte/sequence binding for {case}")
    receipt_bindings = _source_bindings(paths, gates, owner_info["binding"], evidence)
    receipt_bindings["solver"]["role"] = "completed solver receipt with exact source hash"
    direct_input_files = [
        str(paths["owner"]), str(paths["xml"]), str(CONVERTER), str(CONVERTER_V2), str(DECODER), str(PARTVTK), str(DS_CONFIG),
        str(paths["solver_receipt"].parent / "Run.out"), str(paths["solver_receipt"].parent / "RunPARTs.csv"),
        str(paths["solver_receipt"].parent / "Run.csv"), str(paths["solver_receipt"].parent / "data/PartInfo.ibi4"),
        str(paths["solver_receipt"].parent / "data/PartOut_000.obi4"), str(paths["solver_receipt"]), str(paths["gencase_receipt"]),
        str(paths["integrity_report"]), str(paths["integrity_receipt"]), str(paths["frame_report"]), str(paths["frame_receipt"]),
        str(paths["manifest"]), str(paths["semantic_diff"]), str(PRODUCER), str(RUNTIME_V2), str(RUNTIME_V6), str(RUNTIME_V6_BATCH2),
    ]
    input_bindings = _flatten_file_bindings(receipt_bindings)
    source_request_bindings = receipt_bindings.get("source_request_bindings", {})
    if isinstance(source_request_bindings, Mapping):
        for value in source_request_bindings.values():
            if isinstance(value, Mapping) and value.get("status") == "ready" and isinstance(value.get("path"), str):
                source_request_path = Path(value["path"])
                direct_input_files.append(str(source_request_path))
                input_bindings[str(source_request_path)] = _binding(source_request_path, "immutable completed-source request")
    for path, role in (
        (CONVERTER, "direct converter"),
        (CONVERTER_V2, "bounded-scratch direct converter v2"),
        (DECODER, "canonical BI4 decoder"),
        (PARTVTK, "canonical PartVTK"),
        (DS_CONFIG, "canonical DsphConfig"),
        (PRODUCER, "frozen M4 enrichment producer"),
        (RUNTIME_V2, "runtime v2"),
        (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V6_BATCH2, "batch-2 runtime v6"),
    ):
        binding = _binding(path, role)
        input_bindings[binding["path"]] = binding
    depth = float(evidence["physical_axis"]["candidate_value_m"])
    native_files = _native_files(paths)
    present_native = {str(Path(item["path"]).relative_to(paths["solver_receipt"].parent)) for item in native_files["files"]}
    missing_native = [name for name in native_files["required_relative_paths"] if name not in present_native]
    if missing_native:
        raise QueueError(f"completed source gates but required regular native solver files are absent for {case}: {missing_native}")
    candidate: dict[str, Any] = {
        "schema": "ds-data-02.runner.request.v1",
        "status": "candidate_actual_completed_sources_root_review_pending",
        "candidate_only": True,
        "submission_forbidden": True,
        "root_review_required": True,
        "no_launch_performed": True,
        "launch_authorization": "root-controlled; candidate only; no conversion or enrichment launch performed",
        "family_id": "F1", "case_id": case, "attempt_id": paths["direct_attempt"], "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 4,
        "max_wall_seconds": 3600, "estimated_storage_bytes": DIRECT_RESERVE, "estimated_temp_peak_bytes": TEMP_RESERVE,
        "output_storage": "upstream_nas", "cwd": str(ROOT), "worktree_root": str(ROOT),
        "command": _direct_command(case, paths), "input_files": list(dict.fromkeys(direct_input_files)),
        "deferred_source_root": str(paths["solver_receipt"].parent / "data"),
        "estimated_deferred_read_bytes": frame_bytes * 3,
        "deferred_source_binding": {
            "kind": "native_solver_data_root", "path": str(paths["solver_receipt"].parent / "data"),
            "binding_source": str(paths["frame_report"]), "binding_source_sha256": frame["sha256"],
            "frame_count": EXPECTED_FRAMES, "frame_bytes_total": frame_bytes, "estimated_read_bytes": frame_bytes * 3,
            "first_frame": "Part_0000.bi4", "last_frame": "Part_0240.bi4", "frame_hash_sequence_sha256": frame_sequence,
            "raw_frames_pattern": "Part_*.bi4", "raw_frames_opened_one_at_a_time": True, "raw_frames_staged_or_copied": False,
        },
        "actual_completed_receipts": {
            "gencase": receipt_bindings["gencase"],
            "solver": receipt_bindings["solver"],
            "native_integrity": receipt_bindings["native_integrity_receipt"],
            "native_frame_scan": receipt_bindings["native_frame_scan_receipt"],
        },
        "actual_generated_case_binding": {"status": "actual_completed", "generated_xml": xml_binding, "cohort": cohort},
        "input_file_bindings": input_bindings,
        "regular_native_solver_files": native_files,
        "native_audit_binding": {
            "integrity": {"status": "verified", "receipt": receipt_bindings["native_integrity_receipt"], "report": receipt_bindings["native_integrity_report"]},
            "full_frame_scan": {"status": "verified", "receipt": receipt_bindings["native_frame_scan_receipt"], "report": receipt_bindings["native_frame_scan_report"], "frame_count": EXPECTED_FRAMES, "frame_bytes_total": frame_bytes, "frame_hash_sequence_sha256": frame_sequence, "identity_scope": "(Zone,Idp)", "raw_frames_staged_or_copied": False},
        },
        "m3_evidence_binding": evidence,
        "m4_producer_binding": {"path": str(PRODUCER), "sha256": _sha256(PRODUCER), "prepare_owner_completed": True, "owner_metadata_input": owner_info["binding"], "producer_role": "read-only enrichment of completed standard direct-converter HDF5; no source mutation"},
        "scope": {"dimension": 3, "frames": EXPECTED_FRAMES, "full_state": True, "identity_axis": "(Zone,Idp)", "initial_depth_m": depth, "window_s": [0, 6], "qualification": "scoped_diagnostic_only_pending_full_product_replay", "physical_conditions_credited": 0, "raw_frame_staging": False},
        "mother_reference_policy": {"source_mother": MOTHER_CASE, "mother_reference_only": True, "experimental_credit": False, "physical_condition_credit": 0, "acceptance_threshold": None, "retime": False, "comparison_label_policy": "Report physical initial-depth difference and separate output-sampling difference explicitly; differences are diagnostic and do not define acceptance.", "lineage_group_id": "F1_official_v54_mdbc_dambreak3d_v1", "mother_owner_metadata": receipt_bindings["mother_owner"]},
        "immutable_source_policy": {"source_tree": "upstream_nas", "generated_xml_read_only": True, "m3_manifest_and_semantic_diff_read_only": True, "owner_metadata_immutable": True, "raw_solver_outputs_read_only": True, "receipts_read_only": True, "mother_reference_only": True},
        "output_contract": {"trajectory": "{attempt_root}/trajectory.h5", "report": "{attempt_root}/direct-conversion-report.json", "partvtk_validation_dir": "{attempt_root}/partvtk-validation", "direct_conversion_has_not_run": True, "direct_conversion_receipt": None, "all_saved_native_frames": True, "full_initial_typed_identity_axis": True, "source_mutation": False},
        "storage_reservation": {"output_storage": "upstream_nas", "attempt_root": str(paths["run"] / paths["direct_attempt"]), "direct_conversion_output_bytes": DIRECT_RESERVE, "direct_conversion_output_gib": 12, "enriched_copy_bytes_upper_bound": DIRECT_RESERVE, "new_bytes_upper_bound": 2 * DIRECT_RESERVE, "nas_scratch": "/data/nas/jade/Simulation/DualSPHysics/upstream-first/scratch", "scratch_bytes_outside_destination": 0, "scratch_policy": "NAS destination-side partial output only; no raw-frame staging or second scientific scratch copy"},
        "request_note": "Actual completed XML, GenCase, solver, native-integrity, and full 241-frame receipts are bound. Stream the immutable NAS native source through the frozen converter with canonical BI4 decoder/PartVTK; no retiming, no experimental credit, no acceptance threshold.",
    }
    _validate_candidate_v2(candidate, case, paths, gates, owner_info["binding"])
    _write_immutable(paths["candidate"], candidate)
    written = _load(paths["candidate"], "new direct-conversion candidate")
    return {"path": str(paths["candidate"]), "binding": _binding(paths["candidate"], "immutable direct-conversion candidate"), "record": written, "created": True}


def _validate_candidate(candidate: Mapping[str, Any], case: str, paths: Mapping[str, Path], gates: Mapping[str, Any], owner_binding: Mapping[str, Any]) -> None:
    for key, expected in (("case_id", case), ("attempt_id", paths["direct_attempt"])):
        if candidate.get(key) != expected:
            raise QueueError(f"direct candidate {key} mismatch for {case}")
    if candidate.get("candidate_only") is not True or candidate.get("submission_forbidden") is not True:
        raise QueueError(f"direct candidate is not immutable candidate-only state for {case}")
    actual = candidate.get("actual_completed_receipts")
    if not isinstance(actual, Mapping):
        raise QueueError(f"direct candidate has no actual receipt binding for {case}")
    expected_receipts = {"gencase": "gencase", "solver": "solver", "native_integrity": "native_integrity_receipt", "native_frame_scan": "native_frame_scan_receipt"}
    for candidate_key, gate_key in expected_receipts.items():
        item = actual.get(candidate_key)
        binding = gates[gate_key].get("binding")
        if not isinstance(item, Mapping) or not isinstance(binding, Mapping) or item.get("sha256") != binding.get("sha256"):
            raise QueueError(f"direct candidate does not bind current completed {candidate_key} receipt for {case}")
    xml = candidate.get("actual_generated_case_binding", {}).get("generated_xml") if isinstance(candidate.get("actual_generated_case_binding"), Mapping) else None
    if not isinstance(xml, Mapping) or xml.get("sha256") != gates["generated_xml"].get("sha256"):
        raise QueueError(f"direct candidate does not bind current generated XML for {case}")
    producer = candidate.get("m4_producer_binding")
    if not isinstance(producer, Mapping) or not isinstance(producer.get("owner_metadata_input"), Mapping) or producer["owner_metadata_input"].get("sha256") != owner_binding.get("sha256"):
        raise QueueError(f"direct candidate does not bind current owner metadata for {case}")
    files = candidate.get("input_files")
    required_inputs = (DECODER, PARTVTK, DS_CONFIG, CONVERTER, CONVERTER_V2)
    if not isinstance(files, list) or any(str(path) not in files for path in required_inputs):
        raise QueueError(f"direct candidate lacks canonical converter/decoder/PartVTK/DsphConfig inputs for {case}")


def _validate_candidate_v2(
    candidate: Mapping[str, Any],
    case: str,
    paths: Mapping[str, Path],
    gates: Mapping[str, Any],
    owner_binding: Mapping[str, Any],
) -> None:
    _validate_candidate(candidate, case, paths, gates, owner_binding)
    expected_command = _direct_command(case, paths)
    if candidate.get("command") != expected_command:
        raise QueueError(f"direct candidate command is not the exact bounded converter-v2 command for {case}")
    command = candidate.get("command")
    if not isinstance(command, list) or len(command) < 2 or command[1] != str(CONVERTER_V2):
        raise QueueError(f"direct candidate does not invoke converter v2 for {case}")
    input_files = candidate.get("input_files")
    bindings = candidate.get("input_file_bindings")
    if not isinstance(input_files, list) or not isinstance(bindings, Mapping):
        raise QueueError(f"direct candidate input_files/input_file_bindings are malformed for {case}")
    canonical = {
        CONVERTER: "base direct converter",
        CONVERTER_V2: "bounded-scratch direct converter v2",
        DECODER: "canonical BI4 decoder",
        PARTVTK: "canonical PartVTK",
        DS_CONFIG: "canonical DsphConfig",
    }
    for path, role in canonical.items():
        value = str(path.resolve())
        if value not in input_files:
            raise QueueError(f"direct candidate omits {role} input for {case}")
        binding = bindings.get(value)
        expected = _binding(path, role)
        if not isinstance(binding, Mapping) or binding.get("path") != expected["path"] or binding.get("bytes") != expected["bytes"] or binding.get("sha256") != expected["sha256"]:
            raise QueueError(f"direct candidate {role} binding is stale for {case}")
    expected_data = (paths["solver_receipt"].parent / "data").resolve()
    if candidate.get("deferred_source_root") != str(expected_data):
        raise QueueError(f"direct candidate native data root is not exact for {case}")
    small = gates.get("small_source_bindings")
    if not isinstance(small, Mapping):
        raise QueueError(f"direct candidate has no small-source binding map for {case}")
    for key, expected in small.items():
        if not isinstance(expected, Mapping) or expected.get("status") == "missing":
            raise QueueError(f"direct candidate source {key} is missing for {case}")
        path_value = expected.get("path")
        if not isinstance(path_value, str) or path_value not in input_files:
            raise QueueError(f"direct candidate omits actual source {key} for {case}")
        actual = bindings.get(path_value)
        hash_mismatch = "sha256" in expected and actual.get("sha256") != expected.get("sha256") if isinstance(actual, Mapping) else True
        if not isinstance(actual, Mapping) or actual.get("path") != expected.get("path") or actual.get("bytes") != expected.get("bytes") or hash_mismatch:
            raise QueueError(f"direct candidate actual source binding is stale for {case}: {key}")
    native = candidate.get("regular_native_solver_files")
    if not isinstance(native, Mapping) or not isinstance(native.get("files"), list):
        raise QueueError(f"direct candidate regular native solver file map is missing for {case}")
    native_rows = {row.get("path"): row for row in native["files"] if isinstance(row, Mapping)}
    for key in ("run_csv", "run_out", "run_parts_csv", "part_info", "part_out_000"):
        expected = small.get(key)
        if not isinstance(expected, Mapping) or expected.get("status") == "missing":
            raise QueueError(f"direct candidate regular native source {key} is missing for {case}")
        row = native_rows.get(expected.get("path"))
        hash_mismatch = "sha256" in expected and row.get("sha256") != expected.get("sha256") if isinstance(row, Mapping) else True
        if not isinstance(row, Mapping) or row.get("bytes") != expected.get("bytes") or hash_mismatch:
            raise QueueError(f"direct candidate regular native source binding is stale for {case}: {key}")


def _future_stage_inputs(case: str, paths: Mapping[str, Path], source: Mapping[str, Any], direct: Mapping[str, Any], static: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    solver_root = paths["solver_receipt"].parent
    common = [str(RUNTIME_V2), str(RUNTIME_V6), str(RUNTIME_V6_BATCH2), str(DS_CONFIG)]
    regular_native = [str(item["path"]) for item in source["native_files"]["files"]]
    post_evidence = [str(paths[key]) for key in ("xml", "owner", "integrity_report", "integrity_receipt", "frame_report", "frame_receipt", "manifest", "semantic_diff", "gencase_receipt", "solver_receipt")]
    direct_outputs = [str(paths["run"] / paths["direct_attempt"] / name) for name in ("trajectory.h5", "direct-conversion-report.json", "execution-receipt.json")]
    enrich_inputs = [str(PRODUCER), str(ADAPTER), *direct_outputs, *post_evidence, str(MOTHER_OWNER), *regular_native, *common]
    # Keep the list explicit: globbing product files before the stage runs would
    # bind stale or partial artifacts.
    portable_inputs = [str(ADAPTER), str(INTERFACE_SCHEMA), str(L2_READER), *common, str(paths["run"] / ENRICH_ATTEMPT / "execution-receipt.json"), str(paths["run"] / ENRICH_ATTEMPT / "product" / "owner-metadata.json"), str(paths["run"] / ENRICH_ATTEMPT / "product" / "geometry.json"), str(paths["run"] / ENRICH_ATTEMPT / "product" / "control.json"), str(paths["run"] / ENRICH_ATTEMPT / "product" / "enriched.h5"), str(paths["run"] / ENRICH_ATTEMPT / "product" / "interface.json"), str(paths["run"] / ENRICH_ATTEMPT / "product" / "enrichment-receipt.json"), *regular_native, *post_evidence]
    return list(dict.fromkeys(enrich_inputs)), list(dict.fromkeys(portable_inputs))


def _stage_specs(case: str, paths: Mapping[str, Path], source: Mapping[str, Any], direct: Mapping[str, Any], static: Mapping[str, Any]) -> dict[str, Any]:
    enrich_inputs, portable_inputs = _future_stage_inputs(case, paths, source, direct, static)
    solver_root = paths["solver_receipt"].parent
    return {
        "direct_conversion": {
            "attempt_id": paths["direct_attempt"], "request_path": str(paths["root_direct_request"]), "grant_path": str(paths["root_direct_grant"]),
            "candidate_path": direct["path"], "command": direct["record"]["command"], "root_request_reuse_policy": "reuse immutable H060 request/grant; H052/H058 may be materialized only by explicit root launch after gates",
        },
        "enrichment": {
            "attempt_id": ENRICH_ATTEMPT, "status": "candidate_only", "submission_forbidden": True, "root_review_required": True,
            "command": [str(PYTHON), str(PRODUCER), "enrich", "--trajectory", str(paths["run"] / paths["direct_attempt"] / "trajectory.h5"), "--report", str(paths["run"] / paths["direct_attempt"] / "direct-conversion-report.json"), "--generated-xml", str(paths["xml"]), "--owner-metadata", str(paths["owner"]), "--native-integrity", str(paths["integrity_report"]), "--frame-scan", str(paths["frame_report"]), "--case-manifest", str(paths["manifest"]), "--semantic-diff", str(paths["semantic_diff"]), "--output-dir", "{attempt_root}/product"],
            "input_files": enrich_inputs, "output_dir": str(paths["run"] / ENRICH_ATTEMPT / "product"), "estimated_storage_bytes": DIRECT_RESERVE, "estimated_temp_peak_bytes": TEMP_RESERVE,
            "qualification": "diagnostic full-state enrichment pending actual direct-conversion receipt; no credit or acceptance threshold",
        },
        "portable_build": {
            "attempt_id": PORTABLE_ATTEMPT, "status": "candidate_only", "submission_forbidden": True, "root_review_required": True,
            "command": [str(PYTHON), str(ADAPTER), "build", "--interface", str(paths["run"] / ENRICH_ATTEMPT / "product/interface.json"), "--output", "{attempt_root}/bundle"],
            "input_files": portable_inputs, "output_dir": str(paths["run"] / PORTABLE_ATTEMPT / "bundle"), "estimated_storage_bytes": DIRECT_RESERVE, "estimated_temp_peak_bytes": TEMP_RESERVE,
            "qualification": "diagnostic portable bundle pending completed enrichment receipt; no credit or acceptance threshold",
        },
        "relocation_queue": {
            "status": "root_launch_only", "root_launch_only": True, "queue_path": str(RELOCATION_QUEUE), "queue_binding": static["relocation_queue_v2"],
            "command": [str(PYTHON), str(RELOCATION_QUEUE), "--case", case], "depends_on": [ENRICH_ATTEMPT, PORTABLE_ATTEMPT],
            "note": "The v2 root queue owns relocation preparation, isolated replay, source-unchanged verification, and both semantic negatives through the shared batch-2 runner.",
        },
    }


def _build_plan(case: str, *, create_candidate: bool = True) -> dict[str, Any]:
    paths = _case_paths(case)
    owner_info = _prepare_owner(case, paths)
    owner = owner_info["record"]
    evidence = _validate_evidence(case, paths, owner)
    manifest = _load(paths["manifest"], "case manifest")
    metadata = _validate_owner_recipe(case, paths, owner, manifest)
    gates = _strict_source_gates(case, paths, owner, manifest)
    static = _static_bindings()
    direct = _build_direct_candidate(case, paths, owner_info, evidence, gates) if create_candidate else None
    if direct is None and gates["status"] == "ready" and paths["candidate"].is_file():
        candidate_record = _load(paths["candidate"], "direct-conversion candidate")
        direct = {"path": str(paths["candidate"]), "binding": _binding(paths["candidate"], "immutable direct-conversion candidate"), "record": candidate_record, "created": False}
    if direct is None:
        direct = {"path": str(paths["candidate"]), "binding": None, "record": {"command": _direct_command(case, paths)}, "created": False}
    source = {
        "gates": gates,
        "native_files": _native_files(paths),
        "bindings": _source_bindings(paths, gates, owner_info["binding"], evidence),
    }
    admission = _admission_binding()
    plan_status = "ready_for_root_review" if gates["status"] == "ready" and direct.get("binding") is not None else "blocked_actual_completed_sources"
    blockers = list(gates.get("blockers", []))
    if static["relocation_queue_v2"].get("status") == "pending_root_file":
        blockers.append("missing_root_relocation_queue_v2")
    return {
        "schema": "ds-data-02.m4.condition-product-queue-plan.v2",
        "status": plan_status,
        "case_id": case,
        "family_id": "F1",
        "created_by": str(SCRIPT),
        "helper_binding": _binding(SCRIPT, "generic condition product queue helper"),
        "launch_policy": {"auto_launch": False, "default_mode": "prepare_only", "root_launch_flag": "--launch", "root_confirmation_flag": "--root-launch-confirmation ROOT_APPROVED_M4_CONDITION_PIPELINE", "shared_runner": str(RUNTIME_V6_BATCH2), "batch_admission": admission, "no_heavy_scan_in_helper": True, "no_native_payload_hash_in_helper": True},
        "metadata_contract": metadata,
        "source": {"owner": owner_info["binding"], "evidence": evidence, "actual": source, "batch2_admission": admission},
        "direct_candidate": direct["binding"],
        "sequence": ["direct_conversion", "enrichment", "portable_build", "relocation_queue_v2"],
        "stages": _stage_specs(case, paths, source, direct, static),
        "static_inputs": static,
        "blockers": list(dict.fromkeys(blockers)),
        "scientific_scope": {"mother_reference_only": True, "all_conditions_same_development_lineage": True, "physical_depth_difference_label": "initial fill depth difference", "sampling_difference_label": "TimeOut=.025 versus mother .01; no retiming", "comparison_observations": ["H1", "H2", "H3", "H4", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"], "full_window_s": [0, 6], "full_frame_count": EXPECTED_FRAMES, "experimental_credit": False, "acceptance_threshold": None, "physical_condition_credit": 0},
        "root_review_notes": ["H060 direct request and grant are immutable root-owned files and must be reused without overwrite.", "H052/H058 do not become launchable from GenCase metadata alone; solver, native-integrity, and full 241-frame receipts must be completed and rebound first.", "Postprocess requests bind actual direct/enrichment receipts only when each preceding stage has completed.", "The relocation queue v2 is root-launch-only and must remain delegated to the shared batch-2 runner."],
    }


def _request_hash(path: Path) -> str:
    return _sha256(path)


def _load_grant(path: Path, request_path: Path) -> dict[str, Any]:
    grant = _load(path, "immutable batch grant")
    if grant.get("status") != "granted" or grant.get("immutable") is not True:
        raise QueueError(f"grant is not immutable/granted: {path}")
    if grant.get("request_path") != str(request_path):
        raise QueueError(f"grant request path mismatch: {path}")
    if grant.get("request_sha256") != _request_hash(request_path):
        raise QueueError(f"grant request hash mismatch: {path}")
    return grant


def _validate_root_direct(case: str, paths: Mapping[str, Path], candidate: Mapping[str, Any], *, require_grant: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    if not paths["root_direct_request"].is_file():
        raise QueueError(f"root direct request is absent for {case}; review candidate before explicit launch")
    request = _load(paths["root_direct_request"], "root direct request")
    if request.get("case_id") != case or request.get("attempt_id") != paths["direct_attempt"]:
        raise QueueError(f"root direct request case/attempt mismatch for {case}")
    if request.get("input_files") is None or str(paths["candidate"]) not in request["input_files"]:
        raise QueueError(f"root direct request does not bind this candidate for {case}")
    if request.get("command") != candidate.get("command"):
        raise QueueError(f"root direct request command differs from immutable candidate for {case}")
    grant = _load_grant(paths["root_direct_grant"], paths["root_direct_request"]) if require_grant else {}
    return request, grant


def _receipt_status(
    run: Path,
    attempt: str,
    *,
    case: str | None = None,
    request_path: Path | None = None,
) -> tuple[str, Path | None, dict[str, Any] | None]:
    """Read a stage receipt without allowing an unbound receipt to count.

    ``request_path`` is supplied for product stages.  A completed receipt for
    such a stage must bind the exact immutable request bytes.  Invalid JSON or
    an invalid binding is represented as ``invalid`` with a diagnostic object,
    so callers never dereference ``None`` while deciding whether to launch.
    """
    path = run / attempt / "execution-receipt.json"
    if not path.is_file() or path.is_symlink():
        return "absent", None, None
    try:
        receipt = _load(path, f"{attempt} execution receipt")
    except QueueError as exc:
        return "invalid", path, {"validation_error": str(exc)}
    expected_case = case if case is not None else run.name
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        return "invalid", path, {"validation_error": "unexpected_receipt_schema", "receipt": receipt}
    identity_error = _receipt_identity_error(receipt, expected_case, attempt)
    if identity_error is not None:
        return "invalid", path, {"validation_error": identity_error, "receipt": receipt}
    status = str(receipt.get("status", "unknown"))
    if status == "completed":
        if not _completed_returncode_is_zero(receipt):
            return "invalid", path, {"validation_error": "completed_returncode_not_zero", "receipt": receipt}
        if request_path is not None:
            try:
                request = _load(request_path, "root stage request")
            except QueueError as exc:
                return "invalid", path, {"validation_error": f"completed_request_invalid: {exc}", "receipt": receipt}
            request_sha256 = receipt.get("request_sha256")
            if not isinstance(request_sha256, str) or not request_sha256:
                return "invalid", path, {"validation_error": "missing_request_sha256", "receipt": receipt}
            expected_sha256 = _request_hash(request_path)
            if request_sha256 != expected_sha256:
                return "invalid", path, {"validation_error": "completed_request_hash_mismatch", "receipt": receipt}
            # Keep this lightweight check here; _require_completed_stage_binding
            # below performs the full request/grant validation before reuse.
            if request.get("case_id") != expected_case or request.get("attempt_id") != attempt:
                return "invalid", path, {"validation_error": "completed_request_case_or_attempt_mismatch", "receipt": receipt}
    return status, path, receipt


def _promote_candidate(case: str, paths: Mapping[str, Path], candidate: Mapping[str, Any]) -> tuple[Path, Path]:
    if paths["root_direct_request"].exists():
        _validate_root_direct(case, paths, candidate)
        return paths["root_direct_request"], paths["root_direct_grant"]
    request = copy.deepcopy(dict(candidate))
    request.update({"status": "root_authorized_actual_completed_source", "candidate_only": False, "submission_forbidden": False, "root_review_required": False, "no_launch_performed": True, "launch_authorization": "root explicit --launch; shared batch-2 runner only"})
    _write_immutable(paths["root_direct_request"], request)
    sys.path.insert(0, str(BASE / "batch2-runtime"))
    from grant_request import grant  # imported only in explicit launch mode
    grant_path = Path(grant(paths["root_direct_request"]))
    return paths["root_direct_request"], grant_path


def _run_shared(request_path: Path, grant_path: Path, *, summary_name: str) -> None:
    summary = BASE / "batch2-runtime" / summary_name
    if summary.exists() or summary.is_symlink():
        raise QueueError(f"refusing to overwrite runner summary: {summary}")
    command = [str(PYTHON), str(RUNTIME_V6_BATCH2), "run", "--request", str(request_path), "--batch-admission", str(ADMISSION), "--batch-grant", str(grant_path)]
    with summary.open("x", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, check=True)


def _materialize_post_request(case: str, paths: Mapping[str, Path], stage: str, source: Mapping[str, Any]) -> tuple[Path, Path]:
    if stage == "enrichment":
        attempt, command, inputs = ENRICH_ATTEMPT, _stage_specs(case, paths, source, source["direct"], source["static"])["enrichment"]["command"], _stage_specs(case, paths, source, source["direct"], source["static"])["enrichment"]["input_files"]
    elif stage == "portable_build":
        attempt, command, inputs = PORTABLE_ATTEMPT, _stage_specs(case, paths, source, source["direct"], source["static"])["portable_build"]["command"], _stage_specs(case, paths, source, source["direct"], source["static"])["portable_build"]["input_files"]
    else:
        raise QueueError(f"unsupported post stage: {stage}")
    request_path = BASE / "requests" / f"{case}-{attempt}.json"
    grant_path = BASE / "batch2-runtime/grants" / f"{case}-{attempt}.json"
    if request_path.exists():
        request = _load(request_path, f"existing {stage} request")
        if request.get("case_id") != case or request.get("attempt_id") != attempt:
            raise QueueError(f"existing {stage} request does not match case/attempt")
        if request.get("command") != command:
            raise QueueError(f"existing {stage} request command differs; refusing overwrite")
    else:
        request = {"schema": "ds-data-02.runner.request.v1", "status": "root_authorized_actual_completed_source", "family_id": "F1", "case_id": case, "attempt_id": attempt, "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 4, "max_wall_seconds": 3600, "estimated_storage_bytes": DIRECT_RESERVE, "estimated_temp_peak_bytes": TEMP_RESERVE, "output_storage": "upstream_nas", "cwd": str(ROOT), "worktree_root": str(ROOT), "command": command, "input_files": list(dict.fromkeys(inputs)), "source_bindings": source.get("bindings", {}), "qualification": "diagnostic full-state M4 pipeline; no credit or acceptance threshold"}
        _write_immutable(request_path, request)
    if not grant_path.exists():
        sys.path.insert(0, str(BASE / "batch2-runtime"))
        from grant_request import grant
        grant_path = Path(grant(request_path))
    _load_grant(grant_path, request_path)
    return request_path, grant_path


def _stage_request_paths(case: str, paths: Mapping[str, Path], stage: str) -> tuple[Path, Path]:
    if stage == "direct":
        return paths["root_direct_request"], paths["root_direct_grant"]
    attempt = {"enrichment": ENRICH_ATTEMPT, "portable_build": PORTABLE_ATTEMPT}.get(stage)
    if attempt is None:
        raise QueueError(f"unsupported stage for request binding: {stage}")
    return BASE / "requests" / f"{case}-{attempt}.json", BASE / "batch2-runtime/grants" / f"{case}-{attempt}.json"


def _require_completed_stage_binding(
    case: str,
    attempt: str,
    receipt: Mapping[str, Any] | None,
    request_path: Path,
    grant_path: Path,
) -> None:
    if not isinstance(receipt, Mapping):
        raise QueueError(f"{case}/{attempt} completed without a readable receipt")
    if receipt.get("status") != "completed" or not _completed_returncode_is_zero(receipt):
        raise QueueError(f"{case}/{attempt} completed binding has a nonzero return code")
    request = _load(request_path, f"completed {attempt} root request")
    if request.get("schema") != "ds-data-02.runner.request.v1":
        raise QueueError(f"completed {attempt} root request has an unexpected schema")
    if request.get("case_id") != case or request.get("attempt_id") != attempt:
        raise QueueError(f"completed {attempt} root request case/attempt mismatch")
    expected_sha256 = _request_hash(request_path)
    if receipt.get("request_sha256") != expected_sha256:
        raise QueueError(f"completed {attempt} receipt request hash mismatch")
    _load_grant(grant_path, request_path)


def _run_stage(case: str, paths: Mapping[str, Path], stage: str, source: Mapping[str, Any]) -> None:
    attempt = {"direct": paths["direct_attempt"], "enrichment": ENRICH_ATTEMPT, "portable_build": PORTABLE_ATTEMPT}[stage]
    request_path, grant_path = _stage_request_paths(case, paths, stage)
    status, receipt_path, receipt = _receipt_status(paths["run"], attempt, case=case, request_path=request_path)
    if status == "completed":
        _require_completed_stage_binding(case, attempt, receipt, request_path, grant_path)
        return
    if status not in {"absent"}:
        reason = receipt.get("validation_error") if isinstance(receipt, Mapping) else None
        detail = f": {reason}" if reason else ""
        raise QueueError(f"{case}/{attempt} is {status}{detail}; refusing duplicate or failed launch")
    if stage == "direct":
        request_path, grant_path = _promote_candidate(case, paths, source["direct"]["record"])
    else:
        request_path, grant_path = _materialize_post_request(case, paths, stage, source)
    _run_shared(request_path, grant_path, summary_name=f"{case}-{attempt}-runner-summary.json")
    final_status, _, final_receipt = _receipt_status(paths["run"], attempt, case=case, request_path=request_path)
    if final_status != "completed":
        reason = final_receipt.get("validation_error") if isinstance(final_receipt, Mapping) else None
        detail = f": {reason}" if reason else ""
        raise QueueError(f"{case}/{attempt} did not complete: {final_status}{detail}")
    _require_completed_stage_binding(case, attempt, final_receipt, request_path, grant_path)


def _launch(case: str, plan: Mapping[str, Any]) -> None:
    # Re-read all small receipts/reports immediately before any root write or
    # shared-runner call.  An older immutable plan may otherwise point at a
    # running/failed source receipt or an earlier direct-conversion attempt.
    current = _build_plan(case, create_candidate=True)
    for key in ("source", "direct_candidate", "static_inputs"):
        if plan.get(key) != current.get(key):
            raise QueueError(f"immutable plan is stale for {case}; pass a fresh --plan-output path")
    plan = current
    if plan.get("status") not in {"ready_for_root_review"}:
        raise QueueError(f"{case} is not launch-ready: {plan.get('blockers')}")
    if plan.get("static_inputs", {}).get("relocation_queue_v2", {}).get("status") == "pending_root_file":
        raise QueueError("root relocation queue v2 is not present")
    paths = _case_paths(case)
    direct = _load(paths["candidate"], "direct-conversion candidate")
    source = {"direct": {"record": direct, "path": str(paths["candidate"])}, "native_files": plan["source"]["actual"]["native_files"], "bindings": plan["source"]["actual"]["bindings"], "static": plan["static_inputs"]}
    _run_stage(case, paths, "direct", source)
    _run_stage(case, paths, "enrichment", source)
    _run_stage(case, paths, "portable_build", source)
    command = [str(PYTHON), str(RELOCATION_QUEUE), "--case", case]
    subprocess.run(command, cwd=ROOT, check=True)


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", choices=[_case_id(suffix) for suffix in CASE_SUFFIXES])
    group.add_argument("--all", action="store_true", help="prepare immutable plans for H052, H058, and H060")
    parser.add_argument("--plan-output", type=Path, help="fresh immutable v2 plan path; default is m4-next-prepared/plans/<case>-product-queue-v2-001.plan.json")
    parser.add_argument("--launch", action="store_true", help="explicitly launch through shared batch-2 runner; absent by default")
    parser.add_argument("--root-launch-confirmation", help="must equal ROOT_APPROVED_M4_CONDITION_PIPELINE with --launch")
    return parser.parse_args(argv)


def _fresh_plan_path(case: str) -> Path:
    plans = PREP / "plans"
    index = 1
    while True:
        candidate = plans / f"{case}-product-queue-v2-{index:03d}.plan.json"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        index += 1


def _owned_plan_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    try:
        path.relative_to(PREP.resolve())
    except ValueError as exc:
        raise QueueError(f"plan output must remain under m4-next-prepared: {path}") from exc
    return path


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.launch and args.root_launch_confirmation != "ROOT_APPROVED_M4_CONDITION_PIPELINE":
        raise QueueError("--launch requires --root-launch-confirmation ROOT_APPROVED_M4_CONDITION_PIPELINE")
    cases = [_case_id(suffix) for suffix in CASE_SUFFIXES] if args.all else [args.case]
    if args.launch and len(cases) != 1:
        raise QueueError("--launch requires one --case")
    for case in cases:
        default_plan = _fresh_plan_path(case)
        output = _owned_plan_path(args.plan_output if len(cases) == 1 and args.plan_output else default_plan)
        if args.launch:
            if output.is_file():
                plan = _load(output, "existing immutable condition plan")
            else:
                plan = _build_plan(case, create_candidate=True)
                _write_immutable(output, plan)
            _launch(case, plan)
            print(json.dumps({"case_id": case, "status": "completed_pipeline_and_relocation_queue"}, sort_keys=True))
            continue
        plan = _build_plan(case, create_candidate=True)
        _write_immutable(output, plan)
        print(json.dumps({"case_id": case, "status": plan["status"], "plan": str(output), "blockers": plan["blockers"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QueueError as exc:
        print(f"condition product queue rejected: {exc}", file=sys.stderr)
        raise SystemExit(2)
