#!/usr/bin/env python3
"""Build a terminal-proof-bound rolling native/typed overlay.

This is the additive admission entry after the metadata-only V2 adapter.  It
consumes a previous actual V10-compatible overlay and one root-owned terminal
proof.  A completed proof may append its exact native/typed proof reference to
``actual_join_proofs``.  A failed or partial proof produces an immutable
no-join continuation record and leaves the previous proof list unchanged.

The terminal contract deliberately requires fee closure, resource release,
and an idempotence check before any join is admitted.  The proof rows remain
the root wrapper's responsibility; this adapter never treats a worker report
or a count as a proof.  Cases already cause-bound in the previous overlay can
gain a typed/native join, but never gain new native-cause credit.  The seven
ROOT312 unresolved cases can gain both only when the terminal proof explicitly
contains those exact case rows.  Physical fate, legal flux, dynamics, and
QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ds_data02_stage2_verify_generic_native_join_v6 as v6


OVERLAY_SCHEMA = v6.OVERLAY_SCHEMA
TERMINAL_PROOF_SCHEMA = "ds02.stage2.root-terminal-proof.v1"
ROOT_ACTUAL_SCHEMA = "ds02.stage2.root-actual-verification.v1"
STRICT_TERMINAL_SCHEMAS = frozenset({TERMINAL_PROOF_SCHEMA, ROOT_ACTUAL_SCHEMA})
STRICT_JOIN_PROOF_SCHEMAS = frozenset({
    ROOT_ACTUAL_SCHEMA,
    "ds02.stage2.root-terminal-native-join-proof.v1",
})
OUTPUT_SCHEMA = "ds02.stage2.original118-native-cause-actual-overlay-v4"
MAX_JSON = 12 * 1024 * 1024
PAYLOAD_SUFFIXES = set(v6.PAYLOAD_SUFFIXES)


class TerminalOverlayError(ValueError):
    pass


def _fail(message: str) -> None:
    raise TerminalOverlayError(message)


def _sha(path: Path, label: str) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        _fail(f"{label} is missing: {path}")
    if path.stat().st_size > MAX_JSON:
        _fail(f"{label} exceeds bounded metadata size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(value: Any, label: str, *, expected_sha: str | None = None) -> dict[str, Any]:
    if not isinstance(value, (str, Path)) or not str(value):
        _fail(f"{label} path is malformed")
    path = Path(value).expanduser().resolve()
    before = path.stat()
    actual_sha = _sha(path, label)
    after = path.stat()
    before_tuple = (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino, before.st_dev)
    after_tuple = (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino, after.st_dev)
    if before_tuple != after_tuple:
        _fail(f"{label} changed during capture: {path}")
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual_sha != expected_sha:
        _fail(f"{label} SHA differs: {path}")
    return {
        "path": str(path),
        "bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "st_dev": int(after.st_dev),
        "st_ino": int(after.st_ino),
        "sha256": actual_sha,
        "stable_capture": True,
    }


def _json(value: Any, label: str, *, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = _ref(value, label, expected_sha=expected_sha)
    try:
        document = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TerminalOverlayError(f"{label} is not bounded JSON: {ref['path']}") from exc
    if not isinstance(document, dict):
        _fail(f"{label} must be a JSON object")
    return document, ref


def _concrete_ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        _fail(f"{label} reference is malformed")
    expected = value.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64 or expected == "PARENT_GUARD_COMPUTED":
        _fail(f"{label} requires a concrete SHA-256")
    path = Path(value["path"]).expanduser().resolve()
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        _fail(f"{label} payload entered terminal static closure: {path}")
    return _ref(path, label, expected_sha=expected)


def _case_rows(proof: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    for key in ("case_verifications", "case_results", "cases"):
        value = proof.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    top_case = proof.get("physical_case_id")
    if isinstance(top_case, str) and top_case:
        rows.append({"physical_case_id": top_case})
    ids = [row.get("physical_case_id") for row in rows]
    if not ids or any(not isinstance(case_id, str) or not case_id for case_id in ids):
        _fail(f"{label} has no exact physical-case rows")
    if len(ids) != len(set(ids)):
        _fail(f"{label} repeats a physical case")
    return rows, set(ids)


def _proof_ref(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    actual_ref = _concrete_ref(value, label)
    try:
        proof = json.loads(Path(actual_ref["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TerminalOverlayError(f"{label} is not bounded JSON: {actual_ref['path']}") from exc
    if not isinstance(proof, dict):
        _fail(f"{label} must be a JSON object")
    rows, ids = _case_rows(proof, label)
    if proof.get("schema") not in STRICT_JOIN_PROOF_SCHEMAS:
        _fail(f"{label} schema is unsupported: {proof.get('schema')!r}")
    proof_status = proof.get("status")
    if not isinstance(proof_status, str) or not proof_status.startswith("VERIFIED_ACTUAL_"):
        _fail(f"{label} is not an actual verified root proof")
    failed_cases = proof.get("failed_cases")
    if isinstance(failed_cases, list) and failed_cases:
        _fail(f"{label} contains failed case rows")
    failed_physical = proof.get("failed_physical_cases")
    if isinstance(failed_physical, list) and failed_physical:
        _fail(f"{label} contains failed physical cases")
    if isinstance(failed_physical, int) and not isinstance(failed_physical, bool) and failed_physical != 0:
        _fail(f"{label} declares failed physical cases")
    completed = proof.get("actual_completed_physical_cases")
    if isinstance(completed, int) and not isinstance(completed, bool) and completed != len(rows):
        _fail(f"{label} completed-case count differs from its selected rows")
    for row in rows:
        row_status = row.get("status")
        if row_status is not None and (
            not isinstance(row_status, str)
            or not row_status
            or any(token in row_status.upper() for token in ("FAILED", "PARTIAL", "PENDING", "TIMEOUT", "CANCEL"))
        ):
            _fail(f"{label} contains a non-terminal case row")
        has_native_evidence = any(key in row for key in ("native_csv_evidence", "native_report", "native_exit_cause", "native_cause_categories"))
        has_typed_evidence = any(key in row for key in ("typed_summary", "typed_records_stat_only", "typed_records_stat_SHA_only", "source_H5_stat_only"))
        if not has_native_evidence or not has_typed_evidence:
            _fail(f"{label} row lacks native and typed source evidence")
    return proof, actual_ref, ids


def _terminal_state(terminal: dict[str, Any]) -> str:
    """Return a state only for the allow-listed root terminal contract.

    The old V3 predicate treated every non-empty status which did not happen
    to contain ``failed`` as success.  That made arbitrary JSON with an empty
    execution object eligible for an actual join.  A status is now meaningful
    only together with the root proof schema and an explicit terminal prefix.
    """
    schema = terminal.get("schema")
    if schema not in STRICT_TERMINAL_SCHEMAS:
        _fail(f"root terminal proof schema is unsupported: {schema!r}")
    status = terminal.get("status")
    if not isinstance(status, str) or not status:
        _fail("root terminal proof lacks status")
    if status.startswith("VERIFIED_ACTUAL_"):
        return "COMPLETED"
    if (
        status.startswith("FAILED_")
        or status.startswith("PARTIAL_")
        or status in {"FAILED", "PARTIAL", "CANCELLED", "TIMEOUT"}
    ):
        return "FAILED_OR_PARTIAL"
    _fail(f"root terminal proof has an unrecognised terminal status: {status!r}")


def _strict_top_refs(terminal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Capture the four root-owned identity references and their SHA closure."""
    refs: dict[str, dict[str, Any]] = {}
    for name in ("request", "receipt", "report", "manifest"):
        value = terminal.get(name)
        expected = terminal.get(f"{name}_sha256")
        if not isinstance(value, str) or not value:
            _fail(f"completed terminal proof lacks {name} path")
        if not isinstance(expected, str) or len(expected) != 64:
            _fail(f"completed terminal proof lacks concrete {name}_sha256")
        refs[name] = _ref(value, f"terminal {name}", expected_sha=expected)
    return refs


