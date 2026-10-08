#!/usr/bin/env python3
"""Recover only completed F3 conversion phase evidence after a failed parent run.

The F3 native-to-typed worker completed its converter and exact typed/current
comparison, but the parent request was marked failed when its 5400 second
wall deadline elapsed during finalization.  This additive verifier binds that
failed receipt, the converter and compare reports, the exact CURRENT row, the
typed HDF5, and the native raw tree.  It may grant a *phase credit* when those
immutable artifacts still agree.  It never edits or upgrades the failed
receipt, re-runs the decoder, opens BI4 frames, runs a solver, or invokes a
family label operator.

``build-request`` is metadata/stat-only and does not read HDF5 or raw-file
contents.  ``run --io-slot-approved`` streams the already-produced typed HDF5
for a full SHA and hashes the native raw tree before and after.  The latter is
an integrity check, not a reconstruction.  The output is a new small JSON
report under a new namespace; no old output is copied, renamed, or replaced.
All scientific qualification remains UNKNOWN.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import time
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
LAB = SCRIPT.parents[1]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_FAILED_RECEIPT = DATA_ROOT / (
    "families/F3/STAGE2_F3_FULL836_RAW_ANCHOR_TYPED_COMPARE_V2/"
    "f3-full836-raw-anchor-typed-compare-v2-root-v8-001/execution-receipt.json"
)
DEFAULT_OUTPUT = LAB / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "f3-finalization-recovery-v1/f3-s1-finalization-recovery-request-v1-001.json"
)
SCHEMA = "ds02.stage2.f3-finalization-recovery-request.v1"
REPORT_SCHEMA = "ds02.stage2.f3-finalization-recovery-report.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = frozenset("0123456789abcdef")
CHUNK = 4 * 1024 * 1024


class RecoveryError(RuntimeError):
    """Raised when the immutable phase evidence is not safe to verify."""


def _canonical(value: Any) -> str:
    body = ({key: item for key, item in value.items() if key != "sha256"}
            if isinstance(value, Mapping) else value)
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str,
    ).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    target = Path(path).expanduser().resolve()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise RecoveryError(f"JSON object required: {target}")
    return value


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise RecoveryError(f"{role} must be a lowercase SHA-256")
    return value


def _stat(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        info = target.stat()
    except OSError as error:
        raise RecoveryError(f"cannot stat {target}: {error}") from error
    return {
        "path": str(target),
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "inode": int(info.st_ino),
        "device": int(info.st_dev),
    }


def _same_stat(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    # ctime is intentionally not included: a read does not promise ctime
    # stability on every filesystem.  Size, mtime, inode, and device are the
    # source identity fields used by this recovery contract.
    return all(before.get(key) == after.get(key)
               for key in ("bytes", "mtime_ns", "inode", "device"))


def _tree_manifest(root: Path) -> dict[str, Any]:
    """Use the converter's exact path-list/content hash definition."""
    target = root.expanduser().resolve()
    if not target.is_dir():
        raise RecoveryError(f"raw source root is not a directory: {target}")
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in target.rglob("*") if item.is_file()):
        files.append({
            "path": path.relative_to(target).as_posix(),
            "bytes": int(path.stat().st_size),
            "sha256": sha256_file(path),
        })
    return {
        "root": str(target),
        "file_count": len(files),
        "files": files,
        "tree_sha256": _canonical(files),
        "total_bytes": sum(int(item["bytes"]) for item in files),
    }


