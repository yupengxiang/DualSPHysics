#!/usr/bin/env python3
"""Emit a source-bound correction for the consumed ROOT159 edge aliases.

ROOT159 is immutable evidence.  Its ``ROOT138_STREAM`` row accidentally points
at the ROOT130 solver/control proof even though the actual ROOT138 stream has a
separate terminal proof.  This JSON-only worker verifies the two source roles,
the ROOT142 per-ID motive edge, and the historical ROOT133/ROOT140 terminal
relationships.  It writes a new sidecar; it never edits or recreates ROOT159,
and it never opens H5, BI4, OBI4, VTK, or solver output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.full-goal-rollup.edge-link-correction.v1"
MANIFEST_SCHEMA = "ds02.stage2.full-goal-rollup.edge-link-correction.manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}


class EdgeCorrectionError(ValueError):
    """Raised when an immutable source role or edge cannot be proved."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EdgeCorrectionError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EdgeCorrectionError(f"{label} must be a JSON object: {path}")
    return value


def expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise EdgeCorrectionError(f"{label}: expected {expected!r}, got {actual!r}")


def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest = read_json(path.resolve(), "edge-link manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    raw_refs = manifest.get("source_refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        raise EdgeCorrectionError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    values: dict[str, dict[str, Any]] = {}
    for ref in raw_refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("key"), str):
            raise EdgeCorrectionError("malformed source reference")
        key = ref["key"]
        if key in paths:
            raise EdgeCorrectionError(f"duplicate source key: {key}")
        raw_path = ref.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise EdgeCorrectionError(f"{key} path is missing")
        target = Path(raw_path).expanduser()
        if not target.is_absolute() or not target.is_file():
            raise EdgeCorrectionError(f"{key} path is not an existing absolute file: {target}")
        if target.suffix.lower() in FORBIDDEN_SUFFIXES or target.suffix.lower() != ".json":
            raise EdgeCorrectionError(f"{key} is not an allowed JSON source: {target}")
        actual_sha = sha256_file(target)
        expect(ref.get("sha256"), actual_sha, f"{key} SHA")
        paths[key] = target
        values[key] = read_json(target, key)
    return manifest, paths, values


def bind_proof_source(
    proof: dict[str, Any],
    *,
    proof_key: str,
    paths: dict[str, Path],
    values: dict[str, dict[str, Any]],
    expected_schema: str,
    expected_status: str,
    report_key: str | None = None,
    receipt_key: str | None = None,
    request_key: str | None = None,
) -> dict[str, Any]:
    expect(proof.get("schema"), expected_schema, f"{proof_key} schema")
    expect(proof.get("status"), expected_status, f"{proof_key} status")
    if report_key is not None:
        target = paths[report_key]
        expect(proof.get("report"), str(target), f"{proof_key} report path")
        expect(proof.get("report_sha256"), sha256_file(target), f"{proof_key} report SHA")
    if receipt_key is not None:
        target = paths[receipt_key]
        expect(proof.get("receipt"), str(target), f"{proof_key} receipt path")
        expect(proof.get("receipt_sha256"), sha256_file(target), f"{proof_key} receipt SHA")
        expect(values[receipt_key].get("status"), "completed", f"{proof_key} receipt status")
    if request_key is not None:
        target = paths[request_key]
        expect(proof.get("request"), str(target), f"{proof_key} request path")
        expect(proof.get("request_sha256"), sha256_file(target), f"{proof_key} request SHA")
    qualification = proof.get("scientific_qualification", proof.get("qualification"))
    if isinstance(qualification, dict):
        for key in ("QI", "QN", "QE"):
            if key in qualification:
                expect(qualification[key], "UNKNOWN", f"{proof_key} {key}")
    return {
        "proof_key": proof_key,
        "path": str(paths[proof_key]),
        "sha256": sha256_file(paths[proof_key]),
        "schema": proof["schema"],
        "status": proof["status"],
        "request": proof.get("request"),
        "receipt": proof.get("receipt"),
        "report": proof.get("report"),
        "scientific_qualification": qualification,
    }


def edge(report: dict[str, Any], edge_id: str) -> dict[str, Any]:
    groups = report.get("evidence_edges")
    if not isinstance(groups, dict):
        raise EdgeCorrectionError("ROOT159 report evidence_edges is not an object")
    for group_name in ("completed_diagnostics", "failed_attempts", "pending_or_nonterminal"):
        group = groups.get(group_name, [])
        if isinstance(group, list):
            for item in group:
                if isinstance(item, dict) and item.get("edge_id") == edge_id:
                    return item
    raise EdgeCorrectionError(f"ROOT159 edge is missing: {edge_id}")


