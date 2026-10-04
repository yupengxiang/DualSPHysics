#!/usr/bin/env python3
"""Source-only F1 ECC authorizer for the DS-DATA-02 Stage 1 visual path.

This module is deliberately separate from ``ds_data02_production``.  It does
not grant Q-N, does not run a scientific verifier, and does not modify the
consumed runner.  A root-owned ``APPROVED_VISUAL_SCOPES.json`` supplies the
selected visual decision and the frozen case manifest.  The shared runtime
still owns resource reservations, UUID leases, execution, monitoring, and
receipt creation.

The module is installed by ``ds_data02_stage1_dispatch_f1`` only for an
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
SCHEMA = "ds02.root-approved-visual-scopes.v2"
DOMAIN_DECISION_SCHEMA = "ds02.stage1.root-visual-domain-decision.v1"
CASE_DECISION_SCHEMA = "ds02.stage1.root-visual-case-decision.v1"
VISUAL_STAGE_PROFILE = "stage1_visual"
NUMERICAL_PRECISION_STATUS = "not_accepted"
PRECISION_CONTEXT = "pending"
EXPECTED_STAGE1_LABEL = "视觉检查通过、数值精度未验收"
# F1 ECC uses its own frozen native contract.  These are defaults only; the
# selected manifest row remains authoritative for per-case fluid identity.
EXPECTED_FRAME_COUNT = 161
EXPECTED_WINDOW = [0.0, 1.6]
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
    if initial_bytes is None:
        generated = _nested_mapping_value(case, "generated_xml")
        initial_bi4 = _nested_mapping_value(case, "initial_bi4")
        initial_bytes = [value for value in (generated, initial_bi4) if value is not None]
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
        "prospective_domain_launch": bool(request.get("prospective_domain_launch", False)),
        "future_case_visual_review": (
            "required_after_actual_complete_run"
            if request.get("prospective_domain_launch") is True
            else "case_decision_bound_before_launch"
        ),
        "prospective_case": request.get("case_id") in set(validated.get("domain_membership", {}).get("prospective", [])),
        "root_visual_domain_decision": validated.get("root_visual_domain_decision"),
        "root_visual_domain_decision_path": validated.get("root_visual_domain_decision_path"),
        "domain_membership": copy.deepcopy(validated.get("domain_membership", {})),
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

# ---------------------------------------------------------------------------
# v2 semantic validators
# ---------------------------------------------------------------------------
#
# The v1 implementation above is retained verbatim as a provenance aid.  The
# names below intentionally replace its narrow validators at module load time.
# Keeping the consumed runtime and strict dispatcher out of this module is
# useful: v2 only decides whether an already-frozen request is admissible.


def _mapping_value(source: Any, *names: str) -> Any:
    if not isinstance(source, Mapping):
        return None
    for name in names:
        if name in source and source[name] is not None:
            return source[name]
    return None


def _nested_mapping_value(source: Any, *names: str) -> Any:
    """Find one binding in the common case/source/solver provenance maps."""

    if not isinstance(source, Mapping):
        return None
    value = _mapping_value(source, *names)
    if value is not None:
        return value
    for container_name in (
        "source",
        "solver_provenance",
        "prepared_input",
        "initial_state_source",
        "clone_parent_evidence",
        "provenance",
    ):
        container = source.get(container_name)
        if isinstance(container, Mapping):
            value = _mapping_value(container, *names)
            if value is not None:
                return value
    return None


def _binding_file_values(value: Any) -> list[Mapping[str, Any]]:
    """Return nested path/sha256 objects without interpreting array data."""

    result: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            result.append(value)
        for child in value.values():
            result.extend(_binding_file_values(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_binding_file_values(child))
    return result


def _hash_nested_file_bindings(
    value: Any,
    label: str,
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> list[dict[str, Any]]:
    """Hash nested evidence files, preserving their semantic sidecar fields."""

    result: list[dict[str, Any]] = []
    for index, binding in enumerate(_binding_file_values(value)):
        _, normalized = _binding(
            binding,
            f"{label}[{index}]",
            hashes,
            base=base,
        )
        result.append(normalized)
    return result


def _require_zero(value: Any, label: str) -> None:
    if isinstance(value, bool):
        if value:
            raise VisualAuthorizationError(f"{label} must be zero")
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or float(value) != 0:
            raise VisualAuthorizationError(f"{label} must be zero")
        return
    if isinstance(value, str):
        # The endpoint Root records intentionally preserve an observation such
        # as “strict all-frame audit reports0”.  That is accepted as evidence,
        # while explicit non-zero text remains a hard integrity failure.
        if re.search(r"(?:^|[^0-9])(?:[1-9][0-9]*)(?:[^0-9]|$)", value):
            raise VisualAuthorizationError(f"{label} reports a non-zero state")
        if not re.search(r"(?:^|[^0-9])0(?:[^0-9]|$)", value):
            raise VisualAuthorizationError(f"{label} lacks an explicit zero state")
        return
    raise VisualAuthorizationError(f"{label} lacks an explicit zero state")


def _expected_case_frames(case: Mapping[str, Any]) -> int:
    """Return the selected case's saved-frame contract, never a F3 constant."""

    for key in ("expected_saved_frames", "expected_native_frames", "frames", "frame_count"):
        value = case.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return EXPECTED_FRAME_COUNT


def _expected_case_fluid(case: Mapping[str, Any]) -> int | None:
    """Return the selected case's native fluid identity when it is bound."""

    for key in ("native_fluid_particles", "native_fluid", "fluid_particles"):
        value = case.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    for container_name in ("initial_native_reference", "initial_state_qa", "native_initial_qa"):
        container = case.get(container_name)
        if not isinstance(container, Mapping):
            continue
        for key in ("native_fluid_particles", "native_fluid", "fluid_particles", "expected_fluid"):
            value = container.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    return None