def _strict_receipt_identity(terminal: dict[str, Any], refs: dict[str, dict[str, Any]]) -> None:
    """Bind request, receipt, fee closure, and the output identity exactly."""
    request, _ = _json(terminal["request"], "terminal request", expected_sha=terminal["request_sha256"])
    receipt, _ = _json(terminal["receipt"], "terminal execution receipt", expected_sha=terminal["receipt_sha256"])
    if request.get("schema") != "ds02.request.v1":
        _fail("terminal request schema is not ds02.request.v1")
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        _fail("terminal receipt schema is not ds02.execution-receipt.v1")
    if receipt.get("request_sha256") != terminal["request_sha256"]:
        _fail("terminal receipt does not bind the terminal request SHA")
    request_attempt = request.get("attempt_id")
    receipt_request = receipt.get("request")
    if not isinstance(request_attempt, str) or not isinstance(receipt_request, dict):
        _fail("terminal request/receipt lacks an attempt identity")
    if receipt_request.get("attempt_id") != request_attempt:
        _fail("terminal receipt request attempt differs from terminal request")
    manifest_contract = request.get("manifest_contract")
    if not isinstance(manifest_contract, dict):
        # Older, already-consumed root requests use the equivalent
        # source_closure.manifest pair.  Accept that explicit pair only; a
        # missing/boolean convenience flag is never a manifest identity.
        source_closure = request.get("source_closure")
        if not isinstance(source_closure, dict):
            _fail("terminal request lacks manifest_contract/source_closure")
        manifest_contract = {
            "path": source_closure.get("manifest"),
            "sha256": source_closure.get("manifest_sha256"),
        }
    if manifest_contract.get("path") != refs["manifest"]["path"]:
        _fail("terminal request manifest path differs from terminal proof")
    if manifest_contract.get("sha256") != refs["manifest"]["sha256"]:
        _fail("terminal request manifest SHA differs from terminal proof")
    if receipt.get("status") not in {"completed", "COMPLETED", "success", "SUCCESS"}:
        _fail("terminal receipt is not completed")
    if receipt.get("returncode") != 0:
        _fail("terminal receipt returncode is not zero")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or not output_root:
        _fail("terminal receipt lacks output_root")
    output_root_path = Path(output_root).expanduser().resolve()
    report_path = Path(refs["report"]["path"]).resolve()
    try:
        report_path.relative_to(output_root_path)
    except ValueError as exc:
        raise TerminalOverlayError("terminal report is outside receipt output_root") from exc
    charge = terminal.get("parent_charge") or terminal.get("fee")
    if not isinstance(charge, dict):
        _fail("completed terminal proof lacks parent_charge/fee")
    charge_id = charge.get("id")
    if not isinstance(charge_id, str) or not charge_id:
        _fail("completed terminal proof lacks closed fee id")
    if output_root_path.name not in charge_id:
        _fail("closed fee id does not bind receipt output identity")
    # Keep the producer's own request identity in the terminal proof as well;
    # it prevents a caller from pairing a real receipt with a different q.
    declared_request_sha = request.get("request_sha256")
    if declared_request_sha is not None and declared_request_sha != terminal["request_sha256"]:
        _fail("terminal request carries a conflicting request SHA")


