#!/usr/bin/env python3
"""Build a forward Stage2 coverage snapshot with mutable batch inputs removed.

The consumed coverage-v2, native-join-manifest-v1, and native-impact-prep-v1
outputs are immutable evidence files.  This worker reads those JSON files and
does not open H5, rerun a scan, launch a decoder, or inspect the two mutable
F3/F5 science batch receipts that were present in the old native-join request.
The output retains the exact F2/F4/F6 118-case identity and evidence rows,
while making the excluded input boundary explicit.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.omission-coverage-index.v3"
FAMILIES = ("F2", "F4", "F6")
EXPECTED_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
EXCLUDED_LIVE_BATCHES = (
    {
        "path": "/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/batches/stage2-F3-science-v4-001/batch-receipt.json",
        "previously_bound_sha256": "aea04efeafea98e0d10d08d7a51898504a0b6a65552c73a28055a9b99a90d843",
        "reason": "mutable live F3 science batch receipt; not needed by finalized F2/F4/F6 coverage",
    },
    {
        "path": "/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/batches/stage2-F5-science-v4-001/batch-receipt.json",
        "previously_bound_sha256": "78b28f4a813d87f2336b93a26ca288a9815d530735fede237b8e782987d8aa88",
        "reason": "mutable live F5 science batch receipt; not needed by finalized F2/F4/F6 coverage",
    },
)


class CoverageForwardError(RuntimeError):
    """Raised when a finalized evidence boundary cannot be established."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path).expanduser().resolve()
    if not value.is_file():
        raise CoverageForwardError(f"{label} is missing: {value}")
    return value


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    value = require_file(path, label)
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - evidence error path
        raise CoverageForwardError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CoverageForwardError(f"{label} is not a JSON object: {value}")
    return value, payload


def file_ref(path: str | Path, expected_sha256: str | None, label: str) -> dict[str, Any]:
    value = require_file(path, label)
    actual = sha256(value)
    if expected_sha256 is not None and actual != str(expected_sha256):
        raise CoverageForwardError(
            f"{label} hash differs: {value}; expected {expected_sha256}, got {actual}")
    return {"path": str(value), "sha256": actual, "bytes": value.stat().st_size}


def git_commit() -> str | None:
    try:
        repo = Path(__file__).resolve().parents[2]
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


def index_rows(rows: Any, label: str, expected_counts: dict[str, int]) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise CoverageForwardError(f"{label} rows are not a list")
    result: dict[str, dict[str, Any]] = {}
    counts = {family: 0 for family in FAMILIES}
    for row in rows:
        if not isinstance(row, dict):
            raise CoverageForwardError(f"{label} has a non-object row")
        physical_id = str(row.get("physical_case_id", ""))
        family = str(row.get("family_id", ""))
        if not physical_id or physical_id in result:
            raise CoverageForwardError(f"{label} has duplicate/missing physical_case_id: {physical_id}")
        if family not in FAMILIES:
            raise CoverageForwardError(f"{label} contains unsupported family {family}: {physical_id}")
        result[physical_id] = row
        counts[family] += 1
    if counts != expected_counts:
        raise CoverageForwardError(f"{label} family counts {counts} != {expected_counts}")
    return result


def assert_no_excluded_paths(value: Any, label: str) -> None:
    forbidden = tuple(item["path"] for item in EXCLUDED_LIVE_BATCHES)
    if isinstance(value, dict):
        for child in value.values():
            assert_no_excluded_paths(child, label)
    elif isinstance(value, list):
        for child in value:
            assert_no_excluded_paths(child, label)
    elif isinstance(value, str) and value in forbidden:
        raise CoverageForwardError(f"{label} still contains excluded mutable batch input: {value}")