def _tree_stat(root: Path) -> dict[str, Any]:
    """Metadata-only estimate; unlike ``_tree_manifest`` it reads no content."""
    target = root.expanduser().resolve()
    if not target.is_dir():
        raise RecoveryError(f"raw source root is not a directory: {target}")
    files = [item for item in target.rglob("*") if item.is_file()]
    return {
        "root": str(target),
        "file_count": len(files),
        "total_bytes": sum(int(item.stat().st_size) for item in files),
    }


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise RecoveryError(f"refusing to overwrite existing recovery output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _file_binding(path: Path, expected: str, role: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise RecoveryError(f"bound {role} is missing: {target}")
    return {"role": role, "path": str(target), "sha256": _require_sha(expected, role),
            "stat": _stat(target), "content_hash_status": "BOUND_EXPECTED_NOT_READ_AT_BUILD"}


def _find_current_row(catalog: Mapping[str, Any], trajectory_path: Path,
                      expected_sha: str) -> dict[str, Any]:
    cases = catalog.get("cases")
    if not isinstance(cases, list):
        raise RecoveryError("CURRENT catalog cases list is missing")
    target = trajectory_path.expanduser().resolve()
    matches: list[Mapping[str, Any]] = []
    for row in cases:
        if not isinstance(row, Mapping):
            continue
        trajectory = row.get("trajectory")
        if not isinstance(trajectory, Mapping):
            continue
        if Path(str(trajectory.get("path", ""))).expanduser().resolve() == target:
            matches.append(row)
    if len(matches) != 1:
        raise RecoveryError(f"CURRENT trajectory must select exactly one row, found {len(matches)}")
    row = dict(matches[0])
    trajectory = row.get("trajectory")
    if not isinstance(trajectory, Mapping) or trajectory.get("producer_declared_sha256") != expected_sha:
        raise RecoveryError("CURRENT trajectory producer SHA differs from failed run/report")
    if row.get("family_id") != "F3":
        raise RecoveryError("CURRENT row family is not F3")
    return row


def _validate_reports(converter: Mapping[str, Any], compare: Mapping[str, Any],
                      typed_path: Path, expected_sha: str,
                      reference_path: Path) -> dict[str, Any]:
    if converter.get("conversion_status") != "completed":
        raise RecoveryError("converter report does not state completed conversion")
    if converter.get("output_sha256") != expected_sha:
        raise RecoveryError("converter output SHA differs from expected typed SHA")
    if Path(str(converter.get("output_hdf5", ""))).expanduser().resolve() != typed_path.resolve():
        raise RecoveryError("converter output path differs from failed typed output")
    comparison = converter.get("reference_hdf5_comparison")
    if not isinstance(comparison, Mapping) or comparison.get("passed") is not True:
        raise RecoveryError("converter exact reference comparison is not passed")
    if Path(str(comparison.get("reference", ""))).expanduser().resolve() != reference_path.resolve():
        raise RecoveryError("converter comparison reference differs from CURRENT trajectory")
    if compare.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise RecoveryError("typed compare report does not retain development UNKNOWN status")
    typed = compare.get("typed_output")
    if not isinstance(typed, Mapping) or typed.get("sha256") != expected_sha:
        raise RecoveryError("typed compare report SHA differs from expected typed SHA")
    compare_result = compare.get("typed_full_current_compare")
    if not isinstance(compare_result, Mapping) or compare_result.get("passed") is not True:
        raise RecoveryError("typed compare report exact comparison is not passed")
    labels = compare.get("labels")
    if not isinstance(labels, Mapping) or labels.get("status") != "PENDING_FAMILY_SPECIFIC_OPERATOR":
        raise RecoveryError("typed compare report labels are not explicitly pending")
    return {
        "converter_status": converter.get("conversion_status"),
        "converter_comparison_passed": True,
        "typed_compare_status": compare.get("status"),
        "typed_compare_passed": True,
        "family_labels_status": labels.get("status"),
        "qualification": dict(UNKNOWN),
    }


def _failed_binding(failed_receipt_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    receipt = load_json(failed_receipt_path)
    if receipt.get("status") != "failed":
        raise RecoveryError("original receipt is not failed; recovery cannot replace a successful run")
    termination = str(receipt.get("termination", ""))
    deadline = receipt.get("deadline")
    deadline_exceeded = isinstance(deadline, Mapping) and str(deadline.get("status", "")).upper() == "EXCEEDED"
    if not deadline_exceeded and "deadline" not in termination.lower() and "exceeded" not in termination.lower():
        raise RecoveryError("failed receipt is not the known deadline-exceeded F3 attempt")
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        raise RecoveryError("failed receipt does not contain its immutable request")
    input_hashes = request.get("input_hashes")
    input_files = request.get("input_files")
    if not isinstance(input_hashes, Mapping) or not isinstance(input_files, list):
        raise RecoveryError("failed request lacks input hash closure")
    reference_candidates = [Path(str(path)).expanduser().resolve() for path in input_files
                            if str(path).endswith("trajectory.h5")]
    if len(reference_candidates) != 1:
        raise RecoveryError("failed request must bind exactly one trajectory HDF5")
    expected = input_hashes.get(str(reference_candidates[0]))
    expected_sha = _require_sha(expected, "failed trajectory SHA")
    return receipt, dict(request), reference_candidates[0], expected_sha


def build_request(*, failed_receipt: Path | str = DEFAULT_FAILED_RECEIPT,
                  output: Path | str = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Create a metadata-only recovery request from the immutable failed run."""
    receipt_path = Path(failed_receipt).expanduser().resolve()
    receipt, old_request, reference_path, typed_sha = _failed_binding(receipt_path)
    termination = str(receipt.get("termination", ""))
    if not reference_path.is_file():
        raise RecoveryError(f"CURRENT reference HDF5 is missing: {reference_path}")
    current_path = next((Path(str(item)).expanduser().resolve()
                         for item in old_request["input_files"]
                         if Path(str(item)).name == "CURRENT336.json"), None)
    if current_path is None or not current_path.is_file():
        raise RecoveryError("failed request does not bind CURRENT336.json")
    catalog = load_json(current_path)
    current_row = _find_current_row(catalog, reference_path, typed_sha)
    converter_path = Path(str(receipt_path.parent / "reconstruction/raw-converter-report.json"))
    compare_path = Path(str(receipt_path.parent / "reconstruction/raw-to-typed-compare-report.json"))
    if not converter_path.is_file() or not compare_path.is_file():
        raise RecoveryError("completed converter/compare reports are missing")
    converter = load_json(converter_path)
    compare = load_json(compare_path)
    typed_path = Path(str(converter.get("output_hdf5", ""))).expanduser().resolve()
    if not typed_path.is_file():
        raise RecoveryError(f"completed typed output is missing: {typed_path}")
    report_semantics = _validate_reports(converter, compare, typed_path, typed_sha, reference_path)
    raw = converter.get("source_provenance", {}).get("raw_tree", {})
    if not isinstance(raw, Mapping):
        raise RecoveryError("converter report lacks raw-tree provenance")
    raw_root = Path(str(converter.get("source_provenance", {}).get("data_root", ""))).expanduser().resolve()
    expected_tree = _require_sha(raw.get("before_tree_sha256"), "raw before tree SHA")
    if raw.get("after_tree_sha256") != expected_tree or raw.get("unchanged") is not True:
        raise RecoveryError("failed converter raw tree was not unchanged")
    raw_stat = _tree_stat(raw_root)
    expected_count = int(raw.get("before_file_count", -1))
    if raw_stat["file_count"] != expected_count:
        raise RecoveryError("raw tree file count differs from converter evidence")
    input_bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_value in old_request["input_files"]:
        path = Path(str(path_value)).expanduser().resolve()
        key = str(path)
        if key in seen or key == str(reference_path):
            continue
        expected = old_request["input_hashes"].get(str(path_value))
        if expected is None:
            expected = old_request["input_hashes"].get(key)
        if expected is None:
            raise RecoveryError(f"failed request has no hash for {path}")
        input_bindings.append(_file_binding(path, str(expected), "failed_input"))
        seen.add(key)
    # Bind the new verifier and immutable recovery evidence explicitly.  The
    # failed receipt itself is outside the old request's input list.
    for path, role in ((receipt_path, "original_failed_receipt"),
                       (converter_path, "completed_converter_report"),
                       (compare_path, "completed_typed_compare_report"),
                       (current_path, "CURRENT336_catalog")):
        key = str(path.resolve())
        if key not in seen:
            input_bindings.append(_file_binding(path, sha256_file(path), role))
            seen.add(key)
    if str(SCRIPT) not in seen:
        input_bindings.append(_file_binding(SCRIPT, sha256_file(SCRIPT), "recovery_verifier"))
        seen.add(str(SCRIPT))
    output_path = Path(output).expanduser().resolve()
    if output_path.exists():
        raise RecoveryError(f"recovery output already exists: {output_path}")
    h5_stat = _stat(typed_path)
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "request_id": "f3-full836-finalization-recovery-v1-001",
        "status": "READY_FOR_PARENT_IO_SLOT",
        "role": "DEVELOPMENT_PHASE_RECOVERY_ONLY",
        "family_id": "F3",
        "case_id": old_request.get("case_id", "STAGE2_F3_FULL836_RAW_ANCHOR_TYPED_COMPARE_V2"),
        "qualification": dict(UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
        "original_failed_receipt": {
            "path": str(receipt_path),
            "sha256": sha256_file(receipt_path),
            "status": receipt.get("status"),
            "termination": termination,
            "deadline_status": receipt.get("deadline", receipt.get("execution", {}).get("deadline")),
            "never_upgrade": True,
        },
        "typed_output": {
            "path": str(typed_path),
            "expected_sha256": typed_sha,
            "expected_bytes": h5_stat["bytes"],
            "producer_report_output_sha256": converter.get("output_sha256"),
            "CURRENT_producer_declared_sha256": current_row["trajectory"]["producer_declared_sha256"],
            "content_hash_at_build": False,
        },
        "CURRENT_binding": {
            "catalog_path": str(current_path),
            "catalog_sha256": sha256_file(current_path),
            "trajectory_row": {
                "family_id": current_row.get("family_id"),
                "physical_case_id": current_row.get("physical_case_id"),
                "runtime_case_alias": current_row.get("runtime_case_alias"),
                "trajectory_path": str(reference_path),
                "producer_declared_sha256": current_row["trajectory"]["producer_declared_sha256"],
                "frames": current_row.get("frames"),
                "particles": current_row.get("particles"),
            },
        },
        "completed_phase_evidence": {
            "converter_report": {"path": str(converter_path), "sha256": sha256_file(converter_path)},
            "typed_compare_report": {"path": str(compare_path), "sha256": sha256_file(compare_path)},
            **report_semantics,
            "raw_tree": {
                "root": str(raw_root),
                "expected_tree_sha256": expected_tree,
                "expected_file_count": expected_count,
                "metadata_only_build_stat": raw_stat,
                "content_hash_at_build": False,
            },
        },
        "source_files": input_bindings,
        "execution": {
            "entrypoint": str(SCRIPT),
            "command": ["<venv-python>", str(SCRIPT), "run", "--request", "<request>",
                         "--output", "<new-report>", "--io-slot-approved"],
            "raw_bi4_redecode": False,
            "solver_or_cfd": False,
            "typed_hdf5_operation": "stream whole-file SHA only; no h5py dataset reads",
            "family_label_operator": False,
            "old_output_mutation": False,
        },
        "resource_request": {
            "cpu_threads": 1,
            "max_wall_seconds": 5400,
            "max_rss_bytes": 5 * 1024**3,
            "estimated_content_read_bytes": int(h5_stat["bytes"] + raw_stat["total_bytes"]),
            "estimated_typed_hdf5_read_bytes": int(h5_stat["bytes"]),
            "estimated_raw_tree_read_bytes": int(raw_stat["total_bytes"]),
            "new_storage_budget_bytes": 64 * 1024**2,
            "read_scope": "one typed-HDF5 stream plus one raw-tree pre/post integrity pass; no decoder/solver",
        },
        "source_hashes_preverified_by_parent": False,
        "limitations": [
            "This verifies immutable converter/typed comparison evidence and current source identity; it does not re-run conversion.",
            "A successful recovery report grants only PHASE_CREDIT_DEVELOPMENT_UNKNOWN, never full replay completion.",
            "Family-specific labels, scientific quality, recovery equivalence, QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = _canonical(request)
    _write_new(output_path, request)
    return request


def _validate_request(request_path: Path | str) -> dict[str, Any]:
    path = Path(request_path).expanduser().resolve()
    request = load_json(path)
    if request.get("schema") != SCHEMA or request.get("sha256") != _canonical(request):
        raise RecoveryError("recovery request is noncanonical")
    if request.get("status") != "READY_FOR_PARENT_IO_SLOT":
        raise RecoveryError("recovery request is not parent-slot ready")
    if request.get("role") != "DEVELOPMENT_PHASE_RECOVERY_ONLY":
        raise RecoveryError("recovery role is not phase-only")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise RecoveryError("model/CFD invocation must remain false")
    if request.get("qualification") != UNKNOWN:
        raise RecoveryError("qualification must remain UNKNOWN")
    failed = request.get("original_failed_receipt")
    typed = request.get("typed_output")
    current = request.get("CURRENT_binding")
    evidence = request.get("completed_phase_evidence")
    if not all(isinstance(item, Mapping) for item in (failed, typed, current, evidence)):
        raise RecoveryError("recovery source bindings are incomplete")
    return request


def _verify_static_bindings(request: Mapping[str, Any]) -> dict[str, Any]:
    for item in request.get("source_files", []):
        if not isinstance(item, Mapping):
            raise RecoveryError("source_files contains malformed binding")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        expected = _require_sha(item.get("sha256"), f"source_files {path}")
        if sha256_file(path) != expected:
            raise RecoveryError(f"source input content changed: {path}")
    failed_path = Path(str(request["original_failed_receipt"]["path"])).expanduser().resolve()
    failed = load_json(failed_path)
    if sha256_file(failed_path) != request["original_failed_receipt"]["sha256"]:
        raise RecoveryError("original failed receipt changed")
    if failed.get("status") != "failed":
        raise RecoveryError("original failed receipt status changed")
    typed = request["typed_output"]
    typed_path = Path(str(typed["path"])).expanduser().resolve()
    expected_h5 = _require_sha(typed.get("expected_sha256"), "typed output expected SHA")
    before_stat = _stat(typed_path)
    if before_stat["bytes"] != int(typed["expected_bytes"]):
        raise RecoveryError("typed output byte count differs before content verification")
    current = request["CURRENT_binding"]
    catalog_path = Path(str(current["catalog_path"])).expanduser().resolve()
    catalog = load_json(catalog_path)
    row_binding = current.get("trajectory_row")
    if not isinstance(row_binding, Mapping):
        raise RecoveryError("CURRENT trajectory row binding is missing")
    reference_path = Path(str(row_binding.get("trajectory_path", ""))).expanduser().resolve()
    row = _find_current_row(catalog, reference_path, expected_h5)
    expected_catalog_sha = _require_sha(current.get("catalog_sha256"), "CURRENT catalog SHA")
    if sha256_file(catalog_path) != expected_catalog_sha:
        raise RecoveryError("CURRENT catalog content changed")
    if row_binding.get("physical_case_id") != row.get("physical_case_id"):
        raise RecoveryError("CURRENT physical case identity differs")
    return {"failed_receipt": failed, "typed_path": typed_path,
            "expected_h5_sha": expected_h5, "typed_stat_before": before_stat,
            "catalog": catalog, "current_row": row}


def _verify_typed_content(path: Path, expected_sha: str,
                          expected_bytes: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    before = _stat(path)
    if before["bytes"] != int(expected_bytes):
        raise RecoveryError("typed output byte count differs before content verification")
    actual = sha256_file(path)
    after = _stat(path)
    if actual != expected_sha:
        raise RecoveryError("typed HDF5 content SHA differs from immutable producer/CURRENT SHA")
    if not _same_stat(before, after):
        raise RecoveryError("typed HDF5 stat changed during recovery stream")
    return actual, before, after


def _verify_raw_tree(root: Path, expected_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    before = _tree_manifest(root)
    if before["tree_sha256"] != expected_sha:
        raise RecoveryError("native raw tree before hash differs from converter evidence")
    after = _tree_manifest(root)
    if after["tree_sha256"] != before["tree_sha256"] or after["files"] != before["files"]:
        raise RecoveryError("native raw tree changed during recovery integrity pass")
    return before, after


def run(request_path: Path | str, output: Path | str, *, io_slot_approved: bool = False) -> dict[str, Any]:
    if not io_slot_approved:
        raise RecoveryError("full recovery content verification requires --io-slot-approved")
    request_file = Path(request_path).expanduser().resolve()
    request = _validate_request(request_file)
    output_path = Path(output).expanduser().resolve()
    if output_path.exists():
        raise RecoveryError(f"refusing existing recovery report: {output_path}")
    started = time.monotonic()
    cpu_start = resource.getrusage(resource.RUSAGE_SELF)
    static = _verify_static_bindings(request)
    typed_path: Path = static["typed_path"]
    expected_h5: str = static["expected_h5_sha"]
    typed_sha, typed_before, typed_after = _verify_typed_content(
        typed_path, expected_h5, int(request["typed_output"]["expected_bytes"])
    )
    raw = request["completed_phase_evidence"]["raw_tree"]
    raw_root = Path(str(raw["root"])).expanduser().resolve()
    tree_before, tree_after = _verify_raw_tree(raw_root, raw["expected_tree_sha256"])
    elapsed = time.monotonic() - started
    cpu_end = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (cpu_end.ru_utime + cpu_end.ru_stime) - (cpu_start.ru_utime + cpu_start.ru_stime)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "RECOVERED_PHASE_CREDIT_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "original_failed_receipt": {
            "path": request["original_failed_receipt"]["path"],
            "sha256": request["original_failed_receipt"]["sha256"],
            "status": static["failed_receipt"].get("status"),
            "preserved": True,
            "full_replay_status": "NOT_RECOVERED",
        },
        "phase_credit": {
            "typed_content_verified": True,
            "typed_hdf5_sha256": typed_sha,
            "typed_hdf5_stat_before": typed_before,
            "typed_hdf5_stat_after": typed_after,
            "native_raw_tree_before": {"tree_sha256": tree_before["tree_sha256"], "file_count": tree_before["file_count"], "total_bytes": tree_before["total_bytes"]},
            "native_raw_tree_after": {"tree_sha256": tree_after["tree_sha256"], "file_count": tree_after["file_count"], "total_bytes": tree_after["total_bytes"]},
            "converter_and_compare_reports_reused": True,
            "decoder_reinvoked": False,
            "family_labels_invoked": False,
        },
        "CURRENT_binding": request["CURRENT_binding"],
        "execution_boundary": {
            "raw_bi4_opened": False,
            "raw_tree_files_streamed_for_integrity": True,
            "typed_hdf5_opened_as_bytes": True,
            "hdf5_dataset_read": False,
            "converter_invoked": False,
            "solver_invoked": False,
            "model_invoked": False,
            "family_labels_invoked": False,
        },
        "resource": {
            "wall_seconds": elapsed,
            "self_cpu_seconds": max(0.0, cpu),
            "content_read_scope": "typed HDF5 SHA plus two native raw-tree manifests",
        },
        "qualification": dict(UNKNOWN),
        "limitations": [
            "This is phase-credit recovery only; the original deadline-exceeded receipt remains failed.",
            "No family-specific labels or scientific QI/QN/QE credit is issued.",
        ],
    }
    _write_new(output_path, report)
    return report


def prepare(request_path: Path | str) -> dict[str, Any]:
    request = _validate_request(request_path)
    return {
        "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(Path(request_path).expanduser().resolve()), "sha256": sha256_file(request_path)},
        "typed_hdf5_opened": False,
        "raw_tree_content_read": False,
        "estimated_content_read_bytes": request["resource_request"]["estimated_content_read_bytes"],
        "qualification": dict(UNKNOWN),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--failed-receipt", type=Path, default=DEFAULT_FAILED_RECEIPT)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    prep = sub.add_parser("prepare")
    prep.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "build-request":
        value = build_request(failed_receipt=args.failed_receipt, output=args.output)
        print(json.dumps({"status": value["status"], "path": str(args.output.resolve()),
                          "sha256": sha256_file(args.output)}, sort_keys=True))
    elif args.command == "prepare":
        print(json.dumps(prepare(args.request), sort_keys=True))
    else:
        value = run(args.request, args.output, io_slot_approved=args.io_slot_approved)
        print(json.dumps({"status": value["status"], "path": str(args.output.resolve()),
                          "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