def source_path(edge_value: dict[str, Any], label: str) -> tuple[str, str]:
    source = edge_value.get("source")
    if not isinstance(source, dict):
        raise EdgeCorrectionError(f"{label} source is missing")
    path = source.get("path")
    digest = source.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str):
        raise EdgeCorrectionError(f"{label} source path/SHA is incomplete")
    return path, digest


def build(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, paths, values = load_manifest(manifest_path)
    root159 = values["root159_proof"]
    root159_report = values["root159_report"]
    root159_info = bind_proof_source(
        root159,
        proof_key="root159_proof",
        paths=paths,
        values=values,
        expected_schema="ds02.stage2.root-actual-verification.v1",
        expected_status="VERIFIED_ACTUAL_FULL_GOAL_ADDITIVE_ROLLUP_WITH_REMAINING_SOURCE_ROLE_LIMIT",
        report_key="root159_report",
        receipt_key="root159_receipt",
        request_key="root159_request",
    )
    expect(root159_report.get("schema"), "ds02.stage2.full-goal-rollup.v155", "ROOT159 report schema")
    expect(root159_report.get("status"), "ACTUAL_EVIDENCE_BOUND_FULL_GOAL_ROLLUP_NO_SCIENTIFIC_QUALIFICATION", "ROOT159 report status")
    expect(root159_report.get("scope_separation", {}).get("original_current336_cases"), 336, "ROOT159 CURRENT count")
    expect(root159_report.get("scope_separation", {}).get("original_native_omission_cases"), 118, "ROOT159 omission count")
    expect(root159_report.get("scope_separation", {}).get("original_native_identity_count"), 1328, "ROOT159 identity count")

    root138_info = bind_proof_source(
        values["root138_stream_proof"],
        proof_key="root138_stream_proof",
        paths=paths,
        values=values,
        expected_schema="ds02.stage2.root-actual-verification.v1",
        expected_status="VERIFIED_ACTUAL_401_NATIVE_DOMAIN_CONTROL_FIELDS_IDENTITIES_SCREEN_ONLY_PASS",
        report_key="root138_stream_report",
        receipt_key="root138_stream_receipt",
        request_key="root138_stream_request",
    )
    root130_info = bind_proof_source(
        values["root130_solver_proof"],
        proof_key="root130_solver_proof",
        paths=paths,
        values=values,
        expected_schema="ds02.stage2.root-actual-external-solver-verification.v1",
        expected_status="VERIFIED_ACTUAL_NUMERICAL_DOMAIN_CONTROL_NATIVE_OUTPUTS_NO_SCIENTIFIC_Q",
        request_key="root130_solver_request",
    )
    root142_info = bind_proof_source(
        values["root142_motives_proof"],
        proof_key="root142_motives_proof",
        paths=paths,
        values=values,
        expected_schema="ds02.stage2.root-actual-verification.v1",
        expected_status="VERIFIED_ACTUAL_F2_67_NATIVE_PER_ID_POSITION_MOTIVES_AND_SAVED_BRACKETS",
        report_key="root142_motives_report",
        receipt_key="root142_motives_receipt",
        request_key="root142_motives_request",
    )

    root133 = values["root133_historical_proof"]
    root140 = values["root140_historical_proof"]
    root150 = values["root150_observer_proof"]
    root145 = values["root145_failure_proof"]
    expect(root133.get("status"), "MANAGED_LAUNCH_REQUESTED_NOT_TERMINAL", "ROOT133 historical status")
    expect(root140.get("status"), "ACTUAL_RUNNING_NOT_TERMINAL", "ROOT140 historical status")
    expect(root150.get("status"), "VERIFIED_ACTUAL_F3_ALL836_NATIVE_FIELDS_IDENTITIES_AND_HEADER_DIAGNOSTICS", "ROOT150 status")
    expect(root145.get("status"), "ACTUAL_COPIED_WORKER_CANONICAL_FILENAME_MISSING_NO_CONVERSION_PRODUCT", "ROOT145 status")

    old_root138 = edge(root159_report, "ROOT138_STREAM")
    old_root142 = edge(root159_report, "ROOT142_MOTIVES")
    old_root133 = edge(root159_report, "ROOT133")
    old_root140 = edge(root159_report, "ROOT140")
    old138_path, old138_sha = source_path(old_root138, "ROOT138_STREAM")
    old142_path, old142_sha = source_path(old_root142, "ROOT142_MOTIVES")
    expect(old138_path, str(paths["root130_solver_proof"]), "ROOT159 stale ROOT138 source path")
    expect(old138_sha, sha256_file(paths["root130_solver_proof"]), "ROOT159 stale ROOT138 source SHA")
    expect(old142_path, str(paths["root142_motives_proof"]), "ROOT159 ROOT142 source path")
    expect(old142_sha, sha256_file(paths["root142_motives_proof"]), "ROOT159 ROOT142 source SHA")
    expect(old_root133.get("superseded_by"), "ROOT150", "ROOT133 historical supersession")
    expect(old_root140.get("superseded_by"), "ROOT145", "ROOT140 historical supersession")
    graph_edges = root159_report.get("task_graph", {}).get("edges", [])
    graph = {(item.get("from"), item.get("to")): item for item in graph_edges if isinstance(item, dict)}
    expect(graph.get(("ROOT138", "ROOT142"), {}).get("kind"), "stream_identity_to_per_id_motive_join", "ROOT138/ROOT142 graph edge")
    expect(graph.get(("ROOT133", "ROOT150"), {}).get("kind"), "historical_launch_superseded_by_actual_terminal", "ROOT133/ROOT150 graph edge")
    expect(graph.get(("ROOT140", "ROOT145"), {}).get("kind"), "historical_source_closure_attempt_superseded_by_later_terminal_failure", "ROOT140/ROOT145 graph edge")

    return {
        "schema": SCHEMA,
        "status": "CORRECTED_EDGE_LINKS_SOURCE_BOUND_NO_NEW_SCIENCE",
        "purpose": "Correct ROOT159 source-role aliasing without editing or rerunning the consumed ROOT159 rollup.",
        "root159_baseline": {
            "proof": root159_info,
            "report": {"path": str(paths["root159_report"]), "sha256": sha256_file(paths["root159_report"])},
            "receipt": {"path": str(paths["root159_receipt"]), "sha256": sha256_file(paths["root159_receipt"])},
            "report_status": root159_report["status"],
            "immutable": True,
        },
        "corrected_edges": {
            "ROOT138_STREAM": {
                "kind": "actual_completed_diagnostic",
                "prior_root159_source": {"path": old138_path, "sha256": old138_sha, "role": "ROOT130 solver/control proof incorrectly used as ROOT138 source"},
                "corrected_source": root138_info,
                "role": "F2 ROOT138 actual 401-frame stream proof; aggregate domain-control/identity screen only",
                "ROOT130_solver_control_is_separate": True,
                "scientific_credit": "NONE",
                "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
            },
            "ROOT130_SOLVER_CONTROL": {
                "kind": "actual_completed_diagnostic",
                "source": root130_info,
                "role": "F2 ROOT130 numerical-domain solver/control proof; not ROOT138 stream source",
                "scientific_credit": "NONE",
                "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
            },
            "ROOT142_MOTIVES": {
                "kind": "actual_completed_diagnostic",
                "source": root142_info,
                "role": "F2 ROOT142 official PartOut per-ID motive/saved-bracket diagnostic, joined to ROOT138 IDs",
                "identity_join_parent": "ROOT138_STREAM",
                "source_remains_distinct": True,
                "scientific_credit": "NONE",
                "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
            },
        },
        "historical_edges": {
            "ROOT133": {
                "historical_source": {"path": str(paths["root133_historical_proof"]), "sha256": sha256_file(paths["root133_historical_proof"])},
                "superseded_by": "ROOT150",
                "terminal_source": {"path": str(paths["root150_observer_proof"]), "sha256": sha256_file(paths["root150_observer_proof"])},
                "same_attempt": False,
                "same_case_lineage": True,
                "scientific_credit": "NONE",
            },
            "ROOT140": {
                "historical_source": {"path": str(paths["root140_historical_proof"]), "sha256": sha256_file(paths["root140_historical_proof"])},
                "superseded_by": "ROOT145",
                "terminal_source": {"path": str(paths["root145_failure_proof"]), "sha256": sha256_file(paths["root145_failure_proof"])},
                "same_attempt": False,
                "same_case_lineage": True,
                "scientific_credit": "NONE",
            },
            "ROOT150": {"role": "distinct actual F3 full836 observer stream", "scientific_credit": "NONE", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "ROOT145": {"role": "distinct actual F2 V55 failure/fee closure", "scientific_credit": "NONE", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "scope_preservation": {
            "original_current336_cases": 336,
            "original_native_omission_cases": 118,
            "original_native_identity_count": 1328,
            "new_reference_cases_merged": False,
            "root159_report_edited": False,
            "arrays_or_solver_read": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
        },
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise EdgeCorrectionError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_json(args.output, build(args.manifest, args.output))
    except EdgeCorrectionError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