def validate_join_batches(join: dict[str, Any]) -> list[dict[str, Any]]:
    refs = join.get("batch_receipts")
    if not isinstance(refs, list) or not refs:
        raise CoverageForwardError("native join manifest has no batch receipts")
    rows: list[dict[str, Any]] = []
    for entry in refs:
        if not isinstance(entry, dict):
            raise CoverageForwardError("native join batch receipt entry is not an object")
        batch_path = file_ref(entry.get("path", ""), entry.get("sha256"), "native join batch receipt")
        batch = json.loads(Path(batch_path["path"]).read_text(encoding="utf-8"))
        requests = batch.get("requests", [])
        if not isinstance(requests, list):
            raise CoverageForwardError(f"native join batch requests are not a list: {batch_path['path']}")
        for request in requests:
            identity = str(request.get("identity", ""))
            family = identity.split("/", 1)[0] if identity else ""
            if family not in FAMILIES:
                raise CoverageForwardError(f"native join batch contains non-final family {identity}")
            rows.append({"identity": identity, "batch_receipt": batch_path})
    assert_no_excluded_paths(rows, "native join batch snapshot")
    return rows


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build(args: argparse.Namespace) -> dict[str, Any]:
    coverage_path, coverage = read_json(args.coverage_v2, "consumed coverage-v2")
    join_path, join = read_json(args.join_manifest, "finalized native join manifest")
    impact_path, impact = read_json(args.impact_prep, "finalized native impact preparation")
    if coverage.get("schema") != "ds02.stage2.omission-coverage-index.v2":
        raise CoverageForwardError("coverage input must be consumed v2")
    if join.get("schema") != "ds02.stage2.native-join-manifest.v1":
        raise CoverageForwardError("native join input must be v1")
    if impact.get("schema") != "ds02.stage2.native-impact-preparation.v1":
        raise CoverageForwardError("impact input must be v1")
    coverage_rows = index_rows(coverage.get("rows"), "coverage-v2", EXPECTED_COUNTS)
    join_rows = index_rows(join.get("rows"), "native join manifest", {
        "F2": 0, "F4": 19, "F6": 46})
    impact_rows = index_rows(impact.get("rows"), "native impact preparation", EXPECTED_COUNTS)
    if len(coverage_rows) != 118 or len(impact_rows) != 118:
        raise CoverageForwardError("coverage and impact inputs must both contain exact 118 rows")
    if not isinstance(impact.get("source_coverage"), dict) or impact["source_coverage"].get("path") != str(coverage_path):
        raise CoverageForwardError("impact preparation is not bound to this coverage-v2 path")
    if impact["source_coverage"].get("sha256") != sha256(coverage_path):
        raise CoverageForwardError("impact preparation coverage-v2 digest differs")
    if not isinstance(impact.get("source_join_manifest"), dict) or impact["source_join_manifest"].get("path") != str(join_path):
        raise CoverageForwardError("impact preparation is not bound to this native join manifest path")
    if impact["source_join_manifest"].get("sha256") != sha256(join_path):
        raise CoverageForwardError("impact preparation native join digest differs")
    batch_snapshot = validate_join_batches(join)
    if len(batch_snapshot) != 65:
        raise CoverageForwardError(f"native join finalized batch rows {len(batch_snapshot)} != 65")
    assert_no_excluded_paths(coverage, "coverage-v2 output")
    assert_no_excluded_paths(join, "native join manifest output")
    assert_no_excluded_paths(impact, "native impact preparation output")

    rows: list[dict[str, Any]] = []
    for physical_id, base_row in coverage_rows.items():
        row = copy.deepcopy(base_row)
        row["forward_v3"] = {
            "source_scope": "finalized_F2_F4_F6_only",
            "native_join_manifest_row": copy.deepcopy(join_rows.get(physical_id)),
            "native_impact_preparation_row": copy.deepcopy(impact_rows[physical_id]),
        }
        rows.append(row)
    rows.sort(key=lambda row: (row["family_id"], row["physical_case_id"]))

    source_refs = [
        file_ref(coverage_path, sha256(coverage_path), "consumed coverage-v2"),
        file_ref(join_path, sha256(join_path), "finalized native join manifest"),
        file_ref(impact_path, sha256(impact_path), "finalized native impact preparation"),
    ]
    return {
        "schema": SCHEMA,
        "purpose": (
            "Forward source-bound coverage for the exact historical 118 F2/F4/F6 cases; "
            "consumed v2, finalized native join evidence, and impact preparation are "
            "carried forward without opening H5 or consuming mutable F3/F5 batch receipts."),
        "generator": {
            "script": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve())},
            "git_commit": git_commit(),
            "trajectory_h5_opened": False,
            "scientific_scan_reexecuted": False,
            "native_decoder_reexecuted": False,
        },
        "source_scope": {
            "families": list(FAMILIES),
            "historical_118_rows": len(rows),
            "family_counts": EXPECTED_COUNTS,
            "source_inputs": source_refs,
            "native_join_finalized_batch_rows": len(batch_snapshot),
            "old_union_input_count": 2266,
            "excluded_input_count": len(EXCLUDED_LIVE_BATCHES),
            "forward_input_count_before_new_generator": 2264,
            "excluded_mutable_live_batch_receipts": list(EXCLUDED_LIVE_BATCHES),
            "exclusion_policy": (
                "These two live science batch receipts are deliberately not opened, "
                "hashed, or used for v3 coverage; only finalized F2/F4/F6 evidence or "
                "the immutable JSON snapshots above is in scope."),
        },
        "prior_consumed_artifacts": {
            "coverage_v2": source_refs[0],
            "native_join_manifest_v1": source_refs[1],
            "native_impact_preparation_v1": source_refs[2],
        },
        "interpretation": {
            "native_cause": "Existing native joins are carried as evidence only; physical fate and dynamics remain UNKNOWN.",
            "f6_mass_semantics": "Typed fluid mass is separate from XML 128 kg rigid-body mass and 256 kg floating sample mass.",
            "qualification": "No QN/QE/full-qualification/dynamics credit.",
        },
        "source_policy": {
            "h5_opened": False,
            "particle_frames_read": False,
            "scientific_scan_reexecuted": False,
            "native_decoder_reexecuted": False,
            "solver_launched": False,
            "cfd_or_model_run": False,
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-v2", required=True, type=Path)
    parser.add_argument("--join-manifest", required=True, type=Path)
    parser.add_argument("--impact-prep", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build(args)
        write_atomic(args.output, result)
    except CoverageForwardError as exc:
        raise SystemExit(f"CoverageForwardError: {exc}")
    print(json.dumps({
        "status": "completed",
        "output": str(args.output.resolve()),
        "schema": result["schema"],
        "historical_rows": result["source_scope"]["historical_118_rows"],
        "forward_input_count_before_new_generator": result["source_scope"]["forward_input_count_before_new_generator"],
        "excluded_input_count": result["source_scope"]["excluded_input_count"],
        "h5_opened": result["source_policy"]["h5_opened"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