def _validate_integrity_report_v2(
    report: Mapping[str, Any],
    *,
    case_id: str | None = None,
    expected_frame_count: int | None = None,
    expected_fluid_particles: int | None = None,
) -> None:
    """Validate the JSON integrity report, never the raw particle arrays."""

    if report.get("all_frames_rendered") is not True:
        raise VisualAuthorizationError("visual integrity report lacks all_frames_rendered=true")
    if report.get("diagnostic_only") is not False:
        raise VisualAuthorizationError("visual integrity report is diagnostic-only")
    if report.get("actual_times_preserved_exactly") is not True:
        raise VisualAuthorizationError("visual integrity report lacks exact saved times")
    frame_count = expected_frame_count or EXPECTED_FRAME_COUNT
    if report.get("frames") != frame_count:
        raise VisualAuthorizationError(
            f"visual integrity report does not contain all {frame_count} selected frames"
        )
    if report.get("native_identity_axis_preserved") is not True:
        raise VisualAuthorizationError("visual integrity report lacks native identity preservation")
    _require_zero(report.get("nonfinite_active_states"), "visual integrity nonfinite_active_states")
    diagnostics = report.get("frame_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != frame_count:
        raise VisualAuthorizationError("visual integrity report has incomplete frame diagnostics")
    for index, row in enumerate(diagnostics):
        if not isinstance(row, Mapping):
            raise VisualAuthorizationError(f"frame diagnostics row {index} is not an object")
        if row.get("missing", 0) != 0:
            raise VisualAuthorizationError(f"frame diagnostics row {index} reports missing states")
        for key in ("active", "fluid_points"):
            if key in row:
                _require_finite_positive(row[key], f"frame diagnostics row {index} {key}")
        if (
            expected_fluid_particles is not None
            and "fluid_points" in row
            and row["fluid_points"] != expected_fluid_particles
        ):
            raise VisualAuthorizationError(f"frame diagnostics row {index} changes native fluid identity")
        if "actual_time_s" in row and (
            isinstance(row["actual_time_s"], bool)
            or not isinstance(row["actual_time_s"], (int, float))
            or not math.isfinite(float(row["actual_time_s"]))
        ):
            raise VisualAuthorizationError(f"frame diagnostics row {index} has a non-finite time")
    if case_id is not None and report.get("case_id") not in {None, case_id}:
        raise VisualAuthorizationError("visual integrity report case identity differs from selected case")


def _ensure_visual_decision_v2(
    decision: Mapping[str, Any],
    *,
    family_id: str,
    case: Mapping[str, Any],
    current_goal: Mapping[str, Any] | None = None,
    historical: bool = False,
) -> None:
    """Require an actual case decision and its identity/visual-only meaning."""

    if decision.get("schema") != CASE_DECISION_SCHEMA:
        raise VisualAuthorizationError("visual decision has the wrong case-decision schema")
    if decision.get("status") != "visual-approved-by-root":
        raise VisualAuthorizationError("root visual case decision is not approved")
    if decision.get("family_id") != family_id:
        raise VisualAuthorizationError("visual decision family differs from selected case")
    case_id = case.get("case_id")
    if decision.get("case_id") != case_id:
        raise VisualAuthorizationError("visual decision case identity differs from selected case")
    for key in ("physical_case_id", "physical_condition_sha256"):
        if decision.get(key) != case.get(key):
            raise VisualAuthorizationError(f"visual decision {key} differs from frozen case")
    if decision.get("stage1_label") != EXPECTED_STAGE1_LABEL:
        raise VisualAuthorizationError("visual decision must retain the Stage 1 precision label")
    if decision.get("production_scope_approval") is not False:
        raise VisualAuthorizationError("visual case decision cannot grant numerical production")
    if decision.get("numerical_precision_status") != NUMERICAL_PRECISION_STATUS:
        raise VisualAuthorizationError("visual case decision numerical precision is not pending")
    if decision.get("q_n") not in {"not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual case decision must not claim Q-N")
    if decision.get("q_e") not in {"not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual case decision must not claim Q-E")
    expected_window = case.get("physical_window_s", case.get("event_window_s", EXPECTED_WINDOW))
    if decision.get("physical_window_s") != expected_window:
        raise VisualAuthorizationError("visual case decision physical window differs from frozen case")
    expected_frames = _expected_case_frames(case)
    if decision.get("frames") != expected_frames:
        raise VisualAuthorizationError(
            f"visual case decision must identify {expected_frames} saved frames"
        )
    expected_fluid = _expected_case_fluid(case)
    if expected_fluid is not None and decision.get("native_fluid_particles") not in {None, expected_fluid}:
        raise VisualAuthorizationError("visual case decision changes native fluid identity")
    checks = decision.get("visual_rejection_checks")
    if not isinstance(checks, Mapping):
        raise VisualAuthorizationError("visual case decision lacks visual rejection checks")
    _require_zero(checks.get("nonfinite_active_state"), "visual case decision nonfinite_active_state")
    if current_goal is not None and not historical:
        bindings = decision.get("bindings")
        goal = bindings.get("goal") if isinstance(bindings, Mapping) else None
        if goal is None:
            goal = decision.get("goal_authority")
        if not isinstance(goal, Mapping):
            raise VisualAuthorizationError("visual case decision lacks current GOAL binding")
        if goal.get("path") != current_goal.get("path") or goal.get("sha256") != current_goal.get("sha256"):
            raise VisualAuthorizationError("visual case decision is bound to a different current GOAL")


def _ensure_domain_decision_v2(
    decision: Mapping[str, Any],
    *,
    family_id: str,
    scope_id: str,
    current_goal: Mapping[str, Any],
    selected_override: list[str] | None = None,
) -> dict[str, list[str]]:
    """Validate the explicit Root-authored prospective domain membership."""

    if decision.get("schema") != DOMAIN_DECISION_SCHEMA:
        raise VisualAuthorizationError("root domain decision must use the aggregate domain schema")
    if decision.get("status") != "visual-domain-approved-by-root":
        raise VisualAuthorizationError("root visual domain decision is not approved")
    if decision.get("family_id") != family_id or decision.get("scope_id") != scope_id:
        raise VisualAuthorizationError("root visual domain decision scope identity differs")
    if decision.get("stage1_label") != EXPECTED_STAGE1_LABEL:
        raise VisualAuthorizationError("root domain decision must retain the Stage 1 precision label")
    if decision.get("production_scope_approval") is not False:
        raise VisualAuthorizationError("root domain decision cannot grant numerical precision")
    precision_status = decision.get("numerical_precision_status", decision.get("precision_status"))
    # The immutable 042 Root domain record carries the same status in its
    # Stage-1 label and explicitly keeps production/Q-N disabled, but predates
    # this field.  Accept that historical shape while rejecting any explicit
    # non-pending value.
    if precision_status is not None and precision_status != NUMERICAL_PRECISION_STATUS:
        raise VisualAuthorizationError("root domain decision numerical precision is not pending")
    if decision.get("q_n") != "not_granted" or decision.get("q_e") != "not_assessed":
        raise VisualAuthorizationError("root domain decision must leave Q-N and Q-E ungranted")
    goal = decision.get("goal_authority")
    if goal is None and isinstance(decision.get("bindings"), Mapping):
        goal = decision["bindings"].get("goal")
    if not isinstance(goal, Mapping):
        raise VisualAuthorizationError("root domain decision lacks current GOAL authority")
    if goal.get("path") != current_goal.get("path") or goal.get("sha256") != current_goal.get("sha256"):
        raise VisualAuthorizationError("root domain decision is bound to a stale GOAL")

    observed = decision.get("observed_case_ids")
    prospective = decision.get("prospective_case_ids")
    selected = decision.get("selected_case_ids", decision.get("authorized_case_ids"))
    if selected is None:
        selected = selected_override
    if selected is None and decision.get("prospective_execution_authorized") is True:
        selected = list(prospective or [])
    if not isinstance(observed, list) or not observed or not all(isinstance(v, str) and v for v in observed):
        raise VisualAuthorizationError("root domain decision needs explicit observed_case_ids")
    if not isinstance(prospective, list) or not all(isinstance(v, str) and v for v in prospective):
        raise VisualAuthorizationError("root domain decision needs explicit prospective_case_ids")
    if not isinstance(selected, list) or not selected or not all(isinstance(v, str) and v for v in selected):
        raise VisualAuthorizationError("root domain decision needs explicit selected_case_ids")
    if len(set(observed)) != len(observed) or len(set(prospective)) != len(prospective):
        raise VisualAuthorizationError("root domain decision repeats a case ID")
    if set(observed) & set(prospective):
        raise VisualAuthorizationError("a case cannot be both observed and prospective")
    allowed = set(observed) | set(prospective)
    if not set(selected).issubset(allowed):
        raise VisualAuthorizationError("root domain selected membership is outside observed/prospective IDs")
    parameter_axis = decision.get("parameter_axis") if isinstance(decision.get("parameter_axis"), Mapping) else {}
    no_interpolation = decision.get("no_interpolation_or_extrapolation") is True or parameter_axis.get("no_interpolation_or_extrapolation") is True
    if no_interpolation is not True and decision.get("membership_is_explicit") is not True:
        raise VisualAuthorizationError("root domain decision does not prohibit interpolation")
    return {"observed": list(observed), "prospective": list(prospective), "selected": list(selected)}


def _case_parameter_key(row: Mapping[str, Any]) -> str:
    # The 054 physical-domain record stores a rich mechanism tuple while its
    # provenance record stores the same condition as scalar fields.  Compare
    # the canonical physical identity shared by both representations.
    if (
        row.get("transverse_amplitude_m_s2") is not None
        or row.get("nominal_pitch_multiplier") is not None
    ):
        value = {
            "transverse_amplitude_m_s2": row.get("transverse_amplitude_m_s2"),
            "nominal_pitch_multiplier": row.get("nominal_pitch_multiplier"),
            "physical_condition_sha256": row.get("physical_condition_sha256"),
        }
    else:
        value = row.get("parameter_tuple", row.get("physical_parameter_tuple"))
    if value is None:
        raise VisualAuthorizationError("case lacks a frozen physical parameter tuple")
    return _canonical(value)


def _validate_unique_rows_v2(rows: list[Mapping[str, Any]], label: str) -> None:
    cases: set[str] = set()
    physical: set[str] = set()
    tuples: set[str] = set()
    for index, row in enumerate(rows):
        prefix = f"{label}.cases[{index}]"
        case_id = row.get("case_id")
        physical_id = row.get("physical_case_id")
        if not isinstance(case_id, str) or not case_id:
            raise VisualAuthorizationError(f"{prefix}.case_id is required")
        if not isinstance(physical_id, str) or not physical_id:
            raise VisualAuthorizationError(f"{prefix}.physical_case_id is required")
        if case_id in cases or physical_id in physical:
            raise VisualAuthorizationError(f"{label} repeats a case or physical identity")
        cases.add(case_id)
        physical.add(physical_id)
        key = _case_parameter_key(row)
        if key in tuples:
            raise VisualAuthorizationError(f"{label} repeats a physical parameter tuple")
        tuples.add(key)
        if row.get("alias_of") is not None or row.get("derived_from") is not None:
            raise VisualAuthorizationError(f"{prefix} is an alias/view rather than a frozen physical case")
        if row.get("independent_case_count_increment") not in {None, 0} and row.get("independent_case_count_increment_in_candidate") not in {None, 0}:
            raise VisualAuthorizationError(f"{prefix} changes independent physical-case count")


def _extract_visual_binding(row: Mapping[str, Any], *names: str) -> Any:
    value = _mapping_value(row, *names)
    if value is not None:
        return value
    for container_name in ("full_saved_frames", "visual", "visual_provenance", "evidence", "bindings"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            value = _mapping_value(container, *names)
            if value is not None:
                return value
    return None


def _validate_visual_record_v2(
    row: Mapping[str, Any],
    *,
    case: Mapping[str, Any],
    family_id: str,
    current_goal: Mapping[str, Any],
    historical: bool,
    hashes: MutableMapping[str, str],
    base: Path,
) -> dict[str, Any]:
    decision_value = _extract_visual_binding(
        row,
        "decision",
        "root_visual_decision",
        "visual_decision",
    )
    integrity_value = _extract_visual_binding(
        row,
        "integrity_report",
        "animation_integrity_report",
        "full_saved_frame_integrity",
    )
    if decision_value is None or integrity_value is None:
        raise VisualAuthorizationError("actual visual record must bind a decision and integrity report")
    decision_path, decision_binding, decision = _json_binding(
        decision_value,
        "visual case decision",
        hashes,
        base=base,
    )
    _ensure_visual_decision_v2(
        decision,
        family_id=family_id,
        case=case,
        current_goal=current_goal,
        historical=historical,
    )
    # The decision's own artifact bindings are part of the immutable evidence
    # set.  This includes the typed trajectory, original GIF, keyframes and
    # the source receipts; only JSON metadata is interpreted here.
    decision_artifacts = _hash_nested_file_bindings(
        decision,
        "visual decision artifacts",
        hashes,
        base=base,
    )
    integrity_path, integrity_binding, report = _json_binding(
        integrity_value,
        "visual integrity report",
        hashes,
        base=base,
    )
    _validate_integrity_report_v2(
        report,
        case_id=case.get("case_id"),
        expected_frame_count=_expected_case_frames(case),
        expected_fluid_particles=_expected_case_fluid(case),
    )
    # Preserve actual original outputs when the row supplies them separately
    # from the decision.  A path/hash binding is required by the aggregate
    # evidence contract; the JSON report remains the authoritative frame audit.
    original = _extract_visual_binding(
        row,
        "full_saved_animation",
        "animation_gif",
        "trajectory_binding",
        "saved_frame_manifest",
    )
    original_bindings: list[dict[str, Any]] = []
    if original is not None:
        original_bindings = _hash_nested_file_bindings(
            original,
            "visual original saved output",
            hashes,
            base=base,
        )
    if not original_bindings:
        # Current Root decisions carry trajectory/GIF/keyframe bindings in the
        # decision document, so the artifact hash list above is sufficient.
        if not decision_artifacts:
            raise VisualAuthorizationError("actual visual record lacks original saved-frame artifacts")
    return {
        "case_id": case.get("case_id"),
        "decision": decision_binding,
        "decision_path": str(decision_path),
        "integrity_report": integrity_binding,
        "integrity_path": str(integrity_path),
        "original_artifacts": [*decision_artifacts, *original_bindings],
        "historical": historical,
    }


def _visual_evidence_bindings_v2(
    entry: Mapping[str, Any],
    *,
    cases_by_id: Mapping[str, Mapping[str, Any]],
    observed_ids: set[str],
    selected_ids: set[str],
    family_id: str,
    current_goal: Mapping[str, Any],
    hashes: MutableMapping[str, str],
    base: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = entry.get("visual_evidence", entry.get("evidence"))
    evidence = _require_mapping(evidence, "visual_evidence")
    result: dict[str, Any] = {"actual": [], "prospective": []}
    all_bindings: list[dict[str, Any]] = []
    listed_ids: set[str] = set()
    for category in ("mother", "endpoints", "interior", "observed", "prospective"):
        value = evidence.get(category)
        if value is None:
            continue
        rows = value if isinstance(value, list) else [value]
        for index, raw_row in enumerate(rows):
            row = _require_mapping(raw_row, f"visual_evidence.{category}[{index}]")
            row_case_ids = row.get("case_ids")
            if isinstance(row_case_ids, list):
                ids = [item for item in row_case_ids if isinstance(item, str)]
            elif isinstance(row.get("case_id"), str):
                ids = [row["case_id"]]
            else:
                ids = []
            status = str(row.get("status", "")).lower()
            pending = status.startswith("pending") or "prospective" in status or row.get("decision") is None and row.get("root_visual_decision") is None and category == "prospective"
            if pending:
                for case_id in ids:
                    if case_id not in cases_by_id:
                        raise VisualAuthorizationError("prospective visual record names an unknown case")
                    listed_ids.add(case_id)
                result["prospective"].append(copy.deepcopy(dict(row)))
                continue
            if len(ids) != 1:
                raise VisualAuthorizationError("actual visual record must identify exactly one case")
            case_id = ids[0]
            if case_id not in cases_by_id:
                raise VisualAuthorizationError("actual visual record names an unknown case")
            if case_id not in observed_ids:
                raise VisualAuthorizationError("actual visual record is outside observed domain membership")
            listed_ids.add(case_id)
            historical = cases_by_id[case_id].get("role") in {"anchor_existing_mother", "mother"} or "historical" in status
            validated = _validate_visual_record_v2(
                row,
                case=cases_by_id[case_id],
                family_id=family_id,
                current_goal=current_goal,
                historical=historical,
                hashes=hashes,
                base=base,
            )
            result["actual"].append(validated)
            all_bindings.extend(
                [validated["decision"], validated["integrity_report"], *validated["original_artifacts"]]
            )
    missing_actual = selected_ids & observed_ids - listed_ids
    if missing_actual:
        raise VisualAuthorizationError("selected observed cases lack actual visual records: " + ",".join(sorted(missing_actual)))
    # The aggregate entry may bind an optional final report/integrity document;
    # if supplied, validate it as JSON content rather than merely hashing it.
    for name in ("final_visualization_decision", "final_visual_decision", "integrity", "full_scope_frame_integrity"):
        value = evidence.get(name)
        if value is None:
            continue
        path, binding, document = _json_binding(value, f"visual_evidence.{name}", hashes, base=base)
        if name in {"integrity", "full_scope_frame_integrity"}:
            _validate_integrity_report_v2(document)
        all_bindings.append(binding)
        result[name] = binding
    return result, all_bindings


def _case_input_bindings_v2(
    case: Mapping[str, Any],
    *,
    shared: Mapping[str, Any] | None = None,
) -> list[Any]:
    explicit = case.get("input_bindings")
    if isinstance(explicit, list) and explicit:
        return list(explicit)
    result: list[Any] = []
    prepared = case.get("prepared_input")
    if isinstance(prepared, Mapping):
        for name in ("forcing", "generated_xml", "initial_bi4", "report"):
            value = prepared.get(name)
            if isinstance(value, Mapping) and value.get("path"):
                result.append(value)
    source = case.get("source")
    if isinstance(source, Mapping):
        for name in ("source_forcing", "generated_xml", "initial_bi4"):
            value = source.get(name)
            if isinstance(value, Mapping) and value.get("path"):
                result.append(value)
    if isinstance(shared, Mapping):
        # Parent bytes are immutable evidence for exact-initial-clone cases.
        for name in ("generated_xml", "initial_bi4"):
            value = shared.get(name)
            if isinstance(value, Mapping) and value.get("path"):
                result.append(value)
    return result


def _request_paths_v2(request: Mapping[str, Any]) -> set[Path]:
    return {Path(str(value)).resolve() for value in request.get("input_files", []) if isinstance(value, str)}


def _require_request_files_v2(paths: list[Path], request: Mapping[str, Any], label: str) -> None:
    missing = [str(path) for path in paths if path.resolve() not in _request_paths_v2(request)]
    if missing:
        raise VisualAuthorizationError(f"request input_files omit {label}: " + ",".join(missing))


def _validate_receipt_v2(
    value: Any,
    label: str,
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> tuple[Path, dict[str, Any], Mapping[str, Any]]:
    path, binding, document = _json_binding(value, label, hashes, base=base)
    if document.get("status") != "completed" or document.get("returncode", document.get("gencase_returncode")) != 0:
        raise VisualAuthorizationError(f"{label} is not an actual successful receipt")
    launch = document.get("input_hashes_at_launch")
    after = document.get("input_hashes_after_run")
    if launch is not None and after is not None and launch != after:
        raise VisualAuthorizationError(f"{label} input provenance changed during its run")
    return path, binding, document


def _select_qa_v2(raw: Any, case: Mapping[str, Any], parent_case_id: str | None = None) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise VisualAuthorizationError("initial-state QA must be an object")
    rows = raw.get("cases")
    if not isinstance(rows, list):
        return raw
    target = parent_case_id or case.get("initial_qa_case_id") or case.get("case_id")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == target]
    if len(matches) != 1:
        raise VisualAuthorizationError("initial-state QA does not contain the selected parent case row")
    selected = dict(raw)
    selected.pop("cases", None)
    selected.update(matches[0])
    return selected


def _validate_initial_qa_v2(qa: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    checks = qa.get("checks") if isinstance(qa.get("checks"), Mapping) else qa
    if checks.get("passed") is False:
        raise VisualAuthorizationError(f"{label} did not pass")
    if checks.get("passed") is not True and checks.get("finite_state") is not True:
        raise VisualAuthorizationError(f"{label} lacks a passed/finite state check")
    if checks.get("actual_3d") is not True:
        raise VisualAuthorizationError(f"{label} is not actual 3D")
    fluid = checks.get("native_fluid", checks.get("fluid_particles", checks.get("positive_fluid_particles")))
    if fluid is False or (isinstance(fluid, (int, float)) and not isinstance(fluid, bool) and fluid <= 0):
        raise VisualAuthorizationError(f"{label} lacks positive native fluid particles")
    if fluid is None and checks.get("positive_fluid_particles") is not True:
        raise VisualAuthorizationError(f"{label} lacks positive native fluid particles")
    return checks


def _validate_genuine_case_v2(
    case: Mapping[str, Any],
    request: Mapping[str, Any],
    hashes: MutableMapping[str, str],
    *,
    base: Path,
) -> dict[str, Any]:
    gen_value = _nested_mapping_value(case, "gencase_receipt", "actual_gencase_receipt")
    if gen_value is None:
        raise VisualAuthorizationError("genuine_3d_generation requires a GenCase receipt")
    gen_path, gen_binding, gen = _validate_receipt_v2(
        gen_value, "case.gencase_receipt", hashes, base=base
    )
    if gen.get("solver_dimension_from_gencase") != 3:
        raise VisualAuthorizationError("genuine GenCase receipt is not actual 3D")
    total = gen.get("total_particles")
    fluid = gen.get("fluid_particles")
    if not isinstance(total, int) or total <= 0 or not isinstance(fluid, int) or fluid <= 0 or fluid > total:
        raise VisualAuthorizationError("genuine GenCase receipt lacks positive particle counts")
    command = gen.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise VisualAuthorizationError("genuine GenCase command provenance is missing")
    qa_value = _nested_mapping_value(case, "initial_state_qa", "initialization_qa")
    if qa_value is None:
        raise VisualAuthorizationError("genuine_3d_generation requires initial-state QA")
    qa_path, qa_binding, qa_raw = _json_binding(qa_value, "case.initial_state_qa", hashes, base=base)
    qa = _select_qa_v2(qa_raw, case)
    qa_checks = _validate_initial_qa_v2(qa, "genuine initial-state QA")

    # F1 .13 must prove that the actual GenCase receipt, the prepared-input
    # report, and the selected row from QA-031 describe the same generated
    # bytes and particle identity.  This is metadata validation only; the
    # original BI4/CSV/typed artifacts are hashed as bindings and never parsed
    # here.
    prepared_value = case.get("prepared_input")
    if not isinstance(prepared_value, Mapping):
        raise VisualAuthorizationError("genuine_3d_generation requires prepared-input evidence")
    report_value = _mapping_value(prepared_value, "report", "prepared_input_report")
    if report_value is None:
        raise VisualAuthorizationError("genuine_3d_generation requires prepared-input report")
    report_path, report_binding, prepared_report = _json_binding(
        report_value,
        "case.prepared_input.report",
        hashes,
        base=base,
    )
    if prepared_report.get("case_id") not in {None, case.get("case_id")}:
        raise VisualAuthorizationError("prepared-input report case identity differs")
    if prepared_report.get("production_approval") not in {None, "none"}:
        raise VisualAuthorizationError("prepared-input report claims production approval")
    report_xml_sha = prepared_report.get("xml_sha256")
    report_bi4_sha = prepared_report.get("bi4_sha256")
    qa_xml_sha = qa_checks.get("generated_xml_sha256")
    qa_bi4_sha = qa_checks.get("initial_bi4_sha256")
    if report_xml_sha is not None and qa_xml_sha is not None and report_xml_sha != qa_xml_sha:
        raise VisualAuthorizationError("prepared-input report XML differs from initial QA")
    if report_bi4_sha is not None and qa_bi4_sha is not None and report_bi4_sha != qa_bi4_sha:
        raise VisualAuthorizationError("prepared-input report BI4 differs from initial QA")
    gen_total = gen.get("total_particles")
    gen_fluid = gen.get("fluid_particles")
    qa_total = qa_checks.get("native_particles", qa_checks.get("total_particles"))
    qa_fluid = qa_checks.get("native_fluid", qa_checks.get("fluid_particles"))
    report_total = prepared_report.get("actual_total_particles")
    report_counts = prepared_report.get("generated_xml_particle_counts")
    report_fluid = report_counts.get("fluid") if isinstance(report_counts, Mapping) else None
    if isinstance(qa_total, int) and isinstance(gen_total, int) and qa_total != gen_total:
        raise VisualAuthorizationError("initial QA total differs from GenCase receipt")
    if isinstance(qa_fluid, int) and isinstance(gen_fluid, int) and qa_fluid != gen_fluid:
        raise VisualAuthorizationError("initial QA fluid count differs from GenCase receipt")
    if isinstance(report_total, int) and isinstance(gen_total, int) and report_total != gen_total:
        raise VisualAuthorizationError("prepared-input total differs from GenCase receipt")
    if isinstance(report_fluid, int) and isinstance(gen_fluid, int) and report_fluid != gen_fluid:
        raise VisualAuthorizationError("prepared-input fluid count differs from GenCase receipt")

    initial_bytes = qa.get("actual_initial_bytes", qa.get("initial_bytes"))
    if initial_bytes is None:
        initial_bytes = case.get("initial_bytes", case.get("initial_input_bindings"))
    if not isinstance(initial_bytes, list) or not initial_bytes:
        raise VisualAuthorizationError("genuine initial-state QA lacks actual initial bytes")
    byte_bindings = []
    byte_paths = []
    for index, value in enumerate(initial_bytes):
        path, binding = _binding(value, f"initial_state_qa.initial_bytes[{index}]", hashes, base=base)
        byte_bindings.append(binding)
        byte_paths.append(path)
    _require_request_files_v2(
        [gen_path, qa_path, report_path, *byte_paths],
        request,
        "genuine initial-state evidence",
    )
    provenance = qa.get("provenance")
    if isinstance(provenance, Mapping):
        provenance_gen = provenance.get("gencase_receipt")
        if provenance_gen is not None and provenance_gen != gen_binding:
            raise VisualAuthorizationError("genuine QA provenance differs from GenCase receipt")
    return {
        "qa_semantics": "genuine_3d_generation",
        "gencase_receipt": gen_binding,
        "gencase_document": gen,
        "initial_state_qa": qa_binding,
        "initial_state_qa_document": qa,
        "prepared_input_report": report_binding,
        "prepared_input_report_document": prepared_report,
        "initial_bytes": byte_bindings,
        "gencase_path": str(gen_path),
        "qa_path": str(qa_path),
    }


def _validate_clone_case_v2(
    case: Mapping[str, Any],
    request: Mapping[str, Any],
    hashes: MutableMapping[str, str],
    *,
    base: Path,
    shared: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if case.get("gencase_receipt") is not None or case.get("actual_gencase_receipt") is not None:
        # A cloned input may reference the original parent, but a new case must
        # never present a clone-preparation receipt as its own GenCase receipt.
        supplied = _nested_mapping_value(case, "gencase_receipt", "actual_gencase_receipt")
        parent = _nested_mapping_value(case, "genuine_parent_gencase_receipt", "parent_gencase_receipt")
        if parent is None or supplied != parent:
            raise VisualAuthorizationError("exact clone cannot claim an independent GenCase receipt")
    parent_value = _nested_mapping_value(
        case,
        "genuine_parent_gencase_receipt",
        "parent_gencase_receipt",
    )
    if parent_value is None and isinstance(shared, Mapping):
        parent_value = shared.get("genuine_gencase_receipt")
    if parent_value is None:
        raise VisualAuthorizationError("exact clone requires the original genuine GenCase receipt")
    parent_path, parent_binding, parent = _validate_receipt_v2(
        parent_value,
        "exact clone parent GenCase receipt",
        hashes,
        base=base,
    )
    if parent.get("solver_dimension_from_gencase") != 3:
        raise VisualAuthorizationError("exact clone parent is not actual 3D")
    if not isinstance(parent.get("total_particles"), int) or parent.get("total_particles") <= 0:
        raise VisualAuthorizationError("exact clone parent lacks actual particle counts")
    clone_value = _nested_mapping_value(
        case,
        "exact_initial_clone_receipt",
        "clone_preparation_receipt",
        "exact_initial_clone_preparation_receipt",
    )
    if clone_value is None and isinstance(shared, Mapping):
        clone_value = _mapping_value(shared, "exact_initial_clone_receipt", "clone_preparation_receipt")
    if clone_value is None:
        # A provenance package may record one successful preparation receipt at
        # the document level; it is still auditable and is not rebranded.
        clone_value = _mapping_value(
            (shared or {}).get("source_documents", {}) if isinstance(shared, Mapping) else {},
            "first8_preparation_receipt",
        )
    if clone_value is None:
        raise VisualAuthorizationError("exact clone requires a clone-preparation receipt")
    clone_path, clone_binding, clone = _validate_receipt_v2(
        clone_value,
        "exact clone preparation receipt",
        hashes,
        base=base,
    )
    if clone.get("production_approval") not in {None, "none", "none frompreparation"}:
        raise VisualAuthorizationError("clone preparation receipt claims production approval")

    # Exact clone source bytes are explicit prepared_input bindings.  Compare
    # both file hashes to the genuine parent and require the producer's own
    # equality assertions.  The forcing file may differ by physical case.
    prepared = case.get("prepared_input")
    if not isinstance(prepared, Mapping):
        prepared = case.get("source") if isinstance(case.get("source"), Mapping) else {}
    xml_value = _mapping_value(prepared, "generated_xml", "xml")
    bi4_value = _mapping_value(prepared, "initial_bi4", "bi4")
    if xml_value is None or bi4_value is None:
        raise VisualAuthorizationError("exact clone requires generated XML and initial BI4 bindings")
    xml_path, xml_binding = _binding(xml_value, "exact clone generated XML", hashes, base=base)
    bi4_path, bi4_binding = _binding(bi4_value, "exact clone initial BI4", hashes, base=base)
    parent_xml = _nested_mapping_value(shared or {}, "generated_xml") if isinstance(shared, Mapping) else None
    parent_bi4 = _nested_mapping_value(shared or {}, "initial_bi4") if isinstance(shared, Mapping) else None
    if parent_xml is not None:
        _, parent_xml_binding = _binding(parent_xml, "genuine parent generated XML", hashes, base=base)
        if parent_xml_binding["sha256"] != xml_binding["sha256"]:
            raise VisualAuthorizationError("exact clone XML bytes differ from genuine parent")
    if parent_bi4 is not None:
        _, parent_bi4_binding = _binding(parent_bi4, "genuine parent initial BI4", hashes, base=base)
        if parent_bi4_binding["sha256"] != bi4_binding["sha256"]:
            raise VisualAuthorizationError("exact clone BI4 bytes differ from genuine parent")
    prepared_report = None
    prepared_report_binding = None
    report_value = _mapping_value(prepared, "report", "prepared_input_report")
    if report_value is not None:
        _, prepared_report_binding, prepared_report = _json_binding(
            report_value,
            "exact clone prepared-input report",
            hashes,
            base=base,
        )
        if prepared_report.get("case_id") not in {None, case.get("case_id")}:
            raise VisualAuthorizationError("prepared-input report case identity differs")
        if prepared_report.get("physical_case_id") not in {None, case.get("physical_case_id")}:
            raise VisualAuthorizationError("prepared-input report physical identity differs")
        if prepared_report.get("xml_sha256") not in {None, xml_binding["sha256"]}:
            raise VisualAuthorizationError("prepared-input report XML identity differs")
        if prepared_report.get("bi4_sha256") not in {None, bi4_binding["sha256"]}:
            raise VisualAuthorizationError("prepared-input report BI4 identity differs")
        if prepared_report.get("production_approval") not in {None, "none"}:
            raise VisualAuthorizationError("prepared-input report claims production approval")
        if prepared_report.get("independent_case_increment") not in {None, 0}:
            raise VisualAuthorizationError("prepared-input report changes independent count")
    xml_equal = prepared.get("xml_byte_identical_to_baseline") is True or case.get("xml_byte_identical_to_baseline") is True
    if not xml_equal and isinstance(prepared_report, Mapping):
        xml_equal = prepared_report.get("xml_byte_identical_to_baseline") is True
    if not xml_equal:
        raise VisualAuthorizationError("exact clone XML byte-equality assertion is missing")
    bi4_equal = prepared.get("initial_bi4_byte_identical_to_baseline") is True or case.get("initial_bi4_byte_identical_to_baseline") is True
    if not bi4_equal and isinstance(prepared_report, Mapping):
        bi4_equal = prepared_report.get("initial_bi4_byte_identical_to_baseline") is True
    if not bi4_equal:
        raise VisualAuthorizationError("exact clone BI4 byte-equality assertion is missing")

    parent_qa_value = _nested_mapping_value(
        case,
        "genuine_parent_initial_qa",
        "parent_initial_qa",
        "initial_state_qa",
    )
    if parent_qa_value is None and isinstance(shared, Mapping):
        parent_qa_value = shared.get("native_initial_qa", shared.get("initial_native_qa"))
    if parent_qa_value is None:
        raise VisualAuthorizationError("exact clone requires the original initial QA")
    qa_path, qa_binding, qa_raw = _json_binding(parent_qa_value, "exact clone parent initial QA", hashes, base=base)
    parent_case_id = None
    if isinstance(shared, Mapping):
        parent_case_id = shared.get("parent_case_id")
    qa = _select_qa_v2(qa_raw, case, parent_case_id=parent_case_id)
    qa_checks = _validate_initial_qa_v2(qa, "exact clone parent initial QA")
    if qa_checks.get("native_initial_BI4_sha256") not in {None, bi4_binding["sha256"]}:
        raise VisualAuthorizationError("exact clone parent QA BI4 identity differs")
    if qa_checks.get("generated_xml_sha256") not in {None, xml_binding["sha256"]}:
        raise VisualAuthorizationError("exact clone parent QA XML identity differs")
    # A clone has zero independent count increment and must not advertise a
    # per-case visual decision before its actual run.
    for key in ("independent_case_count_increment", "independent_case_count_increment_in_candidate"):
        if case.get(key) not in {None, 0}:
            raise VisualAuthorizationError("exact clone changes independent physical-case count")
    _require_request_files_v2([parent_path, qa_path, xml_path, bi4_path], request, "exact clone QA inputs")
    return {
        "qa_semantics": "exact_initial_clone_of_genuine_3d",
        "parent_gencase_receipt": parent_binding,
        "parent_gencase_document": parent,
        "clone_preparation_receipt": clone_binding,
        "clone_preparation_document": clone,
        "parent_initial_qa": qa_binding,
        "parent_initial_qa_document": qa,
        "generated_xml": xml_binding,
        "initial_bi4": bi4_binding,
        "prepared_input_report": prepared_report_binding,
        "parent_gencase_path": str(parent_path),
        "clone_preparation_path": str(clone_path),
        "parent_initial_qa_path": str(qa_path),
    }


def _actual_case_bindings_v2(
    case: Mapping[str, Any],
    request: Mapping[str, Any],
    hashes: MutableMapping[str, str],
    *,
    base: Path,
    shared: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    semantics = str(case.get("qa_semantics", case.get("initial_state_qa_semantics", "")))
    if semantics in {"genuine_3d_generation", "genuine_3d_parent", "genuine_3d"}:
        qa = _validate_genuine_case_v2(case, request, hashes, base=base)
    elif semantics in {
        "exact_initial_clone_of_genuine_3d",
        "exact_initial_clone_of_genuine_3d_parent",
        "exact_initial_clone",
    }:
        qa = _validate_clone_case_v2(case, request, hashes, base=base, shared=shared)
    else:
        raise VisualAuthorizationError("case must declare genuine or exact-initial-clone QA semantics")

    raw_inputs = _case_input_bindings_v2(case, shared=shared)
    if not raw_inputs:
        raise VisualAuthorizationError("case input_bindings or prepared input bindings are required")
    input_bindings: list[dict[str, Any]] = []
    input_paths: list[Path] = []
    for index, value in enumerate(raw_inputs):
        path, binding = _binding(value, f"case.input_bindings[{index}]", hashes, base=base)
        input_bindings.append(binding)
        input_paths.append(path)
    _require_request_files_v2(input_paths, request, "case inputs")

    mass_value = _nested_mapping_value(
        case,
        "initial_mass_discrepancy_report",
        "mass_discrepancy_report",
    )
    if mass_value is None:
        raise VisualAuthorizationError("initial mass discrepancy report is required")
    _, mass_binding, mass = _json_binding(
        mass_value,
        "case.initial_mass_discrepancy_report",
        hashes,
        base=base,
    )
    if not isinstance(mass, Mapping) or not mass:
        raise VisualAuthorizationError("initial mass discrepancy report must be preserved")
    for source in (case, mass, request):
        if source.get("mass_rescaling") is True or source.get("mass_rescaled") is True:
            raise VisualAuthorizationError("initial mass rescaling is forbidden")

    integrity: dict[str, dict[str, Any]] = {}
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
        value = _nested_mapping_value(case, *names)
        if value is None:
            raise VisualAuthorizationError(f"case.{label} is required")
        _, binding, document = _json_binding(value, f"case.{label}", hashes, base=base)
        _require_true(document, checks, label)
        integrity[label] = binding

    # Input provenance is checked for genuine generation where the producer
    # records it.  For clone cases the parent receipt's full source map can be
    # larger than the selected forcing/input subset, so only matching paths are
    # compared; the parent bytes themselves are checked above.
    gen_doc = qa.get("gencase_document", qa.get("parent_gencase_document", {}))
    gen_inputs = gen_doc.get("input_hashes_at_launch") if isinstance(gen_doc, Mapping) else None
    if isinstance(gen_inputs, Mapping):
        local = {str(Path(item["path"]).resolve()): item["sha256"] for item in input_bindings}
        for raw_path, expected in gen_inputs.items():
            resolved = str(Path(str(raw_path)).resolve())
            if resolved in local and local[resolved] != expected:
                raise VisualAuthorizationError("actual QA input provenance differs from frozen input")

    return {
        "input_bindings": input_bindings,
        "qa_semantics": qa["qa_semantics"],
        "qa_evidence": qa,
        "initial_mass_discrepancy_report": mass_binding,
        "initial_mass_discrepancy_document": mass,
        "integrity_evidence": integrity,
    }


def _validate_index_v2(index: Mapping[str, Any]) -> None:
    if index.get("schema") != SCHEMA or index.get("campaign_id") != CAMPAIGN_ID:
        raise VisualAuthorizationError("invalid v2 APPROVED_VISUAL_SCOPES schema or campaign")
    if not isinstance(index.get("scopes"), list):
        raise VisualAuthorizationError("APPROVED_VISUAL_SCOPES.scopes must be a list")
    if any(key in index for key in ("q_n", "q_n_status", "numerical_approval")):
        raise VisualAuthorizationError("visual index cannot carry a fake Q-N grant")
    goal = index.get("goal_authority", index.get("goal_binding", index.get("goal")))
    if not isinstance(goal, Mapping):
        raise VisualAuthorizationError("v2 visual index goal_authority binding is required")


def _validate_scope_v2(
    request: Mapping[str, Any],
    entry: Mapping[str, Any],
    index: Mapping[str, Any],
    index_path: Path,
    hashes: MutableMapping[str, str],
) -> dict[str, Any]:
    family_id = request.get("family_id")
    scope_id = request.get("scope_id")
    if not isinstance(family_id, str) or not isinstance(scope_id, str):
        raise VisualAuthorizationError("family_id and scope_id are required")
    if request.get("visual_stage_profile") != VISUAL_STAGE_PROFILE or entry.get("visual_stage_profile") not in {None, VISUAL_STAGE_PROFILE}:
        raise VisualAuthorizationError("explicit stage1_visual profile is required")
    if request.get("q_n") not in {None, "not_granted", "not_assessed"}:
        raise VisualAuthorizationError("visual request cannot claim Q-N")
    current_goal_value = index.get("goal_authority", index.get("goal_binding", index.get("goal")))
    goal_path, goal_binding = _binding(current_goal_value, "goal_authority", hashes, base=index_path.parent)
    scope_goal = entry.get("goal_authority", entry.get("goal"))
    if scope_goal is not None:
        _validate_goal_binding(scope_goal, base=index_path.parent, expected_path=goal_path, expected_sha=goal_binding["sha256"])

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
    domain_rows = _case_rows(domain, "physical_domain")
    manifest_rows = _case_rows(manifest, "case_manifest")
    _validate_unique_rows_v2(domain_rows, "physical_domain")
    _validate_unique_rows_v2(manifest_rows, "case_manifest")
    domain_by_case = {row["case_id"]: row for row in domain_rows}
    manifest_by_case = {row["case_id"]: row for row in manifest_rows}
    if set(domain_by_case) != set(manifest_by_case):
        raise VisualAuthorizationError("physical domain and case manifest membership differ")
    for case_id, row in manifest_by_case.items():
        frozen = domain_by_case[case_id]
        for key in ("physical_case_id", "physical_condition_sha256", "transverse_amplitude_m_s2", "nominal_pitch_multiplier"):
            if key in frozen and key in row and frozen[key] != row[key]:
                raise VisualAuthorizationError(f"case {case_id} {key} differs between domain and manifest")
        if _case_parameter_key(row) != _case_parameter_key(frozen):
            raise VisualAuthorizationError(f"case {case_id} physical tuple differs between domain and manifest")

    decision_path, decision_binding, domain_decision = _json_binding(
        _binding_from(entry, "root_visual_domain_decision") or _binding_from(entry, "visual_domain_decision"),
        "root_visual_domain_decision",
        hashes,
        base=index_path.parent,
    )
    membership = _ensure_domain_decision_v2(
        domain_decision,
        family_id=family_id,
        scope_id=scope_id,
        current_goal=goal_binding,
    )
    all_case_ids = set(manifest_by_case)
    if not set(membership["observed"]) | set(membership["prospective"]):
        raise VisualAuthorizationError("root domain decision has no frozen case membership")
    if not (set(membership["observed"]) | set(membership["prospective"])).issubset(all_case_ids):
        raise VisualAuthorizationError("root domain decision names a case outside the frozen manifest")
    case_id = request.get("case_id")
    if case_id not in manifest_by_case or case_id not in set(membership["selected"]):
        raise VisualAuthorizationError("requested case is not explicitly selected by Root domain decision")
    case = manifest_by_case[case_id]
    frozen = domain_by_case[case_id]
    for key in ("physical_case_id", "physical_condition_sha256", "physics", "geometry", "motion", "parent_group_id", "split"):
        if key in case:
            if key in request and request.get(key) != case.get(key):
                raise VisualAuthorizationError(f"request {key} differs from frozen case")
            if key in frozen and case.get(key) != frozen.get(key):
                raise VisualAuthorizationError(f"case {case_id} frozen {key} differs")
    request_tuple = request.get("parameter_tuple", request.get("physical_parameter_tuple"))
    if request_tuple is not None and _case_parameter_key(request) != _case_parameter_key(case):
        raise VisualAuthorizationError("request parameter_tuple differs from frozen physical case")
    event_window = case.get("complete_event_window_s", case.get("event_window_s"))
    if event_window is None:
        event_window = domain.get("event_window_s", domain.get("time_window_s"))
    expected_scope_windows = {
        "F1_ECC_STAGE1_FIRST4_HEAD0110_0190_VISUAL_V1": [0.0, 1.6],
        "F1_DUAL_STAGE1_FIRST4_HEAD0220_0340_VISUAL_V1": [0.0, 4.0],
    }
    if scope_id not in expected_scope_windows or event_window != expected_scope_windows[scope_id]:
        raise VisualAuthorizationError("frozen complete event window differs from selected F1 Root visual scope")
    if request.get("complete_event_window_s") != event_window:
        raise VisualAuthorizationError("request complete event window differs from frozen case")
    command = case.get("command", case.get("actual_solver_command", case.get("solver_command")))
    cwd = case.get("cwd", case.get("actual_solver_cwd", case.get("solver_cwd")))
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise VisualAuthorizationError("frozen actual solver command is required")
    if not isinstance(cwd, str) or not cwd:
        raise VisualAuthorizationError("frozen actual solver cwd is required")
    if request.get("command") != command or request.get("cwd") != cwd:
        raise VisualAuthorizationError("request solver command/cwd differs from frozen case")
    recipe = case.get("numerical_recipe", case.get("numerical_recipe_hash"))
    if recipe is None or request.get("numerical_recipe", request.get("numerical_recipe_hash")) != recipe:
        raise VisualAuthorizationError("request numerical recipe differs from frozen case")

    observed_ids = set(membership["observed"])
    prospective_ids = set(membership["prospective"])
    selected_ids = set(membership["selected"])
    if case_id in prospective_ids:
        if request.get("prospective_domain_launch") is not True:
            raise VisualAuthorizationError("prospective case requires prospective_domain_launch=true")
        if case.get("root_visual_decision") is not None or case.get("visual_decision") is not None:
            raise VisualAuthorizationError("prospective case visual decision must remain a post-run artifact")
    elif case_id not in observed_ids:
        raise VisualAuthorizationError("selected case is outside observed/prospective memberships")

    visual_evidence, visual_bindings = _visual_evidence_bindings_v2(
        entry,
        cases_by_id=manifest_by_case,
        observed_ids=observed_ids,
        selected_ids=selected_ids,
        family_id=family_id,
        current_goal=goal_binding,
        hashes=hashes,
        base=index_path.parent,
    )
    shared_value = manifest.get("shared_initial_state")
    shared = copy.deepcopy(dict(shared_value)) if isinstance(shared_value, Mapping) else None
    if shared is not None and isinstance(manifest.get("source_documents"), Mapping):
        # 054 stores the one strict012 preparation receipt beside the shared
        # parent state rather than repeating it in all five clone rows.
        shared["source_documents"] = copy.deepcopy(dict(manifest["source_documents"]))
    actual_bindings = _actual_case_bindings_v2(
        case,
        request,
        hashes,
        base=index_path.parent,
        shared=shared,
    )
    return {
        "entry": copy.deepcopy(dict(entry)),
        "case": copy.deepcopy(dict(case)),
        "domain_case": copy.deepcopy(dict(frozen)),
        "goal_authority": goal_binding,
        "root_visual_domain_decision": decision_binding,
        "root_visual_domain_decision_path": str(decision_path),
        "domain_membership": membership,
        "visual_evidence": visual_evidence,
        "visual_evidence_bindings": visual_bindings,
        "physical_domain": domain_binding,
        "case_manifest": manifest_binding,
        "actual_case_bindings": actual_bindings,
    }


def _validate_index(index: Mapping[str, Any]) -> None:  # noqa: F811
    _validate_index_v2(index)


def _validate_scope(  # noqa: F811
    request: Mapping[str, Any],
    entry: Mapping[str, Any],
    index: Mapping[str, Any],
    index_path: Path,
    hashes: MutableMapping[str, str],
) -> dict[str, Any]:
    return _validate_scope_v2(request, entry, index, index_path, hashes)


def _collect_request_bindings_v2(value: Any, result: list[str], seen: set[str]) -> None:
    for binding in _binding_file_values(value):
        path = binding.get("path")
        if isinstance(path, str) and path not in seen:
            result.append(path)
            seen.add(path)


def build_request(  # noqa: F811
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
    prospective_domain_launch: bool | None = None,
    shared_initial_state: Mapping[str, Any] | None = None,
    **resource_fields: Any,
) -> dict[str, Any]:
    """Build a frozen request; it never launches GenCase, solver, or ParaView."""

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
    elif "command" not in result:
        result["command"] = copy.deepcopy(result.get("actual_solver_command", result.get("solver_command")))
    if cwd is not None:
        result["cwd"] = cwd
    elif "cwd" not in result:
        result["cwd"] = result.get("actual_solver_cwd", result.get("solver_cwd"))
    if complete_event_window_s is not None:
        result["complete_event_window_s"] = list(complete_event_window_s)
    elif "complete_event_window_s" not in result:
        result["complete_event_window_s"] = copy.deepcopy(result.get("event_window_s", EXPECTED_WINDOW))
    if "numerical_recipe" not in result and "numerical_recipe_hash" in result:
        result["numerical_recipe"] = result["numerical_recipe_hash"]
    if prospective_domain_launch is None:
        prospective_domain_launch = str(result.get("role", "")).startswith("interior") or result.get("visual_review_pending") is True
    result["prospective_domain_launch"] = bool(prospective_domain_launch)
    result.setdefault("production_approval", "none")
    if shared_initial_state is not None:
        result["clone_parent_evidence"] = copy.deepcopy(dict(shared_initial_state))

    source_files = [Path(adapter_path).resolve(), Path(__file__).resolve()]
    if strict_path is None:
        strict_path = _source_module_path("ds_data02_strict_dispatch_v1")
    if runtime_path is None:
        runtime_path = _source_module_path("ds_data02_runtime_v2")
    source_files.extend((Path(strict_path).resolve(), Path(runtime_path).resolve()))
    collected: list[str] = []
    seen: set[str] = set()
    if input_files is not None:
        for value in input_files:
            if isinstance(value, str) and value not in seen:
                collected.append(value)
                seen.add(value)
    _collect_request_bindings_v2(result, collected, seen)
    if shared_initial_state is not None:
        _collect_request_bindings_v2(shared_initial_state, collected, seen)
    all_files: list[Path] = []
    seen_paths: set[Path] = set()
    for value in [*source_files, *(Path(path).resolve() for path in collected)]:
        if value not in seen_paths:
            all_files.append(value)
            seen_paths.add(value)
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


def build_prospective_request(
    manifest: Mapping[str, Any],
    case_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build one explicit prospective request from a frozen manifest row."""

    rows = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if not isinstance(rows, list):
        raise VisualAuthorizationError("prospective manifest cases must be a list")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == case_id]
    if len(matches) != 1:
        raise VisualAuthorizationError("prospective case is not uniquely present in manifest")
    case = matches[0]
    if not str(case.get("role", "")).startswith("interior"):
        raise VisualAuthorizationError("build_prospective_request accepts an explicit interior row")
    if case.get("visual_provenance", {}).get("root_visual_decision") is not None:
        raise VisualAuthorizationError("prospective case already carries a case visual decision")
    shared_value = manifest.get("shared_initial_state")
    shared = copy.deepcopy(dict(shared_value)) if isinstance(shared_value, Mapping) else None
    if shared is not None and isinstance(manifest.get("source_documents"), Mapping):
        shared["source_documents"] = copy.deepcopy(dict(manifest["source_documents"]))
    return build_request(case, shared_initial_state=shared, prospective_domain_launch=True, **kwargs)


__all__ = [
    "CAMPAIGN_ID",
    "CASE_DECISION_SCHEMA",
    "DOMAIN_DECISION_SCHEMA",
    "EXPECTED_FRAME_COUNT",
    "EXPECTED_STAGE1_LABEL",
    "EXPECTED_WINDOW",
    "INDEX",
    "NUMERICAL_PRECISION_STATUS",
    "PRECISION_CONTEXT",
    "SCHEMA",
    "VISUAL_STAGE_PROFILE",
    "VisualAuthorizationError",
    "authorize",
    "build_request",
    "build_prospective_request",
    "digest",
    "revalidate_approval",
]