def _require_completed_accounting(terminal: dict[str, Any]) -> None:
    """Require an actual root-success execution, never caller-supplied bools."""
    execution = terminal.get("execution")
    if "execution" in terminal:
        if not isinstance(execution, dict) or not execution:
            _fail("completed terminal proof has an empty execution object")
        if execution.get("returncode") != 0:
            _fail("completed terminal proof has nonzero/missing execution returncode")
        if execution.get("status") not in ("COMPLETED", "SUCCESS", "success", "completed"):
            _fail("completed terminal proof execution status is not terminal-success")
    else:
        if terminal.get("guarded_receipt_status") not in ("completed", "COMPLETED"):
            _fail("completed terminal proof lacks completed guarded receipt status")
        if terminal.get("outer_unit_result") not in ("success", "SUCCESS"):
            _fail("completed terminal proof lacks successful outer unit result")

    charge = terminal.get("parent_charge") or terminal.get("fee")
    if not isinstance(charge, dict) or str(charge.get("status", "")).lower() not in {"completed", "closed", "settled"}:
        _fail("completed terminal proof lacks closed fee/charge")
    if not isinstance(charge.get("id"), str) or not charge["id"]:
        _fail("completed terminal proof lacks closed fee/charge id")
    if terminal.get("parent_reservation_released") is not True:
        _fail("completed terminal proof lacks resource release")
    if terminal.get("repeat_fee_idempotent") is not True:
        _fail("completed terminal proof lacks repeat/idempotence check")
    refs = _strict_top_refs(terminal)
    _strict_receipt_identity(terminal, refs)

