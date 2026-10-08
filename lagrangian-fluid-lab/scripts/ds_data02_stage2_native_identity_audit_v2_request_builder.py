#!/usr/bin/env python3
"""Build the source-bound all-118 native identity V2 contract.

The builder consumes the already completed all-118 impact ledger and CURRENT
catalog plus the small source products named by each impact row.  It derives
the one raw ``PartOut_000.obi4`` path from each completed decoder receipt, but
does not open that binary or any trajectory/frame file.  The resulting
manifest and request are immutable forward inputs for
``ds_data02_stage2_native_identity_audit_v2.py``.

The F2-S1 historical partial case intentionally remains in the manifest with
its missing typed-conversion sources.  It is an explicit case-scoped source
gap, not silently dropped and not credited by the V2 worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "ds02.stage2.native-identity-audit-manifest.v2"
REQUEST_SCHEMA = "ds02.stage2.native-identity-audit-request.v2"
REQUIRED_SOURCE_KEYS = (
    "scan", "scan_receipt", "native_csv", "runparts", "decoder_receipt",
    "raw_partout", "conversion_report", "solver_receipt", "gencase_receipt",
    "xml", "partvtk_binary",
)
SCIENTIFIC_NAMES = ("trajectory.h5",)
_HASH_CACHE: dict[str, tuple[int, int, str]] = {}


class NativeIdentityBuilderError(ValueError):
    """Raised when the completed source catalog cannot form a strict contract."""


def sha256(path: Path) -> str:
    path = Path(path).resolve()
    stat = path.stat()
    cached = _HASH_CACHE.get(str(path))
    if cached is not None and cached[:2] == (stat.st_size, stat.st_mtime_ns):
        return cached[2]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    _HASH_CACHE[str(path)] = (stat.st_size, stat.st_mtime_ns, value)
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeIdentityBuilderError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NativeIdentityBuilderError(f"{label} is not a JSON object: {path}")
    return value


def _binding(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise NativeIdentityBuilderError(f"{label} is missing: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def _optional_binding(value: Any, label: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return None, "missing_manifest_reference"
    path = Path(value["path"]).expanduser().resolve()
    if not path.is_file():
        return {"path": str(path), "sha256": value.get("sha256"), "bytes": value.get("bytes")}, "source_file_missing"
    actual = _binding(path, label)
    declared = value.get("sha256")
    if isinstance(declared, str) and declared != actual["sha256"]:
        actual["declared_sha256"] = declared
        return actual, "source_digest_differs_from_impact"
    return actual, None


def _decoder_raw_partout(decoder_path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Derive the exact raw PartOut input without reading its bytes."""
    decoder = _json(decoder_path, label)
    inputs = decoder.get("request", {}).get("input_files", [])
    if not isinstance(inputs, list):
        return None, ["decoder_request_input_files_missing"]
    scientific = []
    for value in inputs:
        name = Path(str(value)).name
        if name in SCIENTIFIC_NAMES or (name.startswith("Part_") and name.endswith(".bi4")):
            scientific.append(str(value))
    if scientific:
        return None, ["decoder_receipt_binds_scientific_trajectory_or_part_frame"]
    raw = [Path(str(value)).expanduser().resolve() for value in inputs if Path(str(value)).name == "PartOut_000.obi4"]
    if len(raw) != 1:
        return None, ["decoder_receipt_does_not_bind_exactly_one_raw_partout"]
    return _binding(raw[0], f"{label} raw PartOut"), []


