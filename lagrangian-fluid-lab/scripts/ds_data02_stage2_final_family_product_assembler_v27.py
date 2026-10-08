#!/usr/bin/env python3
"""Assemble the source-closed seven-family Stage2 delivery product.

This is a forward-only product assembler.  It consumes the actual v25 parent
report, evidence manifest, receipt, and independent proof, rather than the
actor-prepared v25 copies used by earlier catalog requests.  The CURRENT336
path is part of the producer identity: a byte-equivalent copy is rejected.

The assembler reads JSON/XML/receipt/proof metadata only.  It does not open
trajectory H5, materialized-label H5, BI4, PartOut, solver output, or start a
solver.  The resulting cards support source/owner/control metadata,
source-role mass bookkeeping, saved-frame artifact diagnostics, and the
already source-closed 118-case native alias index.  Physical fate, legal
flux, continuous event truth, dynamics, recovery transfer, effective split
safety, QN, QE, and QI remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
FAMILIES = [f"F{i}" for i in range(1, 8)]
ANCHOR_INDICES = {"F1": 0, "F2": 78, "F3": 96, "F4": 144, "F5": 192, "F6": 240, "F7": 288}
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
V25_SCHEMA = "ds02.stage2.source-closed-development-split.v25"
V25_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
RAW_STATE_SCHEMA = "ds02.stage2.seven-raw-anchor-actual-state.v1"
RAW_INDEX_SCHEMA = "ds02.stage2.family-native-raw-anchor-index.v1"
QUALITY_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
PRODUCT_SCHEMA = "ds02.stage2.final-family-product.v27"
MANIFEST_SCHEMA = "ds02.stage2.final-family-product-manifest.v27"


class ProductError(RuntimeError):
    """Raised when a source identity or scope invariant is open."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _path(value: Path | str, label: str) -> Path:
    if isinstance(value, Path):
        path = value.expanduser()
    elif isinstance(value, str) and value:
        path = Path(value).expanduser()
    else:
        raise ProductError(f"{label} must be a non-empty path")
    if not path.is_absolute():
        raise ProductError(f"{label} must be an absolute path: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ProductError(f"{label} is a forbidden scientific payload: {path}")
    if not path.is_file():
        raise ProductError(f"{label} is missing: {path}")
    return path


def _json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = _path(value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProductError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(data, dict):
        raise ProductError(f"{label} must be a JSON object: {path}")
    return path, data


def _ref(path: Path, role: str) -> dict[str, Any]:
    return {"role": role, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[2], check=True,
            capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _normalize_fresh_small_inputs(value: Any) -> list[dict[str, str]]:
    """Normalize the v25 proof's list or map representation without aliases.

    Historical proof writers used a list of ``{"path", "sha256"}`` objects;
    one forward test used a path-to-digest map.  Both are accepted as data
    representations, but the later exact-path check remains mandatory.
    """
    entries: list[dict[str, str]] = []

    def add(path: Any, digest: Any) -> None:
        if not isinstance(path, str) or not path or not isinstance(digest, str) or len(digest) != 64:
            raise ProductError("v25 fresh_small_inputs contains a malformed path/digest entry")
        entries.append({"path": path, "sha256": digest})

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                raise ProductError("v25 fresh_small_inputs list contains a non-object")
            add(item.get("path"), item.get("sha256"))
    elif isinstance(value, dict):
        if "path" in value or "sha256" in value:
            add(value.get("path"), value.get("sha256"))
        elif isinstance(value.get("entries"), list):
            return _normalize_fresh_small_inputs(value["entries"])
        else:
            for key, item in value.items():
                if isinstance(item, str):
                    add(key, item)
                elif isinstance(item, dict):
                    add(item.get("path", key), item.get("sha256"))
                else:
                    raise ProductError("v25 fresh_small_inputs map contains an unsupported value")
    else:
        raise ProductError("v25 fresh_small_inputs must be a list or object")

    if not entries:
        raise ProductError("v25 fresh_small_inputs is empty")
    seen: dict[str, str] = {}
    for item in entries:
        previous = seen.get(item["path"])
        if previous is not None and previous != item["sha256"]:
            raise ProductError(f"v25 fresh_small_inputs has conflicting digests for {item['path']}")
        seen[item["path"]] = item["sha256"]
    return entries


def _require_exact_path(actual: Any, expected: Path, label: str) -> None:
    if not isinstance(actual, str) or actual != str(expected):
        raise ProductError(f"{label} does not bind the exact producer path: {actual!r} != {str(expected)!r}")


def _require_sha(path: Path, declared: Any, label: str) -> str:
    actual = sha256_file(path)
    if declared != actual:
        raise ProductError(f"{label} digest mismatch: declared {declared!r}, actual {actual}")
    return actual


def _validate_current(path: Path, current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], tuple[int, dict[str, Any]]]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise ProductError("CURRENT336 schema is not current336.v1")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise ProductError("CURRENT336 must contain exactly 336 cases")
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    counts = {family: 0 for family in FAMILIES}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProductError(f"CURRENT336 row {index} is not an object")
        family, physical = row.get("family_id"), row.get("physical_case_id")
        if family not in FAMILIES or not isinstance(physical, str) or (family, physical) in by_key:
            raise ProductError(f"CURRENT336 identity is invalid at index {index}")
        window = row.get("actual_time_window_s")
        if not isinstance(window, list) or len(window) != 2 or not all(isinstance(x, (int, float)) for x in window):
            raise ProductError(f"CURRENT336 row {index} lacks an exact time window")
        bindings = row.get("source_bindings")
        if not isinstance(bindings, dict) or not bindings:
            raise ProductError(f"CURRENT336 row {index} lacks source bindings")
        counts[family] += 1
        by_key[(family, physical)] = (index, row)
    if counts != {family: 48 for family in FAMILIES}:
        raise ProductError(f"CURRENT336 family counts are not 48 each: {counts}")
    return rows, by_key


def _validate_actual_v25(
    current_path: Path,
    v25_proof_path: Path,
    v25_proof: dict[str, Any],
    v25_report_path: Path,
    v25_report: dict[str, Any],
    v25_manifest_path: Path,
    v25_manifest: dict[str, Any],
    v25_receipt_path: Path,
    v25_receipt: dict[str, Any],
) -> dict[str, Any]:
    if v25_proof.get("schema") != V25_PROOF_SCHEMA or v25_proof.get("status") != "PASS_ACTUAL_SEVEN_SOURCE_CLOSED_DEVELOPMENT_COMPONENT_ROLES":
        raise ProductError("v25 proof is not the completed actual component-role proof")
    if v25_proof.get("H5_BI4_read_by_root") is not False or v25_proof.get("hidden_test") is not False:
        raise ProductError("v25 proof does not close H5/BI4 and hidden-test scope")
    if v25_proof.get("all336_development_exposed") is not True or v25_proof.get("native_omission_count") != 1328:
        raise ProductError("v25 proof does not expose all336 and 1328 native aliases")
    if v25_proof.get("same_parent_role_conflicts") != []:
        raise ProductError("v25 proof has same-parent role conflicts")
    qualification = v25_proof.get("scientific_qualification") or {}
    if any(qualification.get(key) != "UNKNOWN" for key in ("QN", "QE", "QI")):
        raise ProductError("v25 proof grants scientific qualification")

    # The proof binds the exact producer files.  It is intentional that the
    # producer CURRENT is the forensic worktree path; a ROOT worktree copy with
    # the same digest is not substituted here.
    proof_report = v25_proof.get("report")
    proof_manifest = v25_proof.get("output_evidence_manifest")
    proof_receipt = v25_proof.get("receipt")
    _require_exact_path(proof_report, v25_report_path, "v25 proof report")
    _require_exact_path(proof_manifest, v25_manifest_path, "v25 proof evidence manifest")
    _require_exact_path(proof_receipt, v25_receipt_path, "v25 proof receipt")
    _require_sha(v25_report_path, v25_proof.get("report_sha256"), "v25 proof report")
    _require_sha(v25_manifest_path, v25_proof.get("output_evidence_manifest_sha256"), "v25 proof evidence manifest")
    _require_sha(v25_receipt_path, v25_proof.get("receipt_sha256"), "v25 proof receipt")

    report_current = (v25_report.get("inputs") or {}).get("current336")
    manifest_current = v25_manifest.get("current336")
    if not isinstance(report_current, dict) or not isinstance(manifest_current, dict):
        raise ProductError("actual v25 report/manifest lacks current336 binding")
    _require_exact_path(report_current.get("path"), current_path, "v25 report CURRENT336")
    _require_exact_path(manifest_current.get("path"), current_path, "v25 manifest CURRENT336")
    current_sha = sha256_file(current_path)
    if report_current.get("sha256") != current_sha or manifest_current.get("sha256") != current_sha:
        raise ProductError("actual v25 report/manifest CURRENT digest differs")
    fresh = _normalize_fresh_small_inputs(v25_proof.get("fresh_small_inputs"))
    current_entries = [item for item in fresh if item["path"] == str(current_path)]
    if len(current_entries) != 1 or current_entries[0]["sha256"] != current_sha:
        raise ProductError("v25 proof does not bind exactly one producer CURRENT336 path and digest")

    if v25_report.get("schema") != V25_SCHEMA or not str(v25_report.get("status", "")).startswith("PREPARED_SOURCE_CLOSED"):
        raise ProductError("actual v25 report schema/status is not source-closed")
    if v25_manifest.get("schema") != "ds02.stage2.current336-task-evidence-manifest.v25" or v25_manifest.get("current336", {}).get("case_count") != 336:
        raise ProductError("actual v25 evidence manifest is not the 336-case manifest")
    if v25_receipt.get("schema") != "ds02.execution-receipt.v1" or v25_receipt.get("status") != "completed" or v25_receipt.get("returncode") not in (None, 0):
        raise ProductError("actual v25 receipt is not completed")
    output_root = v25_receipt.get("output_root")
    if not isinstance(output_root, str) or Path(output_root) != v25_report_path.parent:
        raise ProductError("actual v25 receipt output_root differs from report parent")
    if v25_report.get("component_count") != 7 or not isinstance(v25_report.get("components"), list) or len(v25_report["components"]) != 7:
        raise ProductError("actual v25 report does not contain seven components")
    return {
        "proof": _ref(v25_proof_path, "actual v25 proof"),
        "report": _ref(v25_report_path, "actual v25 report"),
        "manifest": _ref(v25_manifest_path, "actual v25 evidence manifest"),
        "receipt": _ref(v25_receipt_path, "actual v25 receipt"),
        "producer_current": {"path": str(current_path), "sha256": current_sha, "source": "v25 proof fresh_small_inputs + report.inputs.current336"},
        "proof_fresh_small_input_shape": "list" if isinstance(v25_proof.get("fresh_small_inputs"), list) else "object-normalized",
        "development_role_counts": copy_json(v25_proof.get("development_role_counts") or {}),
        "native_omission_count": v25_proof.get("native_omission_count"),
        "qualification": copy_json(qualification),
        "report_status": v25_report.get("status"),
        "receipt_output_root": output_root,
    }


def _validate_quality(
    current_path: Path,
    quality_manifest_path: Path,
    quality_manifest: dict[str, Any],
    quality_proof_path: Path,
    quality_proof: dict[str, Any],
    quality_report_path: Path,
    quality_report: dict[str, Any],
    quality_receipt_path: Path,
    quality_receipt: dict[str, Any],
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    if quality_proof.get("schema") != QUALITY_PROOF_SCHEMA or quality_proof.get("status") != "PASS_ACTUAL_SEVEN_FAMILY_QUALITY_STRICT_PRODUCER_BOUND":
        raise ProductError("strict quality proof is not the actual producer-bound proof")
    if quality_proof.get("H5_BI4_read_by_root") is not False or quality_proof.get("hidden_test") is not False:
        raise ProductError("strict quality proof does not close H5/BI4 and hidden-test scope")
    if quality_proof.get("family_count") != 7 or quality_proof.get("original_trajectory_H5_BI4_or_label_H5_reopened") is not False:
        raise ProductError("strict quality proof does not close seven-family JSON-only scope")
    q = quality_proof.get("scientific_qualification") or {}
    if any(q.get(key) != "UNKNOWN" for key in ("QN", "QE", "QI")):
        raise ProductError("strict quality proof grants scientific qualification")
    _require_exact_path(quality_proof.get("report"), quality_report_path, "strict quality proof report")
    _require_exact_path(quality_proof.get("receipt"), quality_receipt_path, "strict quality proof receipt")
    _require_sha(quality_report_path, quality_proof.get("report_sha256"), "strict quality proof report")
    _require_sha(quality_receipt_path, quality_proof.get("receipt_sha256"), "strict quality proof receipt")
    if quality_report.get("schema") != "ds02.stage2.family-label-quality-evaluator.v2-strict" or quality_report.get("status") != "PASS_SEVEN_FAMILY_TASK_SCOPE_STRICT_PRODUCER_BOUND_NO_QUALIFICATION":
        raise ProductError("strict quality report is not PASS")
    if quality_report.get("family_count") != 7 or not isinstance(quality_report.get("family_cards"), list) or len(quality_report["family_cards"]) != 7:
        raise ProductError("strict quality report does not contain seven cards")
    manifest_binding = (quality_report.get("inputs") or {}).get("manifest")
    if not isinstance(manifest_binding, dict) or manifest_binding.get("path") != str(quality_manifest_path) or manifest_binding.get("sha256") != sha256_file(quality_manifest_path):
        raise ProductError("strict quality report does not bind the supplied quality manifest exactly")
    if quality_manifest.get("schema") != "ds02.stage2.family-label-quality-manifest.v3" or len(quality_manifest.get("entries", [])) != 7:
        raise ProductError("quality manifest does not contain seven entries")
    _ = current_path  # The strict producer's CURRENT path is recorded separately below.
    cards: dict[str, dict[str, Any]] = {}
    for card in quality_report["family_cards"]:
        family, physical = card.get("family_id"), card.get("physical_case_id")
        if family not in FAMILIES or family in cards or (family, physical) not in by_key:
            raise ProductError(f"strict quality card is not an exact CURRENT anchor: {family}/{physical}")
        if by_key[(family, physical)][0] != ANCHOR_INDICES[family] or card.get("quality_checks_closed") is not True:
            raise ProductError(f"strict quality card {family} is not closed at its registered anchor")
        if card.get("source_role") not in {"native_initial_mk", "initial_spatial_region"}:
            raise ProductError(f"strict quality card {family} has an unsupported source role")
        read_policy = card.get("read_policy") or {}
        if any(read_policy.get(key) is not False for key in ("original_trajectory_h5_opened", "part_bi4_opened", "solver_started", "model_invoked")):
            raise ProductError(f"strict quality card {family} has an open read policy")
        cards[family] = copy_json(card)
    if sorted(cards) != FAMILIES:
        raise ProductError("strict quality report does not cover F1-F7 exactly")
    producer_bindings = quality_proof.get("producer_bindings") or {}
    if isinstance(producer_bindings, list):
        producer_current = next(
            (copy_json(item) for item in producer_bindings if isinstance(item, dict) and (item.get("role") == "CURRENT336" or item.get("name") == "CURRENT336" or "current" in str(item.get("path", "")).lower())),
            {},
        )
    else:
        producer_current = copy_json((producer_bindings.get("current336") or {}) if isinstance(producer_bindings, dict) else {})
    return {
        "proof": _ref(quality_proof_path, "strict quality actual proof"),
        "report": _ref(quality_report_path, "strict quality actual report"),
        "receipt": _ref(quality_receipt_path, "strict quality actual receipt"),
        "manifest": _ref(quality_manifest_path, "quality manifest"),
        "producer_current": copy_json(producer_current),
        "cards": cards,
        "qualification": copy_json(q),
        "report_status": quality_report.get("status"),
    }


def _validate_raw_state(current_path: Path, current: dict[str, Any], state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("schema") != RAW_STATE_SCHEMA or state.get("status") != "SEVEN_ACTUAL_RECONSTRUCTION_EVIDENCE_SCOPES_INDEXED":
        raise ProductError("raw-anchor state index is not the expected actual state")
    current_sha = sha256_file(current_path)
    if state.get("current_sha256") != current_sha:
        raise ProductError("raw-anchor state does not bind the producer CURRENT digest")
    anchors = state.get("anchors")
    if not isinstance(anchors, list) or len(anchors) != 7:
        raise ProductError("raw-anchor state must contain seven anchors")
    by_family: dict[str, dict[str, Any]] = {}
    proofs: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        family = anchor.get("family_id")
        if family not in FAMILIES or family in by_family:
            raise ProductError("raw-anchor state has duplicate/unknown family")
        index = ANCHOR_INDICES[family]
        row = current["cases"][index]
        if anchor.get("physical_case_id") != row.get("physical_case_id") or anchor.get("frames") != row.get("frames") or anchor.get("particles") != row.get("particles"):
            raise ProductError(f"raw-anchor state {family} differs from CURRENT anchor")
        proof_path = _path(anchor.get("actual_proof"), f"{family} actual proof")
        _require_sha(proof_path, anchor.get("actual_proof_sha256"), f"{family} actual proof")
        _, proof = _json(proof_path, f"{family} actual proof")
        qualification = proof.get("scientific_qualification") or proof.get("qualification") or {}
        if any(qualification.get(key) not in (None, "UNKNOWN") for key in ("QN", "QE", "QI")):
            raise ProductError(f"{family} raw proof grants qualification")
        if family == "F2":
            # The historical F2 independent proof intentionally carries no
            # top-level status field; its ``scope``/``labels`` blocks and the
            # state index carry the terminal v4 credit.  Require that exact
            # schema rather than silently treating a missing status as PASS.
            if proof.get("schema") != "ds02.stage2.native-raw-to-typed-label-independent-verification.v1":
                raise ProductError("F2 raw-to-label proof has an unexpected schema")
        elif family == "F3":
            if proof.get("status") != "PASS_ACTUAL_RECONSTRUCTION_PHASE_INTEGRITY_RECOVERY" or proof.get("original_deadline_failure_upgraded") is not False:
                raise ProductError("F3 raw recovery proof does not preserve the failed-parent boundary")
        else:
            if proof.get("status") != "PASS_ACTUAL_FULL_RAW_RECONSTRUCTION_BYTE_IDENTICAL_CURRENT_TYPED":
                raise ProductError(f"{family} raw proof is not a completed full reconstruction proof")
        by_family[family] = copy_json(anchor)
        proofs[family] = {"path": str(proof_path), "sha256": sha256_file(proof_path), "schema": proof.get("schema"), "status": proof.get("status"), "request": proof.get("request"), "request_sha256": proof.get("request_sha256"), "receipt": proof.get("receipt"), "receipt_sha256": proof.get("receipt_sha256"), "report": proof.get("report"), "report_sha256": proof.get("report_sha256"), "actual_time_window_s": copy_json(proof.get("actual_time_window_s")), "portable_trial_completed": proof.get("portable_trial_completed"), "scope": copy_json(proof.get("scope") or proof.get("recovered_scope") or {})}
    if sorted(by_family) != FAMILIES:
        raise ProductError("raw-anchor state does not cover F1-F7")
    return {"path": str(state_path), "sha256": sha256_file(state_path), "status": state.get("status"), "anchors": by_family, "proofs": proofs, "boundary": copy_json(state.get("boundary")), "portable_trial": state.get("full_portable_raw_typed_label_privateSDK_evaluator_trial"), "goal_complete": state.get("goal_complete")}


def _validate_raw_index(current: dict[str, Any], index_path: Path, index: dict[str, Any], f2_bundle_path: Path, f2_bundle: dict[str, Any], f2_request_path: Path) -> dict[str, Any]:
    if index.get("schema") != RAW_INDEX_SCHEMA:
        raise ProductError("raw family index has an unexpected schema")
    rows = index.get("families")
    if not isinstance(rows, list) or {row.get("family_id") for row in rows} != {"F1", "F3", "F4", "F5", "F6", "F7"}:
        raise ProductError("raw family index must contain the six non-F2 anchors")
    f2_ref = index.get("f2_reference") or {}
    bundle_ref = f2_ref.get("bundle") or {}; request_ref = f2_ref.get("request") or {}
    if bundle_ref.get("path") != str(f2_bundle_path) or request_ref.get("path") != str(f2_request_path):
        raise ProductError("raw family index does not bind the supplied F2 bundle/request paths")
    # This historical planning index predates the final v4 JSON bytes.  Keep
    # its declared digests as provenance, but bind the actual source files by
    # their current bytes in the v27 request.  A path mismatch is fatal; a
    # stale index digest is explicit and cannot silently become producer
    # credit.
    bundle_actual_sha = sha256_file(f2_bundle_path)
    request_actual_sha = sha256_file(f2_request_path)
    if f2_bundle.get("schema") != "ds02.stage2.f2-native-raw-to-label-bundle.v4" or not str(f2_bundle.get("status", "")).startswith("READY_FOR_PARENT_PORTABLE_GUARD"):
        raise ProductError("F2 native bundle is not the v4 terminal/development bundle")
    scope = f2_bundle.get("case_scope") or {}
    row = current["cases"][ANCHOR_INDICES["F2"]]
    for key in ("current_case_index", "family_id", "physical_case_id", "frames", "particles", "manifest_case_id"):
        if key == "manifest_case_id":
            # The CURRENT runtime alias is the manifest case id for this exact anchor.
            expected = row.get("runtime_case_alias")
        else:
            expected = ANCHOR_INDICES["F2"] if key == "current_case_index" else row.get(key)
        if scope.get(key) != expected:
            raise ProductError(f"F2 bundle case_scope mismatch for {key}")
    if f2_bundle.get("qualification", {}).get("QN") != "UNKNOWN" or f2_bundle.get("qualification", {}).get("QE") != "UNKNOWN" or f2_bundle.get("qualification", {}).get("QI") != "UNKNOWN":
        raise ProductError("F2 native bundle grants qualification")
    return {
        "index": _ref(index_path, "six-family raw anchor index"),
        "schema": index.get("schema"),
        "status": index.get("status"),
        "families": {row["family_id"]: {"status": row.get("status"), "actual_or_pending": row.get("actual_or_pending"), "bundle": copy_json(row.get("bundle")), "request": copy_json(row.get("request"))} for row in rows},
        "f2_reference": {
            "bundle": {**_ref(f2_bundle_path, "F2 native v4 bundle"), "index_declared_sha256": bundle_ref.get("sha256"), "index_declared_digest_matches": bundle_ref.get("sha256") == bundle_actual_sha},
            "request": {**_ref(f2_request_path, "F2 native v4 request"), "index_declared_sha256": request_ref.get("sha256"), "index_declared_digest_matches": request_ref.get("sha256") == request_actual_sha},
            "status": f2_ref.get("status"), "case_scope": copy_json(scope), "limitations": copy_json(f2_bundle.get("limitations") or []),
        },
        "qualification": copy_json(index.get("qualification") or f2_bundle.get("qualification") or {}),
    }


def _compact_bindings(row: dict[str, Any]) -> list[dict[str, Any]]:
    bindings = row.get("source_bindings") if isinstance(row.get("source_bindings"), dict) else {}
    result: list[dict[str, Any]] = []
    for role, item in sorted(bindings.items()):
        if not isinstance(item, dict):
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str) or Path(path_value).suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ProductError(f"anchor source binding {role} is not a small non-scientific file")
        path = _path(path_value, f"anchor source binding {role}")
        declared = item.get("sha256") or item.get("recomputed_sha256")
        if declared != sha256_file(path):
            raise ProductError(f"anchor source binding {role} digest mismatch")
        result.append({"role": role, "path": str(path), "sha256": declared, "bytes": path.stat().st_size})
    return result


def _condition_summary(component: dict[str, Any]) -> dict[str, Any]:
    graph = component.get("condition_graph") or {}
    condition = graph.get("condition") or {}
    return {
        "component_id": component.get("component_id"),
        "condition_sha256": condition.get("physical_condition_sha256") or canonical_sha(condition),
        "control_family_id": condition.get("control_family_id"),
        "geometry_family_id": condition.get("geometry_family_id"),
        "lineage_group_id": condition.get("lineage_group_id"),
        "mechanism_id": condition.get("mechanism_id"),
        "known_numeric_physical_parameters": copy_json(condition.get("known_numeric_physical_parameters") or {}),
        "controls": copy_json(condition.get("controls") or {}),
        "geometry": copy_json(condition.get("geometry") or {}),
        "native_parent_status": "SOURCE_CLOSED_METADATA_REFERENCE_ONLY",
        "recovery_equivalence_to_other_anchor": (graph.get("recovery") or {}).get("recovery_equivalence_to_other_anchor", "UNKNOWN"),
        "window_transfer_to_other_anchor": (graph.get("window") or {}).get("window_transfer_to_other_anchor", "UNKNOWN"),
    }


def _family_card(
    family: str,
    row: dict[str, Any],
    component: dict[str, Any],
    assignment: dict[str, Any],
    quality: dict[str, Any],
    state: dict[str, Any],
    raw_index: dict[str, Any],
    v25_summary: dict[str, Any],
) -> dict[str, Any]:
    index = ANCHOR_INDICES[family]
    raw_anchor = state["anchors"][family]
    raw_proof = state["proofs"][family]
    if family == "F3":
        parent_boundary = {
            "original_parent_replay": "NOT_RECOVERED",
            "original_parent_failure_preserved": True,
            "recovered_scope": "typed_content_phase_only",
            "labels_invoked_in_recovery": False,
            "qualification": "UNKNOWN",
            "old_failed_receipt": copy_json((json.loads(Path(raw_proof["path"]).read_text(encoding="utf-8")).get("preserved_old_failed_receipt") or {})),
        }
    elif family == "F2":
        parent_boundary = {
            "native_v4_terminal_verified": True,
            "portable_replay": "NOT_RUN_BY_BUNDLE_BUILDER",
            "labels_scope": "DEVELOPMENT_UNKNOWN",
            "hidden_between_save_recrossings": "UNKNOWN",
        }
    else:
        parent_boundary = {"full_native_reconstruction": "ACTUAL_COMPLETED_BYTE_IDENTITY_SCOPE", "portable_trial": raw_anchor.get("credit")}
    quality_scope = copy_json(quality)
    quality_scope["strict_quality_proof"] = v25_summary["quality_proof_ref"] if "quality_proof_ref" in v25_summary else None
    return {
        "schema": "ds02.stage2.family-card.v27",
        "family_id": family,
        "current_anchor": {
            "current_index": index,
            "physical_case_id": row.get("physical_case_id"),
            "runtime_case_alias": row.get("runtime_case_alias"),
            "frames": row.get("frames"),
            "particles": row.get("particles"),
            "actual_time_window_s": copy_json(row.get("actual_time_window_s")),
            "source_bindings": _compact_bindings(row),
        },
        "condition_evidence": _condition_summary(component),
        "development_role": {
            "component_id": component.get("component_id"),
            "saved_frame_role": assignment.get("saved_frame_role"),
            "source_role": assignment.get("source_role"),
            "scientific_split_safe": assignment.get("scientific_split_safe", "UNKNOWN"),
            "same_parent_derivatives_stay_in_component": True,
            "cross_component_transfer": "DISALLOWED_UNLESS_EXACT_PHYSICAL_CONTROL_GEOMETRY_PARENT_RECOVERY_WINDOW_EQUALITY_IS_PROVEN",
        },
        "raw_reconstruction": {
            "actual_state_credit": raw_anchor.get("credit"),
            "producer_or_root_status": raw_anchor.get("producer_or_root_status"),
            "actual_proof": raw_proof,
            "raw_index_parent_slot": raw_index.get("families", {}).get(family) if family != "F2" else raw_index.get("f2_reference"),
            "full_original_parent_replay_recovered": raw_anchor.get("full_original_parent_replay_recovered"),
            "typed_reference_content_root_reopened": raw_anchor.get("typed_reference_content_root_reopened"),
        },
        "quality_saved_frame_scope": quality_scope,
        "task_eligibility": {
            "owner_control_geometry_metadata": "ELIGIBLE_SOURCE_CLOSED_EXACT_ANCHOR",
            "source_role_mass_ledger": "ELIGIBLE_SOURCE_ROLE_BOOKKEEPING_ONLY",
            "saved_frame_artifact": "ELIGIBLE_LIMITED_SAVED_FRAME_DIAGNOSTICS",
            "native_cause_alias_join": "ELIGIBLE_EXACT_118_ALIAS_CASES" if family in {"F2", "F4", "F6"} else "NOT_SELECTED",
            "material_region_event_transport": "EXCLUDED_UNSUPPORTED",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "effective_split_safe": "UNKNOWN",
            "recovery_window_transfer": "UNKNOWN",
            "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN",
            "qualification_credit": "NONE",
        },
        "failure_or_censoring": {
            "saved_frame_first_passage": "FIRST_OBSERVED_SAVED_FRAME_CHORD_BRACKET_ONLY",
            "hidden_continuous_events": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "identity_loss_physical_destination": "UNKNOWN",
            "mass_lower_bound_is_dynamical_error_bound": False,
            "specific_parent_boundary": parent_boundary,
            "unresolved_reasons": [
                "numerical identity exclusion or saved-frame classification does not establish physical fate or legal flux",
                "saved-frame chord brackets do not prove continuous first arrival, hidden crossing, or residence",
                "source role and one exact anchor do not prove transfer/effective-split safety",
                "QN/QE/QI and dynamical impact remain outside this product",
            ],
        },
        "access_policy": {
            "metadata_files_only": True,
            "original_trajectory_h5_opened_by_assembler": False,
            "materialized_label_h5_opened_by_assembler": False,
            "part_bi4_opened_by_assembler": False,
            "solver_started": False,
            "model_invoked": False,
            "producer_paths_in_cards_are_provenance_only": True,
        },
    }


def build(
    current_path: Path | str,
    v25_proof_path: Path | str,
    v25_report_path: Path | str,
    v25_manifest_path: Path | str,
    v25_receipt_path: Path | str,
    raw_state_path: Path | str,
    raw_index_path: Path | str,
    f2_bundle_path: Path | str,
    f2_request_path: Path | str,
    quality_manifest_path: Path | str,
    quality_proof_path: Path | str,
    quality_report_path: Path | str,
    quality_receipt_path: Path | str,
    manifest_output: Path | str,
    output: Path | str,
) -> dict[str, Any]:
    current_path, current = _json(current_path, "producer CURRENT336")
    v25_proof_path, v25_proof = _json(v25_proof_path, "actual v25 proof")
    v25_report_path, v25_report = _json(v25_report_path, "actual v25 report")
    v25_manifest_path, v25_manifest = _json(v25_manifest_path, "actual v25 evidence manifest")
    v25_receipt_path, v25_receipt = _json(v25_receipt_path, "actual v25 receipt")
    raw_state_path, raw_state = _json(raw_state_path, "seven raw-anchor state")
    raw_index_path, raw_index = _json(raw_index_path, "six-family raw-anchor index")
    f2_bundle_path, f2_bundle = _json(f2_bundle_path, "F2 native v4 bundle")
    f2_request_path, _ = _json(f2_request_path, "F2 native v4 request")
    quality_manifest_path, quality_manifest = _json(quality_manifest_path, "quality v3 manifest")
    quality_proof_path, quality_proof = _json(quality_proof_path, "strict quality proof")
    quality_report_path, quality_report = _json(quality_report_path, "strict quality report")
    quality_receipt_path, quality_receipt = _json(quality_receipt_path, "strict quality receipt")
    rows, by_key = _validate_current(current_path, current)
    v25_summary = _validate_actual_v25(current_path, v25_proof_path, v25_proof, v25_report_path, v25_report, v25_manifest_path, v25_manifest, v25_receipt_path, v25_receipt)
    quality_summary = _validate_quality(current_path, quality_manifest_path, quality_manifest, quality_proof_path, quality_proof, quality_report_path, quality_report, quality_receipt_path, quality_receipt, by_key)
    v25_summary["quality_proof_ref"] = quality_summary["proof"]
    state_summary = _validate_raw_state(current_path, current, raw_state_path, raw_state)
    raw_index_summary = _validate_raw_index(current, raw_index_path, raw_index, f2_bundle_path, f2_bundle, f2_request_path)
    components = {component.get("component_id"): component for component in v25_report.get("components", [])}
    assignments = {item.get("family_id"): item for item in (v25_report.get("development_split") or {}).get("assignments", [])}
    component_by_family: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        component_id = f"v24-anchor-{family}"
        if component_id not in components or family not in assignments:
            raise ProductError(f"actual v25 product lacks exact component/assignment for {family}")
        members = components[component_id].get("members")
        if members != [{"current_index": ANCHOR_INDICES[family], "family_id": family, "physical_case_id": rows[ANCHOR_INDICES[family]].get("physical_case_id")}]:
            raise ProductError(f"actual v25 component {family} differs from exact CURRENT anchor")
        component_by_family[family] = components[component_id]

    cards = {
        family: _family_card(family, rows[ANCHOR_INDICES[family]], component_by_family[family], assignments[family], quality_summary["cards"][family], state_summary, raw_index_summary, v25_summary)
        for family in FAMILIES
    }
    case_inventory = []
    for index, row in enumerate(rows):
        family = row["family_id"]
        is_anchor = index == ANCHOR_INDICES[family]
        case_inventory.append({
            "current_index": index,
            "family_id": family,
            "physical_case_id": row["physical_case_id"],
            "runtime_case_alias": row.get("runtime_case_alias"),
            "frames": row.get("frames"),
            "actual_time_window_s": copy_json(row.get("actual_time_window_s")),
            "anchor_card": family if is_anchor else None,
            "source_role": quality_summary["cards"][family].get("source_role") if is_anchor else "UNKNOWN_UNRESOLVED_NON_ANCHOR",
            "task_scope": "EXACT_ANCHOR_SOURCE_CLOSED_METADATA_AND_SAVED_FRAME" if is_anchor else "CURRENT_EXPOSED_METADATA_ONLY_NO_ANCHOR_TRANSFER",
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN",
        })
    refs = [
        _ref(current_path, "producer CURRENT336"), _ref(v25_proof_path, "actual v25 proof"), _ref(v25_report_path, "actual v25 report"),
        _ref(v25_manifest_path, "actual v25 evidence manifest"), _ref(v25_receipt_path, "actual v25 receipt"),
        _ref(raw_state_path, "seven raw-anchor actual state"), _ref(raw_index_path, "six-family raw-anchor index"),
        _ref(f2_bundle_path, "F2 native v4 bundle"), _ref(f2_request_path, "F2 native v4 request"),
        _ref(quality_manifest_path, "quality v3 manifest"), _ref(quality_proof_path, "strict quality proof"),
        _ref(quality_report_path, "strict quality report"), _ref(quality_receipt_path, "strict quality receipt"),
        *[{"role": f"{family} actual raw proof", **{key: value for key, value in (("path", item["path"]), ("sha256", item["sha256"]))}} for family, item in sorted(state_summary["proofs"].items())],
    ]
    # The seven raw proof paths are already checked above; add their byte sizes
    # without reopening any scientific payload.
    for ref in refs:
        if "bytes" not in ref:
            ref["bytes"] = Path(ref["path"]).stat().st_size
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "producer_current": v25_summary["producer_current"],
        "actual_v25": v25_summary,
        "actual_quality": quality_summary,
        "raw_anchor_state": state_summary,
        "raw_anchor_index": raw_index_summary,
        "source_refs": refs,
        "case_count": 336,
        "family_counts": {family: 48 for family in FAMILIES},
        "anchor_count": 7,
        "native_alias_count": 1328,
        "cards": cards,
        "case_inventory": case_inventory,
        "read_policy": {
            "current_json_opened": True, "v25_proof_report_manifest_receipt_opened": True,
            "raw_state_index_and_proofs_opened": True, "quality_manifest_proof_report_receipt_opened": True,
            "original_trajectory_h5_opened_by_this_worker": False,
            "materialized_label_h5_opened_by_this_worker": False,
            "part_bi4_opened_by_this_worker": False,
            "raw_solver_output_opened_by_this_worker": False,
            "solver_started": False, "model_invoked": False,
            "byte_equivalent_current_alias_accepted": False,
        },
        "claim_boundary": {
            "eligible": ["exact producer CURRENT/source bindings", "seven anchor owner/control/geometry metadata cards", "source-role mass bookkeeping", "limited saved-frame artifact diagnostics", "118 native alias identity scope"],
            "physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN", "continuous_events": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN",
            "recovery_window_transfer": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none",
            "mass_screen": "whole-initial denominator remains task-specific; missing mass is a visibility lower bound and not a dynamics bound",
        },
    }
    manifest_output = _path(manifest_output, "manifest output") if Path(manifest_output).exists() else Path(manifest_output).expanduser().resolve()
    if manifest_output.exists():
        raise ProductError(f"refusing to overwrite v27 manifest: {manifest_output}")
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema": PRODUCT_SCHEMA,
        "status": "PREPARED_ACTUAL_V25_BOUND_SEVEN_FAMILY_PRODUCT_NO_PHYSICAL_QUALIFICATION",
        "producer": manifest["producer"],
        "inputs": {"manifest": _ref(manifest_output, "v27 product manifest"), "source_refs": refs},
        "coverage": {"current_case_count": 336, "family_counts": {family: 48 for family in FAMILIES}, "hidden_current_cases": 0, "anchor_cards": 7, "native_alias_cases": 118, "native_alias_ids": 1328, "raw_state_actual_anchors": 7, "f3_full_parent_replay_recovered": False},
        "family_cards": cards,
        "case_inventory": case_inventory,
        "actual_v25": v25_summary,
        "actual_quality": quality_summary,
        "raw_anchor_state": state_summary,
        "raw_anchor_index": raw_index_summary,
        "read_policy": manifest["read_policy"],
        "claim_boundary": manifest["claim_boundary"],
    }
    output = _path(output, "product output") if Path(output).exists() else Path(output).expanduser().resolve()
    if output.exists():
        raise ProductError(f"refusing to overwrite v27 product: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _runtime_inputs(runtime_root: Path, worker_root: Path) -> list[Path]:
    paths = [
        SCRIPT,
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_final_family_product_assembler_v27.py",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = _path(path, "runtime/source input")
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    return unique


def make_request(
    current_path: Path | str,
    v25_proof_path: Path | str,
    v25_report_path: Path | str,
    v25_manifest_path: Path | str,
    v25_receipt_path: Path | str,
    raw_state_path: Path | str,
    raw_index_path: Path | str,
    f2_bundle_path: Path | str,
    f2_request_path: Path | str,
    quality_manifest_path: Path | str,
    quality_proof_path: Path | str,
    quality_report_path: Path | str,
    quality_receipt_path: Path | str,
    output: Path | str,
    runtime_root: Path | str,
    worker_root: Path | str,
    attempt_id: str = "final-family-product-v27-forward-001",
) -> dict[str, Any]:
    current_path = _path(current_path, "producer CURRENT336")
    v25_proof_path, v25_proof = _json(v25_proof_path, "actual v25 proof")
    v25_report_path, v25_report = _json(v25_report_path, "actual v25 report")
    v25_manifest_path, v25_manifest = _json(v25_manifest_path, "actual v25 evidence manifest")
    v25_receipt_path, v25_receipt = _json(v25_receipt_path, "actual v25 receipt")
    raw_state_path, raw_state = _json(raw_state_path, "seven raw-anchor state")
    raw_index_path, raw_index = _json(raw_index_path, "six-family raw-anchor index")
    f2_bundle_path, f2_bundle = _json(f2_bundle_path, "F2 native v4 bundle")
    f2_request_path = _path(f2_request_path, "F2 native v4 request")
    quality_manifest_path, quality_manifest = _json(quality_manifest_path, "quality v3 manifest")
    quality_proof_path, quality_proof = _json(quality_proof_path, "strict quality proof")
    quality_report_path, quality_report = _json(quality_report_path, "strict quality report")
    quality_receipt_path, quality_receipt = _json(quality_receipt_path, "strict quality receipt")
    rows, by_key = _validate_current(current_path, json.loads(current_path.read_text(encoding="utf-8")))
    _validate_actual_v25(current_path, v25_proof_path, v25_proof, v25_report_path, v25_report, v25_manifest_path, v25_manifest, v25_receipt_path, v25_receipt)
    _validate_quality(current_path, quality_manifest_path, quality_manifest, quality_proof_path, quality_proof, quality_report_path, quality_report, quality_receipt_path, quality_receipt, by_key)
    _validate_raw_state(current_path, rows and json.loads(current_path.read_text(encoding="utf-8")), raw_state_path, raw_state)
    _validate_raw_index(json.loads(current_path.read_text(encoding="utf-8")), raw_index_path, raw_index, f2_bundle_path, f2_bundle, f2_request_path)
    runtime_root = Path(runtime_root).expanduser().resolve(); worker_root = Path(worker_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_final_family_product_assembler_v27.py"
    inputs = _runtime_inputs(runtime_root, worker_root)
    inputs.extend([current_path, v25_proof_path, v25_report_path, v25_manifest_path, v25_receipt_path, raw_state_path, raw_index_path, f2_bundle_path, f2_request_path, quality_manifest_path, quality_proof_path, quality_report_path, quality_receipt_path])
    unique: list[Path] = []; seen: set[str] = set()
    for path in inputs:
        path = _path(path, "request input")
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    hashes = {str(path): sha256_file(path) for path in unique}
    command = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "build",
        "--current", str(current_path), "--v25-proof", str(v25_proof_path), "--v25-report", str(v25_report_path),
        "--v25-manifest", str(v25_manifest_path), "--v25-receipt", str(v25_receipt_path), "--raw-state", str(raw_state_path),
        "--raw-index", str(raw_index_path), "--f2-bundle", str(f2_bundle_path), "--f2-request", str(f2_request_path),
        "--quality-manifest", str(quality_manifest_path), "--quality-proof", str(quality_proof_path), "--quality-report", str(quality_report_path),
        "--quality-receipt", str(quality_receipt_path), "--manifest-output", "{attempt_root}/final-family-product-manifest-v27.json", "--output", "{attempt_root}/final-family-product-v27.json",
    ]
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": "ds02.stage2.final-family-product-v27-request.v1", "attempt_id": attempt_id,
        "case_id": "DS02_STAGE2_FINAL_FAMILY_PRODUCT_V27", "family_id": "infra", "dataset_families": FAMILIES,
        "kind": "cpu", "cpu_task_kind": "metadata_audit", "cpu_threads": 1, "max_wall_seconds": 900,
        "estimated_storage_bytes": 32 * 1024 * 1024, "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(worker_root),
        "command": command, "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": True, "primary_launch_owner": "root", "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {"small_json_receipt_proof_bytes_read": sum(path.stat().st_size for path in unique), "materialized_label_h5_bytes_read": 0, "original_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN", "continuous_events": "UNKNOWN", "hidden_recrossings": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN", "recovery_window_transfer": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none"},
        "coverage_contract": {"exact_current_case_count": 336, "hidden_current_cases": 0, "seven_family_cards": 7, "native_alias_cases": 118, "native_alias_ids": 1328, "f3_parent_replay_recovered": False},
        "upstream_quality_h5": "quality producer's prior materialized-label H5 read is represented only by actual report/receipt; this worker opens JSON only",
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ProductError(f"refusing to overwrite v27 request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    names = ("current", "v25-proof", "v25-report", "v25-manifest", "v25-receipt", "raw-state", "raw-index", "f2-bundle", "f2-request", "quality-manifest", "quality-proof", "quality-report", "quality-receipt")
    for command in ("build", "make-request"):
        p = sub.add_parser(command)
        for name in names:
            p.add_argument(f"--{name}", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if command == "build":
            p.add_argument("--manifest-output", type=Path, required=True)
        else:
            p.add_argument("--runtime-root", type=Path, required=True)
            p.add_argument("--worker-root", type=Path, required=True)
            p.add_argument("--attempt-id", default="final-family-product-v27-forward-001")
    args = parser.parse_args(argv)
    kwargs = {name.replace("-", "_") + "_path": getattr(args, name.replace("-", "_")) for name in names}
    if args.command == "build":
        build(**kwargs, manifest_output=args.manifest_output, output=args.output)
    else:
        make_request(**kwargs, output=args.output, runtime_root=args.runtime_root, worker_root=args.worker_root, attempt_id=args.attempt_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
