#!/usr/bin/env python3
"""Source-only authorizer for the DS-DATA-02 Stage 1 visual production path.

This module is deliberately separate from ``ds_data02_production``.  It does
not grant Q-N, does not run a scientific verifier, and does not modify the
consumed runner.  A root-owned ``APPROVED_VISUAL_SCOPES.json`` supplies the
selected visual decision and the frozen case manifest.  The shared runtime
still owns resource reservations, UUID leases, execution, monitoring, and
receipt creation.

The module is installed by ``ds_data02_stage1_dispatch_v1`` only for an
explicit ``visual_stage_profile == "stage1_visual"`` production request.  An
ordinary qualification/production request continues to use the legacy module
through the legacy strict dispatcher.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, MutableMapping


CAMPAIGN_ID = "DS-DATA-02"
SCHEMA = "ds02.root-approved-visual-scopes.v1"
VISUAL_STAGE_PROFILE = "stage1_visual"
NUMERICAL_PRECISION_STATUS = "not_accepted"
PRECISION_CONTEXT = "pending"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MISSING = object()

# The integration worktree owns the real index.  This source package contains
# no index or grant.  Tests and root integration should pass ``index_path``
# explicitly; the environment variable is useful for the installed adapter.
INDEX = Path(
    os.environ.get(
        "DS_DATA02_APPROVED_VISUAL_SCOPES",
        "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
        "lagrangian-fluid-lab/campaigns/ds-data-02/APPROVED_VISUAL_SCOPES.json",
    )
)


class VisualAuthorizationError(ValueError):
    """Raised when a visual-stage request or root decision is not eligible."""


def digest(path: os.PathLike[str] | str) -> str:
    """Return the SHA-256 of one source/evidence file."""

    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _parse_json(raw: str | bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise VisualAuthorizationError("duplicate JSON field: " + key)
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique)
    except json.JSONDecodeError as error:
        raise VisualAuthorizationError(f"invalid JSON: {error}") from error


def _read_json(path: os.PathLike[str] | str) -> Any:
    return _parse_json(Path(path).read_text(encoding="utf-8"))


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entry_digest(entry: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(entry).encode("utf-8")).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise VisualAuthorizationError(f"{label} must contain a lowercase SHA-256")
    return value


def _resolve_binding_path(path: str, *, base: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _binding(
    value: Any,
    label: str,
    hashes: MutableMapping[str, str],
    *,
    base: Path,
    require_file: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Validate and hash an auditable path/sha256 binding.

    The mutable approval index itself is intentionally never passed here.  It
    is read and revalidated separately, while all selected evidence is frozen
    into the launch hash map returned to the runtime.
    """

    if not isinstance(value, Mapping):
        raise VisualAuthorizationError(f"{label} must be a path/sha256 binding")
    raw_path = value.get("path")
    expected = _sha(value.get("sha256"), f"{label}.sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise VisualAuthorizationError(f"{label}.path is required")
    path = _resolve_binding_path(raw_path, base=base)
    if require_file and not path.is_file():
        raise VisualAuthorizationError(f"{label} file is missing: {path}")
    actual = digest(path)
    if actual != expected:
        raise VisualAuthorizationError(f"{label} hash mismatch: {path}")
    hashes[str(path)] = actual
    return path, {"path": str(path), "sha256": actual}


def _optional_binding(
    value: Any,
    label: str,
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> tuple[Path, dict[str, Any]] | None:
    if value is None:
        return None
    return _binding(value, label, hashes, base=base)


def _json_binding(
    value: Any,
    label: str,
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> tuple[Path, dict[str, Any], Any]:
    path, binding = _binding(value, label, hashes, base=base)
    try:
        document = _read_json(path)
    except (OSError, UnicodeError) as error:
        raise VisualAuthorizationError(f"{label} must be readable JSON: {path}") from error
    return path, binding, document


def _binding_from(entry: Mapping[str, Any], name: str) -> Any:
    """Read a binding from the explicit entry field or its ``bindings`` map."""

    if name in entry:
        return entry[name]
    bindings = entry.get("bindings")
    if isinstance(bindings, Mapping) and name in bindings:
        return bindings[name]
    return None


def _required_binding_from(
    entry: Mapping[str, Any],
    names: tuple[str, ...],
    label: str,
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> tuple[Path, dict[str, Any]]:
    for name in names:
        value = _binding_from(entry, name)
        if value is not None:
            return _binding(value, label, hashes, base=base)
    raise VisualAuthorizationError(f"{label} binding is required")


def _read_json_document(path: Path, label: str) -> Any:
    try:
        return _read_json(path)
    except (OSError, UnicodeError) as error:
        raise VisualAuthorizationError(f"{label} is not readable JSON: {path}") from error


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VisualAuthorizationError(f"{label} must be an object")
    return value


def _require_true(document: Mapping[str, Any], keys: tuple[str, ...], label: str) -> None:
    checks = document.get("checks")
    if isinstance(checks, Mapping):
        source: Mapping[str, Any] = checks
    else:
        source = document
    for key in keys:
        if source.get(key) is not True:
            raise VisualAuthorizationError(f"{label} check failed or is missing: {key}")


def _require_finite_positive(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisualAuthorizationError(f"{label} must be finite and positive")
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise VisualAuthorizationError(f"{label} must be finite and positive")


def _ensure_visual_decision(
    decision: Mapping[str, Any], *, family_id: str, case_id: str, scope_id: str | None = None
) -> None:
    if decision.get("schema") != "ds02.stage1.root-visual-case-decision.v1":
        raise VisualAuthorizationError("visual decision has the wrong schema")
    if decision.get("status") != "visual-approved-by-root":
        raise VisualAuthorizationError("root visual decision is not approved")
    if decision.get("family_id") != family_id:
        raise VisualAuthorizationError("visual decision family differs from selected case")
    decision_case_ids = decision.get("case_ids", decision.get("approved_case_ids"))
    selected_case_matches = decision.get("case_id") == case_id
    if isinstance(decision_case_ids, list):
        selected_case_matches = selected_case_matches or case_id in decision_case_ids
    if decision.get("scope_id") is not None and scope_id is not None:
        selected_case_matches = selected_case_matches or decision.get("scope_id") == scope_id
    if not selected_case_matches:
        raise VisualAuthorizationError("visual decision identity differs from selected case")
    if decision.get("stage1_label") != "视觉检查通过、数值精度未验收":
        raise VisualAuthorizationError("visual decision must retain the Stage 1 precision label")
    if decision.get("production_scope_approval") is not False:
        raise VisualAuthorizationError("visual decision cannot grant a numerical production scope")
    if decision.get("numerical_precision_status") != NUMERICAL_PRECISION_STATUS:
        raise VisualAuthorizationError("visual decision numerical precision is not pending")
    if decision.get("q_n") not in {"not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual decision must not claim Q-N")
    if decision.get("q_e") not in {"not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual decision must not claim Q-E")
    for key in ("physical_case_id", "physical_condition_sha256", "physical_window_s"):
        if key not in decision:
            raise VisualAuthorizationError(f"visual decision lacks {key}")
    window = decision.get("physical_window_s")
    if not isinstance(window, list) or len(window) != 2 or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
        for item in window
    ) or window[1] <= window[0]:
        raise VisualAuthorizationError("visual decision physical window is invalid")


def _validate_goal_binding(
    value: Any,
    *,
    base: Path,
    expected_path: Path | None = None,
    expected_sha: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    path, binding = _binding(value, "goal_authority", {}, base=base)
    if expected_path is not None and path != expected_path:
        raise VisualAuthorizationError("scope goal authority path differs from index authority")
    if expected_sha is not None and binding["sha256"] != expected_sha:
        raise VisualAuthorizationError("scope goal authority hash differs from index authority")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "Stage1" not in text and "stage1" not in text and "视觉" not in text:
        raise VisualAuthorizationError("goal authority is not the updated Stage 1 visual goal")
    return path, binding


def _visual_evidence_bindings(
    entry: Mapping[str, Any],
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = entry.get("visual_evidence")
    if evidence is None:
        evidence = entry.get("evidence")
    evidence = _require_mapping(evidence, "visual_evidence")
    result: dict[str, Any] = {}
    all_bindings: list[dict[str, Any]] = []

    def many(name: str, aliases: tuple[str, ...]) -> None:
        value = None
        for alias in aliases:
            if alias in evidence:
                value = evidence[alias]
                break
        if not isinstance(value, list) or not value:
            raise VisualAuthorizationError(f"visual evidence requires non-empty {name}")
        rows = []
        for index, item in enumerate(value):
            _, binding = _binding(item, f"visual_evidence.{name}[{index}]", hashes, base=base)
            rows.append(binding)
            all_bindings.append(binding)
        result[name] = rows

    many("mother", ("mother", "mother_case", "mother_evidence"))
    many("endpoints", ("endpoints", "endpoint_cases", "endpoint_evidence"))
    many("interior", ("interior", "interior_cases", "interior_evidence"))

    final_value = None
    for alias in ("final_visualization_decision", "final_visual_decision", "decision"):
        if alias in evidence:
            final_value = evidence[alias]
            break
    if final_value is None:
        final_value = _binding_from(entry, "final_visualization_decision")
    if final_value is None:
        raise VisualAuthorizationError("final visualization decision binding is required")
    _, result["final_visualization_decision"] = _binding(
        final_value, "final_visualization_decision", hashes, base=base
    )
    all_bindings.append(result["final_visualization_decision"])

    integrity_value = None
    for alias in ("integrity", "animation_integrity", "full_saved_frames", "saved_frames"):
        if alias in evidence:
            integrity_value = evidence[alias]
            break
    if integrity_value is None:
        raise VisualAuthorizationError("full saved-frame visual integrity binding is required")
    _, result["integrity"] = _binding(integrity_value, "visual_evidence.integrity", hashes, base=base)
    all_bindings.append(result["integrity"])
    return result, all_bindings


def _case_rows(document: Mapping[str, Any], label: str) -> list[Mapping[str, Any]]:
    rows = document.get("cases")
    if not isinstance(rows, list) or not rows:
        raise VisualAuthorizationError(f"{label}.cases must be a non-empty list")
    return [_require_mapping(row, f"{label}.cases[{index}]") for index, row in enumerate(rows)]


def _parameter_tuple(row: Mapping[str, Any], label: str) -> str:
    value = _parameter_value(row)
    if value is None:
        raise VisualAuthorizationError(f"{label} lacks a frozen physical parameter_tuple")
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, Mapping)):
        raise VisualAuthorizationError(f"{label}.parameter_tuple must be structured physical values")
    # Parameter tuples identify physical conditions.  A time/DP/save alias is
    # never a physical tuple and would permit counting a view as a new case.
    if isinstance(value, Mapping):
        forbidden = {"dp", "dp_id", "time", "time_s", "dt", "save", "save_id", "frame", "resolution", "alias"}
        if forbidden.intersection(str(key).lower() for key in value):
            raise VisualAuthorizationError(f"{label}.parameter_tuple contains a DP/time/view alias")
    return _canonical(value)


def _parameter_value(row: Mapping[str, Any]) -> Any:
    value = row.get("parameter_tuple")
    if value is None:
        value = row.get("physical_parameter_tuple")
    if value is None:
        value = row.get("parameter_values")
    return value


def _validate_unique_physical_rows(rows: list[Mapping[str, Any]], label: str) -> None:
    seen_case: set[str] = set()
    seen_physical: set[str] = set()
    seen_tuple: set[str] = set()
    for index, row in enumerate(rows):
        prefix = f"{label}.cases[{index}]"
        for key, seen, text in (
            ("case_id", seen_case, "case_id"),
            ("physical_case_id", seen_physical, "physical_case_id"),
        ):
            value = row.get(key)
            if not isinstance(value, str) or not value:
                raise VisualAuthorizationError(f"{prefix}.{text} is required")
            if value in seen:
                raise VisualAuthorizationError(f"{label} duplicates {text}: {value}")
            seen.add(value)
        tuple_key = _parameter_tuple(row, prefix)
        if tuple_key in seen_tuple:
            raise VisualAuthorizationError(f"{label} duplicates a physical parameter tuple")
        seen_tuple.add(tuple_key)
        if row.get("alias_of") is not None or row.get("derived_from") is not None:
            raise VisualAuthorizationError(f"{prefix} is an alias/view rather than an independent physical case")


def _same(left: Any, right: Any, label: str) -> None:
    if left != right:
        raise VisualAuthorizationError(f"{label} differs from the frozen approved value")


def _select_initial_qa_document(raw: Any, case: Mapping[str, Any]) -> Mapping[str, Any]:
    """Select a case row from a shared/native initial-QA report when needed."""

    if not isinstance(raw, Mapping):
        raise VisualAuthorizationError("initial-state QA must be an object")
    rows = raw.get("cases")
    if not isinstance(rows, list):
        return raw
    target = case.get("initial_qa_case_id", case.get("case_id"))
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == target]
    if len(matches) != 1:
        raise VisualAuthorizationError("initial-state QA does not contain the selected case row")
    selected = dict(raw)
    selected.pop("cases", None)
    selected.update(matches[0])
    return selected


def _actual_case_bindings(
    case: Mapping[str, Any],
    request: Mapping[str, Any],
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> dict[str, Any]:
    """Hash and validate the actual visual-stage input/initial-state evidence."""

    raw_inputs = case.get("input_bindings")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise VisualAuthorizationError("case input_bindings are required")
    inputs: list[dict[str, Any]] = []
    input_paths: set[Path] = set()
    for index, item in enumerate(raw_inputs):
        path, binding = _binding(item, f"case.input_bindings[{index}]", hashes, base=base)
        inputs.append(binding)
        input_paths.add(path)
    request_input_paths = {Path(value).resolve() for value in request.get("input_files", []) if isinstance(value, str)}
    if not input_paths.issubset(request_input_paths):
        raise VisualAuthorizationError("request input_files omit a frozen case input")

    gen_value = case.get("gencase_receipt")
    if gen_value is None:
        gen_value = case.get("actual_gencase_receipt")
    gen_path, gen_binding, gen = _json_binding(gen_value, "case.gencase_receipt", hashes, base=base)
    if gen.get("status") != "completed" or gen.get("returncode", gen.get("gencase_returncode")) != 0:
        raise VisualAuthorizationError("GenCase evidence is not an actual successful run")
    if gen.get("solver_dimension_from_gencase") != 3:
        raise VisualAuthorizationError("GenCase evidence is not actual 3D")
    total = gen.get("total_particles")
    fluid = gen.get("fluid_particles")
    if not isinstance(total, int) or total <= 0 or not isinstance(fluid, int) or fluid <= 0 or fluid > total:
        raise VisualAuthorizationError("GenCase evidence lacks positive actual particle counts")
    if gen.get("input_hashes_at_launch") != gen.get("input_hashes_after_run"):
        raise VisualAuthorizationError("GenCase input provenance changed during its run")
    gen_inputs = gen.get("input_hashes_at_launch")
    if not isinstance(gen_inputs, Mapping):
        raise VisualAuthorizationError("GenCase input provenance is missing")
    for raw_path, expected_hash in gen_inputs.items():
        path = Path(str(raw_path)).resolve()
        matching = next((item for item in inputs if Path(item["path"]).resolve() == path), None)
        if matching is None or matching["sha256"] != expected_hash:
            raise VisualAuthorizationError("GenCase input provenance differs from frozen case inputs")
    command = gen.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
        raise VisualAuthorizationError("GenCase command provenance is missing")

    qa_value = case.get("initial_state_qa")
    if qa_value is None:
        qa_value = case.get("initialization_qa")
    qa_path, qa_binding, raw_qa = _json_binding(qa_value, "case.initial_state_qa", hashes, base=base)
    qa = _select_initial_qa_document(raw_qa, case)
    qa_checks = qa.get("checks") if isinstance(qa.get("checks"), Mapping) else qa
    if qa_checks.get("actual_3d") is not True:
        raise VisualAuthorizationError("initial-state QA check failed or is missing: actual_3d")
    positive = qa_checks.get("positive_fluid_particles") is True
    if not positive:
        positive = any(
            isinstance(qa_checks.get(key), int) and qa_checks.get(key) > 0
            for key in ("fluid_particles", "native_fluid")
        )
    if not positive:
        raise VisualAuthorizationError("initial-state QA lacks positive fluid particles")
    if qa_checks.get("finite_state") is not True and qa_checks.get("passed") is not True:
        raise VisualAuthorizationError("initial-state QA check failed or is missing: finite_state")
    clone_equal = any(
        source.get(key) is True
        for source in (qa_checks, qa, case)
        for key in ("equivalent_clone", "clone_initial_byte_equality", "initial_bytes_equal_to_parent")
    )
    if not clone_equal:
        clone_value = case.get("equivalent_clone_qa")
        if clone_value is not None:
            _, clone_binding, clone_document = _json_binding(
                clone_value, "case.equivalent_clone_qa", hashes, base=base
            )
            clone_checks = clone_document.get("checks") if isinstance(clone_document.get("checks"), Mapping) else clone_document
            clone_equal = any(
                source.get(key) is True
                for source in (clone_checks, clone_document)
                for key in ("equivalent_clone", "clone_initial_byte_equality", "initial_bytes_equal_to_parent")
            )
    if not clone_equal:
        raise VisualAuthorizationError("initial-state QA lacks equivalent clone byte-equality evidence")
    initial_bytes = qa.get("actual_initial_bytes")
    if initial_bytes is None:
        initial_bytes = qa.get("initial_bytes")
    if initial_bytes is None:
        initial_bytes = case.get("initial_bytes", case.get("initial_input_bindings"))
    if initial_bytes is None and isinstance(qa.get("native_initial_BI4_sha256"), str):
        initial_bytes = [
            item
            for item in raw_inputs
            if isinstance(item, Mapping) and item.get("sha256") == qa["native_initial_BI4_sha256"]
        ]
    if not isinstance(initial_bytes, list) or not initial_bytes:
        raise VisualAuthorizationError("initial-state QA lacks genuine actual initial bytes")
    byte_bindings = []
    initial_byte_paths: set[Path] = set()
    for index, item in enumerate(initial_bytes):
        path, binding = _binding(item, f"initial_state_qa.initial_bytes[{index}]", hashes, base=base)
        byte_bindings.append(binding)
        initial_byte_paths.add(path)
    if not initial_byte_paths.issubset(request_input_paths):
        raise VisualAuthorizationError("request input_files omit genuine initial bytes")
    provenance = qa.get("provenance")
    if not isinstance(provenance, Mapping):
        raise VisualAuthorizationError("initial-state QA provenance is required")
    _same(provenance.get("gencase_receipt"), gen_binding, "initial-state QA GenCase binding")
    qa_input_bindings = provenance.get("input_bindings")
    if qa_input_bindings != inputs:
        raise VisualAuthorizationError("initial-state QA input provenance differs from the manifest")
    _same(request.get("gencase_receipt"), str(gen_path), "request GenCase receipt")
    request_gen_hash = request.get("gencase_receipt_sha256")
    if request_gen_hash is not None:
        _same(request_gen_hash, gen_binding["sha256"], "request GenCase receipt hash")

    mass_value = case.get("initial_mass_discrepancy_report")
    if mass_value is None:
        mass_value = case.get("mass_discrepancy_report")
    mass_path, mass_binding, mass = _json_binding(
        mass_value, "case.initial_mass_discrepancy_report", hashes, base=base
    )
    if not isinstance(mass, Mapping) or not mass:
        raise VisualAuthorizationError("initial mass discrepancy report must be preserved")
    # The report is evidence to carry forward, never a precision gate.  A
    # producer may not silently rescale the state, however.
    for source in (case, qa, mass, request):
        if source.get("mass_rescaling") is True or source.get("mass_rescaled") is True:
            raise VisualAuthorizationError("initial mass rescaling is forbidden")

    # Physics, geometry, motion and finite/no-overlap evidence are explicit
    # visual integrity inputs.  No spatial convergence, time-step, save-rate,
    # macro, or external-validation gate is evaluated here.
    evidence_bindings: dict[str, dict[str, Any]] = {}
    evidence_specs = (
        ("physics_evidence", ("physics_evidence", "physics"), ("finite_state",)),
        ("geometry_evidence", ("geometry_evidence", "geometry"), ("finite_state",)),
        ("motion_evidence", ("motion_evidence", "motion"), ("finite_state",)),
        (
            "no_overlap_finite_state_evidence",
            ("no_overlap_finite_state_evidence", "finite_state_evidence", "integrity_evidence"),
            ("finite_state", "no_initial_fluid_solid_overlap"),
        ),
    )
    for label, names, checks in evidence_specs:
        value = None
        for name in names:
            value = case.get(name)
            if value is not None:
                break
        path, binding, document = _json_binding(value, f"case.{label}", hashes, base=base)
        _require_true(document, checks, label)
        evidence_bindings[label] = binding

    return {
        "input_bindings": inputs,
        "gencase_receipt": gen_binding,
        "gencase_document": gen,
        "initial_state_qa": qa_binding,
        "initial_state_qa_document": qa,
        "initial_bytes": byte_bindings,
        "initial_mass_discrepancy_report": mass_binding,
        "initial_mass_discrepancy_document": mass,
        "integrity_evidence": evidence_bindings,
    }


def _source_module_path(module_name: str) -> Path:
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise VisualAuthorizationError(f"required consumed module is not importable: {module_name}") from error
    path = getattr(module, "__file__", None)
    if not path:
        raise VisualAuthorizationError(f"required consumed module has no source path: {module_name}")
    return Path(path).resolve()


def _registered_source_bindings(
    request: Mapping[str, Any],
    hashes: MutableMapping[str, str],
) -> dict[str, str]:
    """Require the new adapter/authorizer and consumed strict/runtime bytes."""

    adapter_value = request.get("visual_stage_adapter_path")
    if not isinstance(adapter_value, str) or not adapter_value:
        raise VisualAuthorizationError("visual_stage_adapter_path is required")
    adapter = Path(adapter_value).resolve()
    if not adapter.is_file():
        raise VisualAuthorizationError("visual stage adapter source is missing")
    strict = _source_module_path("ds_data02_strict_dispatch_v1")
    runtime = _source_module_path("ds_data02_runtime_v2")
    authorizer = Path(__file__).resolve()
    required = {
        "visual_stage_adapter": adapter,
        "visual_stage_authorizer": authorizer,
        "consumed_strict_dispatch": strict,
        "consumed_runtime": runtime,
    }
    request_files = {Path(value).resolve() for value in request.get("input_files", []) if isinstance(value, str)}
    expected_maps: list[Mapping[str, Any]] = []
    for key in ("input_sha256", "input_hashes"):
        value = request.get(key)
        if value is not None:
            if not isinstance(value, Mapping):
                raise VisualAuthorizationError(f"{key} must be a path/hash map")
            expected_maps.append(value)
    expected: dict[Path, str] = {}
    for mapping in expected_maps:
        for raw_path, value in mapping.items():
            path = Path(str(raw_path)).resolve()
            value = _sha(value, f"{key}[{path}]")
            if path in expected and expected[path] != value:
                raise VisualAuthorizationError("conflicting registered source digest: " + str(path))
            expected[path] = value
    if not expected_maps:
        raise VisualAuthorizationError("registered source digests are required")
    for label, path in required.items():
        if path not in request_files:
            raise VisualAuthorizationError(f"request input_files omit {label}: {path}")
        if path not in expected:
            raise VisualAuthorizationError(f"registered source digest missing for {label}: {path}")
        actual = digest(path)
        if expected[path] != actual:
            raise VisualAuthorizationError(f"registered source digest differs for {label}: {path}")
        hashes[str(path)] = actual
    return {label: str(path) for label, path in required.items()}


def _validate_index(index: Mapping[str, Any]) -> None:
    if index.get("schema") != SCHEMA or index.get("campaign_id") != CAMPAIGN_ID:
        raise VisualAuthorizationError("invalid APPROVED_VISUAL_SCOPES schema or campaign")
    if not isinstance(index.get("scopes"), list):
        raise VisualAuthorizationError("APPROVED_VISUAL_SCOPES.scopes must be a list")
    if index.get("interpretation") and "visual" not in str(index["interpretation"]).lower():
        raise VisualAuthorizationError("visual index interpretation must remain visual-only")
    if any(key in index for key in ("q_n", "q_n_status", "numerical_approval")):
        raise VisualAuthorizationError("visual index cannot carry a fake Q-N grant")
    goal = index.get("goal_authority", index.get("goal_binding", index.get("goal")))
    if goal is None:
        goal = index.get("goal")
    if goal is None:
        raise VisualAuthorizationError("visual index goal_authority binding is required")
    if not isinstance(goal, Mapping):
        raise VisualAuthorizationError("visual index goal_authority must be a binding")


def _find_entry(index: Mapping[str, Any], request: Mapping[str, Any]) -> Mapping[str, Any]:
    family_id = request.get("family_id")
    scope_id = request.get("scope_id")
    matches = [
        item
        for item in index.get("scopes", [])
        if isinstance(item, Mapping)
        and item.get("family_id") == family_id
        and item.get("scope_id") == scope_id
    ]
    if len(matches) != 1:
        raise VisualAuthorizationError("visual production scope is not uniquely approved")
    return matches[0]


def _validate_scope(
    request: Mapping[str, Any],
    entry: Mapping[str, Any],
    index: Mapping[str, Any],
    index_path: Path,
    hashes: MutableMapping[str, str],
) -> dict[str, Any]:
    family_id = request.get("family_id")
    scope_id = request.get("scope_id")
    if entry.get("visual_stage_profile") not in {None, VISUAL_STAGE_PROFILE}:
        raise VisualAuthorizationError("scope is not explicitly a Stage 1 visual profile")
    if request.get("visual_stage_profile") != VISUAL_STAGE_PROFILE:
        raise VisualAuthorizationError("request lacks explicit stage1_visual profile")
    if entry.get("q_n") not in {None, "not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual scope cannot claim Q-N")
    if entry.get("numerical_precision_status") not in {None, NUMERICAL_PRECISION_STATUS}:
        raise VisualAuthorizationError("visual scope numerical precision is already accepted")

    index_goal_value = index.get("goal_authority", index.get("goal_binding", index.get("goal")))
    goal_path, goal_binding = _binding(index_goal_value, "goal_authority", hashes, base=index_path.parent)
    scope_goal_value = entry.get("goal_authority", entry.get("goal"))
    if scope_goal_value is not None:
        _validate_goal_binding(
            scope_goal_value,
            base=index_path.parent,
            expected_path=goal_path,
            expected_sha=goal_binding["sha256"],
        )

    decision_path, decision_binding, decision = _json_binding(
        _binding_from(entry, "root_visual_decision")
        or _binding_from(entry, "visual_decision")
        or _binding_from(entry, "final_visualization_decision"),
        "root_visual_decision",
        hashes,
        base=index_path.parent,
    )
    _ensure_visual_decision(
        decision,
        family_id=family_id,
        case_id=request.get("case_id"),
        scope_id=scope_id,
    )
    decision_goal = decision.get("bindings", {}).get("goal") if isinstance(decision.get("bindings"), Mapping) else None
    if decision_goal is not None:
        decision_goal_path = _resolve_binding_path(str(decision_goal.get("path")), base=index_path.parent)
        if decision_goal_path != Path(goal_binding["path"]) or decision_goal.get("sha256") != goal_binding["sha256"]:
            raise VisualAuthorizationError("visual decision is bound to a different updated GOAL")

    visual_evidence, visual_bindings = _visual_evidence_bindings(entry, hashes, base=index_path.parent)

    domain_path, domain_binding, domain = _json_binding(
        _binding_from(entry, "physical_domain") or _binding_from(entry, "frozen_physical_domain"),
        "physical_domain",
        hashes,
        base=index_path.parent,
    )
    manifest_path, manifest_binding, manifest = _json_binding(
        _binding_from(entry, "case_manifest") or _binding_from(entry, "manifest") or _binding_from(entry, "frozen_case_manifest"),
        "case_manifest",
        hashes,
        base=index_path.parent,
    )
    if domain.get("schema") not in {None, "ds02.stage1.frozen-physical-domain.v1"}:
        raise VisualAuthorizationError("physical_domain has an unexpected schema")
    if manifest.get("schema") not in {None, "ds02.stage1.visual-case-manifest.v1"}:
        raise VisualAuthorizationError("case_manifest has an unexpected schema")
    domain_rows = _case_rows(domain, "physical_domain")
    manifest_rows = _case_rows(manifest, "case_manifest")
    _validate_unique_physical_rows(domain_rows, "physical_domain")
    _validate_unique_physical_rows(manifest_rows, "case_manifest")
    if len(domain_rows) != len(manifest_rows):
        raise VisualAuthorizationError("physical domain and case manifest have different case counts")

    domain_by_case = {row["case_id"]: row for row in domain_rows}
    manifest_by_case = {row["case_id"]: row for row in manifest_rows}
    if set(domain_by_case) != set(manifest_by_case):
        raise VisualAuthorizationError("physical domain and case manifest case IDs differ")
    for case_id, row in manifest_by_case.items():
        frozen = domain_by_case[case_id]
        for key in ("physical_case_id", "physics", "geometry", "motion"):
            if key in frozen or key in row:
                _same(row.get(key), frozen.get(key), f"case {case_id} {key}")
        _same(_parameter_value(row), _parameter_value(frozen), f"case {case_id} parameter_tuple")

    case_id = request.get("case_id")
    if case_id not in manifest_by_case:
        raise VisualAuthorizationError("requested visual case is absent from frozen case manifest")
    case = manifest_by_case[case_id]
    frozen = domain_by_case[case_id]
    for key in (
        "physical_case_id",
        "physical_condition_sha256",
        "physics",
        "geometry",
        "motion",
        "parent_group_id",
        "split",
    ):
        if key in case or key in request:
            _same(request.get(key), case.get(key), f"request {key}")
        if key in frozen:
            _same(case.get(key), frozen.get(key), f"case {case_id} frozen {key}")
    _same(_parameter_value(request), _parameter_value(case), "request parameter_tuple")
    _same(_parameter_value(case), _parameter_value(frozen), f"case {case_id} frozen parameter_tuple")

    numerical_recipe = case.get("numerical_recipe")
    if numerical_recipe is None:
        numerical_recipe = case.get("numerical_recipe_hash")
    if numerical_recipe is None:
        raise VisualAuthorizationError("frozen case numerical_recipe is required")
    _same(request.get("numerical_recipe", request.get("numerical_recipe_hash")), numerical_recipe, "numerical recipe")
    command = case.get("actual_solver_command", case.get("solver_command"))
    cwd = case.get("actual_solver_cwd", case.get("solver_cwd"))
    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
        raise VisualAuthorizationError("frozen case actual solver command is required")
    if not isinstance(cwd, str) or not cwd:
        raise VisualAuthorizationError("frozen case actual solver cwd is required")
    _same(request.get("command"), command, "actual solver command")
    _same(request.get("cwd"), cwd, "actual solver cwd")
    event_window = case.get("event_window_s", case.get("complete_event_window_s"))
    if event_window is None:
        event_window = domain.get("event_window_s", domain.get("time_window_s"))
    if not isinstance(event_window, list) or len(event_window) != 2 or event_window[1] <= event_window[0]:
        raise VisualAuthorizationError("frozen complete event window is required")
    _same(request.get("complete_event_window_s"), event_window, "complete event window")

    actual_bindings = _actual_case_bindings(case, request, hashes, base=index_path.parent)
    return {
        "entry": copy.deepcopy(dict(entry)),
        "case": copy.deepcopy(dict(case)),
        "domain_case": copy.deepcopy(dict(frozen)),
        "goal_authority": goal_binding,
        "root_visual_decision": decision_binding,
        "root_visual_decision_path": str(decision_path),
        "visual_evidence": visual_evidence,
        "visual_evidence_bindings": visual_bindings,
        "physical_domain": domain_binding,
        "case_manifest": manifest_binding,
        "actual_case_bindings": actual_bindings,
    }


def authorize(
    request: Mapping[str, Any],
    *,
    index_path: os.PathLike[str] | str = INDEX,
    approval_context: MutableMapping[str, Any] | None = None,
) -> dict[str, str]:
    """Authorize one frozen Stage 1 visual case before any lease is acquired.

    Returned hashes are immutable request/evidence inputs.  The mutable visual
    index is recorded in ``approval_context`` and is intentionally excluded
    from this map so unrelated family additions do not invalidate a running
    selected scope.  A changed/revoked selected entry is caught by
    :func:`revalidate_approval`.
    """

    if request.get("kind") != "production":
        raise VisualAuthorizationError("Stage 1 visual authorizer accepts production only")
    if request.get("visual_stage_profile") != VISUAL_STAGE_PROFILE:
        raise VisualAuthorizationError("explicit stage1_visual profile is required")
    if request.get("q_n") not in {None, "not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual production request cannot claim Q-N")
    production_approval = request.get("production_approval")
    if (
        production_approval is not None
        and "none" not in str(production_approval).lower()
        and any(token in str(production_approval).lower() for token in ("approved", "granted", "q-n"))
    ):
        raise VisualAuthorizationError("visual production request cannot claim numerical approval")
    index_path = Path(index_path).resolve()
    if not index_path.is_file():
        raise VisualAuthorizationError(f"visual approval index is missing: {index_path}")
    request_files = {Path(value).resolve() for value in request.get("input_files", []) if isinstance(value, str)}
    if index_path in request_files:
        raise VisualAuthorizationError("mutable visual approval index must be excluded from immutable input_files")
    for map_name in ("input_sha256", "input_hashes"):
        mapping = request.get(map_name)
        if isinstance(mapping, Mapping) and index_path in {Path(str(value)).resolve() for value in mapping}:
            raise VisualAuthorizationError("mutable visual approval index must be excluded from registered hashes")
    raw_index = index_path.read_bytes()
    index = _parse_json(raw_index)
    _validate_index(index)
    entry = _find_entry(index, request)
    hashes: dict[str, str] = {}
    source_paths = _registered_source_bindings(request, hashes)
    validated = _validate_scope(request, entry, index, index_path, hashes)
    selected_digest = _entry_digest(entry)
    goal_binding = validated["goal_authority"]
    context = {
        "index_path": str(index_path),
        "index_sha256_at_launch": hashlib.sha256(raw_index).hexdigest(),
        "selected_family_id": request["family_id"],
        "selected_scope_id": request["scope_id"],
        "selected_case_id": request["case_id"],
        "selected_entry_at_launch": copy.deepcopy(dict(entry)),
        "selected_entry_sha256": selected_digest,
        "goal_authority_at_launch": goal_binding,
        "stage1_profile": VISUAL_STAGE_PROFILE,
        "visual_only": True,
        "numerical_precision_status": NUMERICAL_PRECISION_STATUS,
        "precision_context": PRECISION_CONTEXT,
        "q_n": "not_granted",
        "source_paths": source_paths,
    }
    if approval_context is not None:
        approval_context.update(context)
    # Keep the validated semantic artifacts auditable to callers without
    # adding mutable index bytes to the immutable runtime map.
    return hashes


def revalidate_approval(context: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate only the selected visual entry and its GOAL authority.

    Adding or changing an unrelated family entry changes the index digest but
    leaves the selected entry digest intact and is therefore allowed.  Remove,
    duplicate, or edit the selected entry, or change the active GOAL authority,
    and the shared runtime must terminate the selected process.
    """

    required = ("index_path", "selected_family_id", "selected_scope_id", "selected_entry_sha256")
    for key in required:
        if key not in context:
            raise VisualAuthorizationError(f"approval context lacks {key}")
    index_path = Path(str(context["index_path"])).resolve()
    raw_index = index_path.read_bytes()
    index = _parse_json(raw_index)
    _validate_index(index)
    selected = {
        "family_id": context["selected_family_id"],
        "scope_id": context["selected_scope_id"],
    }
    matches = [
        item
        for item in index.get("scopes", [])
        if isinstance(item, Mapping)
        and item.get("family_id") == selected["family_id"]
        and item.get("scope_id") == selected["scope_id"]
    ]
    if len(matches) != 1 or _entry_digest(matches[0]) != context["selected_entry_sha256"]:
        raise VisualAuthorizationError("selected visual approval changed or was revoked")
    current_goal = index.get("goal_authority", index.get("goal_binding", index.get("goal")))
    goal_path, goal_binding = _binding(current_goal, "goal_authority", {}, base=index_path.parent)
    launch_goal = context.get("goal_authority_at_launch")
    if not isinstance(launch_goal, Mapping) or goal_binding != launch_goal:
        raise VisualAuthorizationError("selected visual approval GOAL authority changed")
    return {
        "status": "selected_visual_approval_unchanged",
        "index_sha256": hashlib.sha256(raw_index).hexdigest(),
        "selected_entry_sha256": context["selected_entry_sha256"],
        "stage1_profile": VISUAL_STAGE_PROFILE,
        "visual_only": True,
        "numerical_precision_status": NUMERICAL_PRECISION_STATUS,
        "precision_context": PRECISION_CONTEXT,
        "goal_authority": goal_binding,
    }


def build_request(
    case: Mapping[str, Any],
    *,
    family_id: str,
    scope_id: str,
    attempt_id: str,
    adapter_path: os.PathLike[str] | str,
    strict_path: os.PathLike[str] | str | None = None,
    runtime_path: os.PathLike[str] | str | None = None,
    command: list[str] | None = None,
    cwd: str | None = None,
    complete_event_window_s: list[float] | None = None,
    input_files: list[str] | None = None,
    **resource_fields: Any,
) -> dict[str, Any]:
    """Build an explicit visual production request without launching work.

    The builder copies only frozen case metadata and computes source/input
    digests.  It performs no GenCase, solver, conversion, or numerical work.
    """

    if not isinstance(case, Mapping):
        raise VisualAuthorizationError("case must be an object")
    result = copy.deepcopy(dict(case))
    result.update(
        family_id=family_id,
        scope_id=scope_id,
        attempt_id=attempt_id,
        kind="production",
        visual_stage_profile=VISUAL_STAGE_PROFILE,
        visual_stage_adapter_path=str(Path(adapter_path).resolve()),
    )
    if command is not None:
        result["command"] = list(command)
    elif "actual_solver_command" in result:
        result["command"] = copy.deepcopy(result["actual_solver_command"])
    elif "solver_command" in result:
        result["command"] = copy.deepcopy(result["solver_command"])
    if cwd is not None:
        result["cwd"] = cwd
    elif "actual_solver_cwd" in result:
        result["cwd"] = result["actual_solver_cwd"]
    elif "solver_cwd" in result:
        result["cwd"] = result["solver_cwd"]
    if complete_event_window_s is not None:
        result["complete_event_window_s"] = list(complete_event_window_s)
    elif "event_window_s" in result:
        result["complete_event_window_s"] = copy.deepcopy(result["event_window_s"])
    elif "complete_event_window_s" not in result and "time_window_s" in result:
        result["complete_event_window_s"] = copy.deepcopy(result["time_window_s"])
    if "numerical_recipe" not in result and "numerical_recipe_hash" in result:
        result["numerical_recipe"] = result["numerical_recipe_hash"]
    gen = result.get("gencase_receipt", result.get("actual_gencase_receipt"))
    if isinstance(gen, Mapping) and isinstance(gen.get("path"), str):
        result["gencase_receipt"] = str(Path(gen["path"]).resolve())
        result["gencase_receipt_sha256"] = gen.get("sha256")
    else:
        raise VisualAuthorizationError("case gencase_receipt binding is required")
    source_files = [Path(adapter_path).resolve(), Path(__file__).resolve()]
    if strict_path is None:
        strict_path = _source_module_path("ds_data02_strict_dispatch_v1")
    if runtime_path is None:
        runtime_path = _source_module_path("ds_data02_runtime_v2")
    source_files.extend((Path(strict_path).resolve(), Path(runtime_path).resolve()))
    if input_files is None:
        input_files = []
        for item in result.get("input_bindings", []):
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                input_files.append(item["path"])
        for name in (
            "gencase_receipt",
            "initial_state_qa",
            "initialization_qa",
            "initial_mass_discrepancy_report",
            "mass_discrepancy_report",
            "physics_evidence",
            "geometry_evidence",
            "motion_evidence",
            "no_overlap_finite_state_evidence",
        ):
            value = result.get(name)
            if isinstance(value, Mapping) and isinstance(value.get("path"), str):
                input_files.append(value["path"])
        # The initial-state QA document contains the genuine generated bytes
        # as nested bindings.  Include them in the immutable request set so
        # the strict dispatcher checks those bytes in its normal hash pass.
        qa_value = result.get("initial_state_qa", result.get("initialization_qa"))
        if isinstance(qa_value, Mapping) and isinstance(qa_value.get("path"), str):
            try:
                qa_document = _read_json(Path(qa_value["path"]))
            except (OSError, UnicodeError, VisualAuthorizationError):
                qa_document = {}
            nested = qa_document.get("actual_initial_bytes", qa_document.get("initial_bytes", []))
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                        input_files.append(item["path"])
        for item in result.get("initial_bytes", result.get("initial_input_bindings", [])):
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                input_files.append(item["path"])
    all_files = []
    seen: set[Path] = set()
    for value in [*source_files, *(Path(path).resolve() for path in input_files)]:
        if value not in seen:
            all_files.append(value)
            seen.add(value)
    result["input_files"] = [str(path) for path in all_files]
    result["input_sha256"] = {str(path): digest(path) for path in all_files}
    result["input_hashes"] = dict(result["input_sha256"])
    defaults = {
        "max_wall_seconds": 1,
        "cpu_threads": 1,
        "estimated_storage_bytes": 0,
        "estimated_peak_gpu_mib": 1,
        "worktree_root": str(Path(__file__).resolve().parents[5]),
    }
    defaults.update(resource_fields)
    for key, value in defaults.items():
        result.setdefault(key, value)
    return result


__all__ = [
    "CAMPAIGN_ID",
    "INDEX",
    "NUMERICAL_PRECISION_STATUS",
    "PRECISION_CONTEXT",
    "SCHEMA",
    "VISUAL_STAGE_PROFILE",
    "VisualAuthorizationError",
    "authorize",
    "build_request",
    "digest",
    "revalidate_approval",
]