def _case_manifest_row(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("evidence_bindings", {})
    full = evidence.get("full_probe_sources", {})
    if not isinstance(full, dict):
        raise NativeIdentityBuilderError(f"{row.get('case_key')} lacks full_probe_sources")
    refs: dict[str, Any] = {}
    missing: list[dict[str, str]] = []
    binding_diffs: list[str] = []
    for key in REQUIRED_SOURCE_KEYS:
        if key == "raw_partout":
            continue
        value, error = _optional_binding(full.get(key), f"{row.get('case_key')} {key}")
        if value is not None:
            refs[key] = value
        if error:
            missing.append({"key": key, "reason": error})
            if error == "source_digest_differs_from_impact":
                binding_diffs.append(key)
    decoder_ref = refs.get("decoder_receipt")
    if isinstance(decoder_ref, dict) and Path(str(decoder_ref.get("path", ""))).is_file():
        raw, errors = _decoder_raw_partout(Path(decoder_ref["path"]), f"{row.get('case_key')} decoder")
        if raw is not None:
            refs["raw_partout"] = raw
        for error in errors:
            missing.append({"key": "raw_partout", "reason": error})
    else:
        missing.append({"key": "raw_partout", "reason": "decoder_receipt_unavailable"})
    conversion_count: int | None = None
    conversion_ref = refs.get("conversion_report")
    if isinstance(conversion_ref, dict) and Path(str(conversion_ref.get("path", ""))).is_file():
        conversion = _json(Path(conversion_ref["path"]), f"{row.get('case_key')} conversion report")
        ledger = conversion.get("typed_identity", {}).get("initial_exclusion_ledger", {})
        if isinstance(ledger, dict) and isinstance(ledger.get("count"), (int, float)):
            conversion_count = int(ledger["count"])
        else:
            missing.append({"key": "conversion_report", "reason": "initial_exclusion_ledger_missing"})
    else:
        missing.append({"key": "conversion_report", "reason": "conversion_report_unavailable"})
    known = evidence.get("f2_s1_native_closure")
    if isinstance(known, dict):
        value, error = _optional_binding(known, f"{row.get('case_key')} native closure")
        if value is not None:
            refs["native_identity_closure"] = value
        if error:
            missing.append({"key": "native_identity_closure", "reason": error})
    cause = row.get("native_numerical_cause", {})
    source_status = "CLOSED_INPUTS" if not missing else "SOURCE_INCOMPLETE"
    return {
        "case_key": row.get("case_key"),
        "family_id": row.get("family_id"),
        "physical_case_id": row.get("physical_case_id"),
        "expected_native_motive": cause.get("motive"),
        "expected_native_count": cause.get("native_count"),
        "expected_initial_conversion_exclusion_count": conversion_count,
        "source_status": source_status,
        "missing_source_keys": missing,
        "binding_diffs": binding_diffs,
        "source_refs": refs,
    }


def _reject_scientific_path(path: str) -> None:
    name = Path(path).name
    if name in SCIENTIFIC_NAMES or (name.startswith("Part_") and name.endswith(".bi4")):
        raise NativeIdentityBuilderError(f"request would bind forbidden scientific content: {path}")


def _make_manifest(impact_path: Path, current_path: Path, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    impact = _json(impact_path, "all118 impact report")
    current = _json(current_path, "CURRENT336")
    cases = impact.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise NativeIdentityBuilderError("all118 impact report must contain exactly 118 cases")
    current_pairs = {(row.get("family_id"), row.get("physical_case_id")) for row in current.get("cases", [])}
    rows = [_case_manifest_row(row) for row in cases]
    bad_identity = [row["case_key"] for row in rows if (row["family_id"], row["physical_case_id"]) not in current_pairs]
    if bad_identity:
        raise NativeIdentityBuilderError(f"CURRENT lacks exact physical identities: {bad_identity[:3]}")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "audit_id": "STAGE2_NATIVE_IDENTITY_AUDIT_V2",
        "expected_case_count": 118,
        "impact_report": _binding(impact_path, "all118 impact report"),
        "current": _binding(current_path, "CURRENT336"),
        "cases": rows,
        "source_policy": {
            "reuse_only": "completed native PartOut CSV, RunPARTs, scientific-scan JSON/receipt, conversion report, decoder receipt, solver/gencase receipt, XML, official binary and raw PartOut hash",
            "trajectory_h5_content_read": False,
            "part_frames_content_read": False,
            "decoder_started": False,
            "solver_started": False,
            "physical_fate_credit": False,
        },
    }
    manifest_path = output_dir / "native-identity-audit-v2-manifest.json"
    _atomic_json(manifest_path, manifest)
    return manifest_path, manifest


def _make_request(manifest_path: Path, manifest: dict[str, Any], output_dir: Path, attempt_id: str) -> Path:
    repo = Path(__file__).resolve().parents[1]
    worker = repo / "scripts" / "ds_data02_stage2_native_identity_audit_v2.py"
    v1 = repo / "scripts" / "ds_data02_stage2_native_identity_audit_v1.py"
    runtime = [
        repo / "scripts" / "ds_data02_runtime_v4.py",
        repo / "scripts" / "ds_data02_stage2_dispatch_v4.py",
        repo / "scripts" / "ds_data02_strict_dispatch_v4.py",
    ]
    builder = Path(__file__).resolve()
    interpreter = Path("/usr/bin/python3.10")
    paths: dict[str, Path] = {}
    for path in [worker, v1, builder, *runtime, interpreter, manifest_path]:
        paths[str(path.resolve())] = path.resolve()
    for case in manifest["cases"]:
        for value in case.get("source_refs", {}).values():
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                path = Path(value["path"]).expanduser().resolve()
                if path.is_file():
                    _reject_scientific_path(str(path))
                    paths[str(path)] = path
    ordered = sorted(paths.values(), key=str)
    bindings = {str(path): _binding(path, "request input") for path in ordered}
    input_bytes = sum(int(value["bytes"]) for value in bindings.values())
    raw_bytes = sum(int(value["bytes"]) for path, value in bindings.items() if Path(path).name == "PartOut_000.obi4")
    incomplete = [case["case_key"] for case in manifest["cases"] if case.get("source_status") != "CLOSED_INPUTS"]
    command = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        str(worker), "--manifest", str(manifest_path), "--output", "{attempt_root}/native-identity-audit-v2.json",
    ]
    request = {
        "schema": REQUEST_SCHEMA,
        "attempt_id": attempt_id,
        "case_id": "STAGE2_NATIVE_IDENTITY_AUDIT_V2",
        "family_id": "infra",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 4 * 1024 * 1024,
        "cwd": str(repo),
        "command": command,
        "input_files": [str(path) for path in ordered],
        "input_sha256": {str(path): value["sha256"] for path, value in bindings.items()},
        "source_cost": {
            "input_count": len(ordered), "input_bytes": input_bytes,
            "raw_partout_hash_bytes": raw_bytes,
            "estimated_output_bytes": 4 * 1024 * 1024,
            "trajectory_h5_content_read": False, "part_frames_content_read": False,
            "decoder_started": False, "solver_started": False,
        },
        "source_closure": {
            "requested_case_count": 118,
            "manifest_closed_input_case_count": 118 - len(incomplete),
            "manifest_source_incomplete_cases": incomplete,
            "native_identity_credit_requires_case_status": "NATIVE_IDENTITY_SOURCE_CLOSED",
        },
        "request_note": "Forward all-118 native identity/MK/type audit using completed small PartOut CSV, RunPARTs, scan/conversion/decoder receipts and typed conversion reports. One F2-S1 historical case has no typed decoder source and remains case-scoped UNKNOWN. No H5/Part_*.bi4 content, decoder, solver, CFD, legal-flux or fate credit.",
        "worktree_root": str(Path(__file__).resolve().parents[2]),
    }
    request_path = output_dir / "native-identity-audit-v2-request.json"
    _atomic_json(request_path, request)
    return request_path


def build(impact_report: Path, current: Path, output_dir: Path, attempt_id: str) -> tuple[Path, Path]:
    impact_report = Path(impact_report).expanduser().resolve()
    current = Path(current).expanduser().resolve()
    if not impact_report.is_file() or not current.is_file():
        raise NativeIdentityBuilderError("impact report and CURRENT must be existing files")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path, manifest = _make_manifest(impact_report, current, output_dir)
    request_path = _make_request(manifest_path, manifest, output_dir, attempt_id)
    return manifest_path, request_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impact-report", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    manifest, request = build(args.impact_report, args.current, args.output_dir, args.attempt_id)
    print(json.dumps({"manifest": str(manifest), "request": str(request)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