def _load_base(
    path: Path,
    lifecycle_plan_path: Path | None = None,
    current_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    document, ref = _json(path, "previous V10-compatible overlay")
    if document.get("schema") != OVERLAY_SCHEMA:
        _fail(f"previous scope schema is not V10-compatible: {document.get('schema')}")
    try:
        inventory = v6._base_inventory(path)
    except Exception as exc:
        raise TerminalOverlayError(f"previous V10 scope preflight failed: {exc}") from exc
    if (lifecycle_plan_path is None) != (current_path is None):
        _fail("lifecycle plan and CURRENT336 must be supplied together")
    if lifecycle_plan_path is not None and current_path is not None:
        try:
            scoped, _ = v6._load_scope_v5(path, lifecycle_plan_path, current_path)
        except Exception as exc:
            raise TerminalOverlayError(f"CURRENT336/lifecycle-plan alias preflight failed: {exc}") from exc
        aliases = set(scoped.get("aliases", set()))
        if not aliases.issubset(inventory["ids"]):
            _fail("CURRENT336/lifecycle-plan alias is outside the previous V10 scope")
        if aliases & inventory["existing"]:
            _fail("CURRENT336/lifecycle-plan alias is already an actual join")
        original_bound = set(inventory["bound"])
        original_unresolved = set(inventory["unresolved"])
        # The arithmetic V10 scope counts the historical alias as cause-bound,
        # while the current canonical plan requires it to remain a separate
        # unresolved identity.  Keep both ledgers explicit.
        inventory["bound"] = original_bound - aliases
        inventory["unresolved"] = original_unresolved - aliases
        inventory["aliases"] = set(inventory.get("aliases", set())) | aliases
        inventory["_historical_bound_count"] = int(
            document.get("historical_native_cause_bound_per_fluid_id_cases", len(original_bound))
        )
        inventory["_current336_plan_ref"] = v6._json_ref(
            {"path": str(lifecycle_plan_path.expanduser().resolve())}, "V4 lifecycle plan binding"
        )[1]
        inventory["_current336_ref"] = v6._json_ref(
            {"path": str(current_path.expanduser().resolve())}, "V4 CURRENT336 binding"
        )[1]
    else:
        inventory["_historical_bound_count"] = int(
            document.get("historical_native_cause_bound_per_fluid_id_cases", len(inventory["bound"]))
        )
    return document, ref, inventory


def _classify_candidates(inventory: dict[str, Any], ids: set[str]) -> tuple[set[str], set[str]]:
    if ids & inventory["existing"]:
        _fail("terminal proof repeats an existing actual join")
    if ids & inventory["aliases"]:
        _fail("terminal proof attempts historical alias substitution")
    allowed = inventory["bound"] | inventory["unresolved"]
    if not ids.issubset(allowed):
        _fail("terminal proof contains a case outside the previous V10 scope")
    new_cause = ids & inventory["unresolved"]
    typed_only = ids & (inventory["bound"] - inventory["existing"])
    return new_cause, typed_only


def _canonical_base_scope(
    base: dict[str, Any],
    source_base_ref: dict[str, Any],
    inventory: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Materialize a canonical SCOPE_SCHEMA parent when the plan has an alias.

    A top-level V10 overlay cannot attach ``unresolved_alias_case_ids`` while
    still pointing directly at the arithmetic V10 parent: the V6 inventory
    validator would correctly see the alias in both ``bound`` and ``aliases``.
    This tiny, source-bound parent partitions the same 118 identities into
    canonical bound/unresolved/alias classes and leaves the original V10 ref
    visible for audit.  It contains no trajectory/native payload.
    """
    aliases = set(inventory.get("aliases", set()))
    if not aliases:
        return source_base_ref
    canonical_path = output_path.with_name(output_path.stem + "-canonical-base-scope.json")
    if canonical_path.exists() or canonical_path.is_symlink():
        _fail(f"refusing to overwrite canonical base scope: {canonical_path}")
    rows = []
    for case_id in sorted(inventory["ids"]):
        if case_id in aliases:
            classification = "HISTORICAL_ALIAS_UNRESOLVED"
        elif case_id in inventory["bound"]:
            classification = "NATIVE_CAUSE_BOUND_PER_FLUID_ID"
        elif case_id in inventory["unresolved"]:
            classification = "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN"
        else:
            _fail(f"canonical base scope lost case identity: {case_id}")
        rows.append({"physical_case_id": case_id, "classification": classification})
    document = {
        "schema": v6.SCOPE_SCHEMA,
        "status": "SOURCE_BOUND_CANONICAL_CURRENT336_ALIAS_PARTITION",
        "source_arithmetic_v10_scope": source_base_ref,
        "current336": {
            "plan": inventory.get("_current336_plan_ref"),
            "catalog": inventory.get("_current336_ref"),
            "alias_ids": sorted(aliases),
        },
        "scope": {"unresolved_alias_case_ids": sorted(aliases)},
        "case_rows": rows,
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_bytes((json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return _ref(canonical_path, "canonical CURRENT336 base scope")


def _no_join_overlay(base: dict[str, Any], base_ref: dict[str, Any], source_base_ref: dict[str, Any], inventory: dict[str, Any], terminal_ref: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema": OVERLAY_SCHEMA,
        "status": "ROOT_TERMINAL_NOT_ADMITTED_NO_JOIN",
        "base_scope": base_ref,
        "source_arithmetic_v10_scope": source_base_ref,
        "actual_join_proofs": list(base.get("actual_join_proofs", [])),
        "physical_case_count": base.get("physical_case_count"),
        "native_cause_bound_per_fluid_id_cases": len(inventory["bound"]),
        "historical_native_cause_bound_per_fluid_id_cases": inventory.get("_historical_bound_count", len(inventory["bound"])),
        "cause_not_located_after_completed_scan_cases": len(inventory["unresolved"]),
        "actual_typed_native_saved_frame_join_physical_cases": base.get("actual_typed_native_saved_frame_join_physical_cases"),
        "newly_bound_cases": [],
        "remaining_cause_not_located_case_ids": list(base.get("remaining_cause_not_located_case_ids", [])),
        "unresolved_alias_case_ids": sorted(inventory.get("aliases", set())),
        "current336_lifecycle": {"plan": inventory.get("_current336_plan_ref"), "catalog": inventory.get("_current336_ref")},
        "terminal_proof": terminal_ref,
        "terminal_admission": {"status": "NO_JOIN", "reason": reason},
        "claim_boundary": {"native_cause_credit": "NONE", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build(
    base_scope_path: Path,
    terminal_proof_path: Path,
    output_path: Path,
    lifecycle_plan_path: Path | None = None,
    current_path: Path | None = None,
    *,
    allow_fixture_context: bool = False,
) -> dict[str, Any]:
    if lifecycle_plan_path is None and current_path is None and not allow_fixture_context:
        _fail("production V4 admission requires exact CURRENT336 and lifecycle-plan bindings")
    base, base_ref, inventory = _load_base(base_scope_path, lifecycle_plan_path, current_path)
    canonical_base_ref = _canonical_base_scope(base, base_ref, inventory, output_path)
    terminal, terminal_ref = _json(terminal_proof_path, "root terminal proof")
    terminal_state = _terminal_state(terminal)
    if terminal_state == "FAILED_OR_PARTIAL":
        overlay = _no_join_overlay(base, canonical_base_ref, base_ref, inventory, terminal_ref, "terminal execution failed/partial; actual proof withheld")
        result_status = overlay["status"]
    else:
        _require_completed_accounting(terminal)
        proof_value = terminal.get("actual_join_proof") or terminal.get("native_join_proof") or terminal.get("join_proof")
        if not isinstance(proof_value, dict):
            _fail("root terminal proof lacks an exact actual_join_proof reference")
        proof, proof_ref, proof_ids = _proof_ref(proof_value, "root terminal actual_join_proof")
        declared_ids = terminal.get("selected_case_ids")
        if (
            not isinstance(declared_ids, list)
            or not declared_ids
            or any(not isinstance(case_id, str) or not case_id for case_id in declared_ids)
            or len(declared_ids) != len(set(declared_ids))
            or set(declared_ids) != proof_ids
        ):
            _fail("root terminal selected_case_ids are not the exact actual_join_proof rows")
        if proof.get("schema") not in STRICT_JOIN_PROOF_SCHEMAS:
            _fail(f"actual_join_proof schema is unsupported: {proof.get('schema')!r}")
        proof_status = proof.get("status")
        if not isinstance(proof_status, str) or not proof_status.startswith("VERIFIED_ACTUAL_"):
            _fail("actual_join_proof is not an actual verified root proof")
        if proof.get("root_native_H5_or_large_JSONL_content_read") is True:
            # This is a provenance warning rather than a scientific rejection;
            # the native proof must still be root-owned and closed.  Keeping the
            # field visible avoids silently treating a content-read proof as a
            # metadata-only claim.
            pass
        new_cause, typed_only = _classify_candidates(inventory, proof_ids)
        proof_rows, _ = _case_rows(proof, "root terminal actual_join_proof")
        proof_counts = proof.get("counts")
        if isinstance(proof_counts, dict) and (proof_counts.get("failed") not in (None, 0) or proof_counts.get("completed") not in (None, len(proof_rows))):
            _fail("root terminal actual_join_proof counts include incomplete rows")
        incomplete_statuses = {"FAILED", "FAILED_NO_JOIN_CREDIT", "PARTIAL", "PENDING", "UNKNOWN"}
        if any(isinstance(row.get("status"), str) and (row.get("status") in incomplete_statuses or any(token in row["status"].upper() for token in ("FAILED", "PARTIAL", "PENDING", "TIMEOUT", "CANCEL"))) for row in proof_rows):
            _fail("completed root terminal actual_join_proof contains failed case rows")
        actual_refs = list(base.get("actual_join_proofs", []))
        if not isinstance(actual_refs, list) or not actual_refs:
            _fail("previous V10 scope lacks actual_join_proofs")
        actual_refs.append(proof_ref)
        existing_join_count = base.get("actual_typed_native_saved_frame_join_physical_cases")
        if isinstance(existing_join_count, bool) or not isinstance(existing_join_count, int):
            _fail("previous V10 scope join count is malformed")
        rows = []
        for row in proof_rows:
            case_id = row["physical_case_id"]
            if case_id in new_cause:
                rows.append({"physical_case_id": case_id, "previous_classification": "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN", "classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID", "evidence": terminal_ref["path"], "evidence_sha256": terminal_ref["sha256"], "saved_frame_join": "VERIFIED_BY_ROOT_TERMINAL_PROOF", "native_cause_credit": "NEW_CASE_ALLOWED"})
            elif case_id in typed_only:
                rows.append({"physical_case_id": case_id, "previous_classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID", "classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID", "evidence": terminal_ref["path"], "evidence_sha256": terminal_ref["sha256"], "saved_frame_join": "VERIFIED_BY_ROOT_TERMINAL_PROOF", "native_cause_credit": "NONE_ALREADY_BOUND"})
            else:
                _fail(f"terminal case classification is incomplete: {case_id}")
        newly_bound = list(base.get("newly_bound_cases", [])) + [row for row in rows if row["native_cause_credit"] == "NEW_CASE_ALLOWED"]
        remaining = sorted(set(base.get("remaining_cause_not_located_case_ids", [])) - new_cause)
        bound = set(inventory["bound"]) | new_cause
        overlay = {
            "schema": OVERLAY_SCHEMA,
            "status": "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY",
            "base_scope": canonical_base_ref,
            "source_arithmetic_v10_scope": base_ref,
            "actual_join_proofs": actual_refs,
            "physical_case_count": len(inventory["ids"]),
            "native_cause_bound_per_fluid_id_cases": len(bound),
            "historical_native_cause_bound_per_fluid_id_cases": inventory.get("_historical_bound_count", len(inventory["bound"])) + len(new_cause),
            "cause_not_located_after_completed_scan_cases": len(remaining),
            "actual_typed_native_saved_frame_join_physical_cases": existing_join_count + len(proof_ids),
            "newly_bound_cases": newly_bound,
            "remaining_cause_not_located_case_ids": remaining,
            "unresolved_alias_case_ids": sorted(inventory.get("aliases", set())),
            "current336_lifecycle": {"plan": inventory.get("_current336_plan_ref"), "catalog": inventory.get("_current336_ref")},
            "root_terminal_proof": terminal_ref,
            "terminal_join_proof": proof_ref,
            "terminal_admission": {"status": "ADMITTED", "new_cause_case_ids": sorted(new_cause), "already_cause_bound_join_only_case_ids": sorted(typed_only), "failed_case_ids": []},
            "qualification_boundary": {"native_id_join": "VERIFIED_PER_ROOT_TERMINAL_PROOF_ROWS", "new_native_cause_credit": "ONLY_UNRESOLVED_ROWS_IN_THIS_TERMINAL_PROOF", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "claim_boundary": {"native_cause_credit": "PER_EXPLICIT_ROOT_TERMINAL_ROWS_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        result_status = overlay["status"]
    if output_path.exists() or output_path.is_symlink():
        _fail(f"refusing to overwrite output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(overlay, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_JSON:
        _fail("rolling overlay output exceeds bounded metadata size")
    output_path.write_bytes(encoded)
    output_ref = _ref(output_path, "rolling overlay output")
    return {"schema": OUTPUT_SCHEMA, "status": result_status, "output": output_ref, "new_join_count": len(overlay.get("terminal_admission", {}).get("new_cause_case_ids", [])) + len(overlay.get("terminal_admission", {}).get("already_cause_bound_join_only_case_ids", [])), "new_native_cause_count": len(overlay.get("terminal_admission", {}).get("new_cause_case_ids", [])), "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-scope", type=Path, required=True)
    parser.add_argument("--terminal-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lifecycle-plan", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = build(args.base_scope, args.terminal_proof, args.output, args.lifecycle_plan, args.current)
    except (TerminalOverlayError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_OVERLAY_TERMINAL_V3_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
