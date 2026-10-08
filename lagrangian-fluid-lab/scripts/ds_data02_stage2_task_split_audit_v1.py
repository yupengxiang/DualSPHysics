#!/usr/bin/env python3
"""Resolve narrowly scoped development roles from exact source evidence.

The v1 equivalence audit intentionally excludes every CURRENT336 case from
promotion when recovery, time-window transfer, or trajectory content proof is
unknown.  This forward worker keeps that global result immutable and adds
task-scoped roles only when an independently produced, hashed product proves
the smaller task.  A metadata task may use all 336 rows; native cause/mass/
censoring uses the exact 118-case mechanism/label products; raw-to-typed uses
the one F1 byte-identity anchor; source-role diagnostics use three actual
materialized label reports.  None of these scopes prove physical fate,
legal flux, dynamics, QN/QE, recovery safety, or a prospective scientific
split.

Only JSON proof/report/receipt files are read.  This worker never opens H5,
BI4, raw trajectories, solver output, or model input.  Every evidence path is
hashed on the current run and compared with the request's exact digest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
_V1_PATH = SCRIPT.with_name("ds_data02_stage2_equivalence_split_audit_v1.py")
_SPEC = importlib.util.spec_from_file_location("_ds02_equivalence_split_v1_for_task", _V1_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load {_V1_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)

SCHEMA = "ds02.stage2.task-equivalence-split-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.task-split-evidence-manifest.v1"
TASKS = {
    "metadata_lineage_audit": {"required": {"source_proof_v21", "source_index_v22", "scientific_audit_v23"}, "selector": {"all_current"}},
    "native_cause_mass_censoring": {"required": {"all118_impact_v8", "all118_label_calibration", "all118_mechanism_v2"}, "selector": {"mechanism_cases"}},
    "raw_to_typed_identity": {"required": {"f1_raw_to_typed_proof"}, "selector": {"explicit"}},
    "label_source_role_diagnostics": {"required": {"f1_label_report", "f2_recovery_report", "f3_label_report"}, "selector": {"explicit"}},
}
ROLES = ("development_train", "development_validation", "development_test")


class TaskSplitError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise TaskSplitError(f"{label} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise TaskSplitError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(str(value), label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaskSplitError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise TaskSplitError(f"{label} must be an object")
    return path, payload


def _exact_current_binding(payload: dict[str, Any], current_sha: str, count: int, label: str) -> None:
    binding = payload.get("current_binding")
    if not isinstance(binding, dict) or binding.get("sha256") != current_sha or binding.get("case_count") != count:
        raise TaskSplitError(f"{label} is not bound to this CURRENT336")
    families = binding.get("family_counts")
    if families != {f"F{i}": 48 for i in range(1, 8)}:
        raise TaskSplitError(f"{label} family counts are not CURRENT336")


def _validate_evidence_record(record: dict[str, Any], current_sha: str, count: int) -> dict[str, Any]:
    evidence_id = record.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id:
        raise TaskSplitError("evidence record lacks evidence_id")
    path = require_file(record.get("path"), f"evidence {evidence_id}")
    expected = record.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise TaskSplitError(f"evidence {evidence_id} lacks a SHA256")
    actual = sha256_file(path)
    if actual != expected:
        raise TaskSplitError(f"evidence {evidence_id} digest differs")
    _, payload = read_json(path, f"evidence {evidence_id}")
    kind = record.get("kind")
    if not isinstance(kind, str) or not kind:
        raise TaskSplitError(f"evidence {evidence_id} lacks kind")
    bound_files: list[dict[str, str]] = []
    if kind == "source_proof_v21":
        if payload.get("schema") != "ds02.stage2.current336-source-proof.v21":
            raise TaskSplitError("v21 source proof schema differs")
        _exact_current_binding(payload, current_sha, count, "v21 source proof")
        scope = payload.get("read_scope", {})
        if scope.get("current_json_opened") is not True or scope.get("hdf5_opened") is not False or scope.get("bi4_opened") is not False:
            raise TaskSplitError("v21 source proof read scope is not metadata-only")
        if payload.get("split_policy", {}).get("split_safe") is not False:
            raise TaskSplitError("v21 source proof cannot assert split safety")
    elif kind == "source_index_v22":
        if payload.get("schema") != "ds02.stage2.seven-family-source-access-index.v22":
            raise TaskSplitError("v22 source index schema differs")
        _exact_current_binding(payload, current_sha, count, "v22 source index")
        policy = payload.get("access_policy", {})
        if policy.get("exact_paths_only") is not True or policy.get("external_paths_are_provenance_only_until_parent_guard") is not True:
            raise TaskSplitError("v22 access policy is not exact/guarded")
        if payload.get("family_cards", {}).get("F1", {}).get("split_safe") is not False:
            raise TaskSplitError("v22 family cards did not preserve split_safe=false")
    elif kind == "scientific_audit_v23":
        if payload.get("schema") != "ds02.stage2.scientific-audit-independent-verification.v23":
            raise TaskSplitError("scientific v23 proof schema differs")
        catalog = payload.get("current_catalog", {})
        scope = str(payload.get("verification_scope", ""))
        if (catalog.get("sha256") != current_sha or payload.get("distinct_completed_cases") != count or
                "No extra root H5 content scan" not in scope or "No" not in scope or
                payload.get("goal_complete") is True):
            raise TaskSplitError("scientific v23 CURRENT/read/qualification scope differs")
    elif kind == "all118_impact_v8":
        if payload.get("schema") != "ds02.stage2.all118-impact-v8-independent-verification.v1" or payload.get("status") != "PASS_NATIVE_CAUSE_SOURCE_MASS_CENSORING_ACCOUNTING_ONLY":
            raise TaskSplitError("all118 impact proof is not source/mass/censor-only")
        coverage = payload.get("coverage", {})
        if coverage.get("case_count") != 118 or coverage.get("full_source_case_count") != 118 or coverage.get("partial_source_case_count") != 0:
            raise TaskSplitError("all118 impact coverage is incomplete")
        if payload.get("root_h5_or_raw_read") is not False:
            raise TaskSplitError("all118 impact proof did not prove no H5/raw read")
        claims = payload.get("claim_boundary", {})
        if claims.get("physical_fate") != "UNKNOWN" or claims.get("dynamical_impact") != "UNKNOWN":
            raise TaskSplitError("all118 impact proof overclaims fate/dynamics")
        for nested_name in ("output", "receipt"):
            nested = payload.get(nested_name)
            if not isinstance(nested, dict):
                raise TaskSplitError(f"all118 impact proof lacks {nested_name} binding")
            nested_path = require_file(nested.get("path"), f"all118 impact {nested_name}")
            nested_sha = nested.get("sha256")
            if not isinstance(nested_sha, str) or len(nested_sha) != 64 or sha256_file(nested_path) != nested_sha:
                raise TaskSplitError(f"all118 impact {nested_name} digest differs")
            bound_files.append({"role": nested_name, "path": str(nested_path), "sha256": nested_sha})
    elif kind == "all118_label_calibration":
        if payload.get("schema") != "ds02.stage2.label-calibration.v1" or payload.get("status") != "LABEL_CALIBRATED_SOURCE_MK_CENSORING_NO_MODEL":
            raise TaskSplitError("all118 label calibration is not source/censor-only")
        current = payload.get("current", {})
        if current.get("sha256") != current_sha or payload.get("coverage", {}).get("selected_case_count") != 118:
            raise TaskSplitError("all118 label calibration CURRENT/count differs")
        policy = payload.get("read_policy", {})
        if policy.get("h5_opened") is not False or policy.get("trajectory_content_opened") is not False:
            raise TaskSplitError("all118 label calibration read H5 content")
        if not isinstance(payload.get("cases"), list) or len(payload["cases"]) != 118:
            raise TaskSplitError("all118 label calibration lacks exact case records")
    elif kind == "all118_mechanism_v2":
        if payload.get("schema") != "ds02.stage2.omission-mechanism-probe.v2" or payload.get("status") != "MECHANISM_PROBE_SOURCE_CLOSED_NO_H5":
            raise TaskSplitError("all118 mechanism report is not source-closed/no-H5")
        policy = payload.get("read_policy", {})
        if policy.get("h5_opened") is not False or policy.get("trajectory_content_opened") is not False:
            raise TaskSplitError("all118 mechanism report read H5 content")
        cases = payload.get("cases")
        if not isinstance(cases, list) or len(cases) != 118:
            raise TaskSplitError("all118 mechanism report lacks 118 cases")
        source_report = payload.get("source_report", {})
        current = source_report.get("current", {}) if isinstance(source_report, dict) else {}
        # The mechanism producer's source report may bind CURRENT indirectly;
        # exact per-case identities below are the authoritative join.
        if current and current.get("sha256") not in {None, current_sha}:
            raise TaskSplitError("all118 mechanism source CURRENT differs")
    elif kind == "f1_raw_to_typed_proof":
        if payload.get("schema") != "ds02.stage2.f1-full161-raw-reconstruction-independent.v1" or payload.get("status") != "PASS_ACTUAL_FULL_RAW_RECONSTRUCTION_BYTE_IDENTICAL_CURRENT_TYPED":
            raise TaskSplitError("F1 raw-to-typed proof is not complete")
        if payload.get("root_original_reference_h5_reread") is not False or payload.get("root_native_raw_reread") is not False or payload.get("all_typed_fields_and_entire_file_byte_identity_verified") is not True:
            raise TaskSplitError("F1 raw-to-typed read/identity proof is not exact")
        if payload.get("portable_trial_completed") is not False:
            raise TaskSplitError("F1 proof unexpectedly claims portable replay")
        for nested_name in ("request", "receipt", "report", "converter_report"):
            nested_path_value = payload.get(nested_name)
            nested_sha = payload.get(f"{nested_name}_sha256")
            if nested_path_value is None and nested_sha is None:
                continue
            nested_path = require_file(nested_path_value, f"F1 raw-to-typed {nested_name}")
            if not isinstance(nested_sha, str) or len(nested_sha) != 64 or sha256_file(nested_path) != nested_sha:
                raise TaskSplitError(f"F1 raw-to-typed {nested_name} digest differs")
            bound_files.append({"role": nested_name, "path": str(nested_path), "sha256": nested_sha})
    elif kind == "label_report":
        schema = payload.get("schema")
        if schema == "ds02.stage2.family-label-report.v1":
            if payload.get("status") != "LABELS_MATERIALIZED_SOURCE_BOUND":
                raise TaskSplitError(f"{evidence_id} label report is incomplete")
            source = payload.get("source_join", {})
            if not isinstance(source, dict) or source.get("current_manifest", "") is None:
                raise TaskSplitError(f"{evidence_id} label report lacks source join")
            if payload.get("physical_fate") != "UNKNOWN" or payload.get("dynamic_impact") != "UNKNOWN":
                raise TaskSplitError(f"{evidence_id} label report overclaims fate/dynamics")
        elif schema == "ds02.stage2.f2-s1-trajectory-labels-recovery.v2":
            if payload.get("status") != "TRAJECTORY_LABELS_RECOVERED_FROM_COMPLETED_H5":
                raise TaskSplitError(f"{evidence_id} recovery report is incomplete")
            if payload.get("recovery", {}).get("source_trajectory_h5_opened") is not False:
                raise TaskSplitError(f"{evidence_id} recovery report lacks source H5 exclusion")
        else:
            raise TaskSplitError(f"{evidence_id} unsupported label report schema")
    else:
        raise TaskSplitError(f"unsupported evidence kind {kind!r}")
    expected_identity = record.get("identity")
    if expected_identity is not None:
        if not isinstance(expected_identity, dict):
            raise TaskSplitError(f"evidence {evidence_id} identity binding is not an object")
        if kind != "label_report":
            raise TaskSplitError(f"evidence {evidence_id} identity binding is unsupported for {kind}")
        if payload.get("schema") == "ds02.stage2.f2-s1-trajectory-labels-recovery.v2":
            actual_family = "F2"
            actual_physical = payload.get("physical_case_id")
        else:
            actual_family = payload.get("family_id")
            actual_physical = payload.get("physical_case_id")
        if (expected_identity.get("family_id"), expected_identity.get("physical_case_id")) != (actual_family, actual_physical):
            raise TaskSplitError(f"evidence {evidence_id} identity differs from producer report")
    return {"evidence_id": evidence_id, "kind": kind, "path": str(path), "sha256": actual,
            "payload": payload, "bound_files": bound_files}


def _mechanism_case_ids(evidence: dict[str, Any], current_keys: set[tuple[str, str]]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for item in evidence["payload"]["cases"]:
        family = item.get("family_id")
        physical = item.get("physical_case_id")
        if not isinstance(family, str) or not isinstance(physical, str) or (family, physical) not in current_keys:
            raise TaskSplitError("all118 mechanism case does not bind exact CURRENT physical identity")
        result.add((family, physical))
    if len(result) != 118 or {family for family, _ in result} != {"F2", "F4", "F6"}:
        raise TaskSplitError("all118 mechanism identity coverage is not F2/F4/F6 118-case union")
    return result


def _role_map(base_result: dict[str, Any], selected: set[tuple[str, str]]) -> tuple[dict[str, str], set[tuple[str, str]], set[str]]:
    members: dict[str, set[tuple[str, str]]] = {}
    for component in base_result["components"]:
        members[component["component_id"]] = {(x["family_id"], x["physical_case_id"]) for x in component["members"]}
    eligible_components = sorted(component_id for component_id, component_members in members.items()
                                if component_members & selected and component_members <= selected)
    partial_components = {component_id for component_id, component_members in members.items()
                          if component_members & selected and not component_members <= selected}
    roles = {component_id: ROLES[index % len(ROLES)] for index, component_id in enumerate(eligible_components)}
    return roles, {key for cid in partial_components for key in members[cid] & selected}, set(eligible_components)


def _selector(task: dict[str, Any], evidence: dict[str, dict[str, Any]], current_keys: set[tuple[str, str]]) -> set[tuple[str, str]]:
    selector = task.get("selector")
    if not isinstance(selector, dict) or selector.get("kind") not in TASKS[task.get("task_id", "")]["selector"]:
        raise TaskSplitError(f"task {task.get('task_id')} has unsupported selector")
    kind = selector["kind"]
    if kind == "all_current":
        return set(current_keys)
    if kind == "mechanism_cases":
        evidence_id = selector.get("evidence_id", "all118_mechanism_v2")
        return _mechanism_case_ids(evidence[evidence_id], current_keys)
    values = selector.get("cases")
    if not isinstance(values, list) or not values:
        raise TaskSplitError("explicit selector requires non-empty cases")
    result = set()
    for item in values:
        if not isinstance(item, dict):
            raise TaskSplitError("explicit selector case is not an object")
        key = (item.get("family_id"), item.get("physical_case_id"))
        if key not in current_keys:
            raise TaskSplitError(f"explicit task identity is not in CURRENT: {key}")
        result.add(key)
    return result


def audit(current_path: Path | str, lineage_path: Path | str, source_manifest_path: Path | str,
          evidence_manifest_path: Path | str) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    lineage_path, lineage = read_json(lineage_path, "lineage-v19")
    evidence_manifest_path, evidence_manifest = read_json(evidence_manifest_path, "task evidence manifest")
    if evidence_manifest.get("schema") != MANIFEST_SCHEMA:
        raise TaskSplitError("unsupported task evidence manifest schema")
    source_manifest_path, source_manifest = read_json(source_manifest_path, "v22 source access index")
    rows = _BASE._rows(current)
    links = _BASE._links(lineage)
    current_by_key, _ = _BASE._verify_membership(current_path, current, lineage, rows, links)
    current_sha = sha256_file(current_path)
    _exact_current_binding(source_manifest, current_sha, len(rows), "v22 source access index")
    evidence_entries = evidence_manifest.get("evidence")
    if not isinstance(evidence_entries, list) or not evidence_entries:
        raise TaskSplitError("task evidence list is required")
    evidence: dict[str, dict[str, Any]] = {}
    for entry in evidence_entries:
        if not isinstance(entry, dict):
            raise TaskSplitError("evidence entry is not an object")
        normalized = _validate_evidence_record(entry, current_sha, len(rows))
        if normalized["evidence_id"] in evidence:
            raise TaskSplitError("duplicate evidence id")
        evidence[normalized["evidence_id"]] = normalized
    mechanism_evidence = evidence.get("all118_mechanism_v2")
    label_evidence = evidence.get("all118_label_calibration")
    if mechanism_evidence is not None and label_evidence is not None:
        mechanism_keys = {
            (item.get("family_id"), item.get("case_key"))
            for item in mechanism_evidence["payload"].get("cases", [])
            if isinstance(item, dict)
        }
        label_keys = {
            (item.get("family_id"), item.get("case_key"))
            for item in label_evidence["payload"].get("cases", [])
            if isinstance(item, dict)
        }
        if len(mechanism_keys) != 118 or len(label_keys) != 118 or mechanism_keys != label_keys:
            raise TaskSplitError("all118 mechanism and label products do not bind the same exact case keys")
    base_result = _BASE.audit(current_path, lineage_path)
    current_keys = set(current_by_key)
    tasks = evidence_manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise TaskSplitError("task list is required")
    task_outputs = []
    globally_assigned: dict[tuple[str, str], set[str]] = {}
    for task in tasks:
        if not isinstance(task, dict) or task.get("task_id") not in TASKS:
            raise TaskSplitError(f"unsupported task {task.get('task_id') if isinstance(task, dict) else None}")
        task_id = task["task_id"]
        required = TASKS[task_id]["required"]
        supplied = set(task.get("required_evidence", []))
        if supplied != required or not supplied <= set(evidence):
            raise TaskSplitError(f"task {task_id} evidence set differs from fixed requirement")
        selected = _selector(task, evidence, current_keys)
        role_by_component, partial, eligible_components = _role_map(base_result, selected)
        records = []
        for key in sorted(current_keys):
            base_record = next(row for row in base_result["cases"] if (row["family_id"], row["physical_case_id"]) == key)
            component_id = base_record["component_id"]
            if key not in selected:
                task_status = "OUT_OF_SCOPE"
                role = "development_task_out_of_scope"
            elif key in partial:
                task_status = "UNRESOLVED_COMPONENT_BOUNDARY"
                role = "development_unresolved_excluded"
            else:
                task_status = "ELIGIBLE_FOR_TASK_SCOPE"
                role = role_by_component[component_id]
                globally_assigned.setdefault(key, set()).add(task_id)
            records.append({
                "family_id": key[0], "physical_case_id": key[1],
                "runtime_case_alias": base_record.get("runtime_case_alias"),
                "component_id": component_id,
                "task_status": task_status, "task_development_role": role,
                "global_equivalence_unresolved": base_record["unresolved_reasons"],
                "global_promotion_status_unchanged": "UNRESOLVED_EXCLUDED",
            })
        role_counts = {role: sum(item["task_development_role"] == role for item in records) for role in ROLES}
        selected_eligible = [item for item in records if item["task_status"] == "ELIGIBLE_FOR_TASK_SCOPE"]
        task_outputs.append({
            "task_id": task_id,
            "status": "RESOLVED_TASK_SCOPE_WITH_GLOBAL_EXCLUSIONS_PRESERVED" if selected_eligible else "NO_TASK_ELIGIBLE_CASES",
            "selector": task["selector"],
            "required_evidence": sorted(required),
            "selected_case_count": len(selected),
            "eligible_case_count": len(selected_eligible),
            "partial_component_case_count": len(partial),
            "eligible_component_count": len(eligible_components),
            "role_case_counts": role_counts,
            "roles_sufficient_for_three_way_split": len(eligible_components) >= 3,
            "component_unit_preserved": True,
            "cases": records,
            "evidence_bindings": [{k: value[k] for k in ("evidence_id", "kind", "path", "sha256", "bound_files")} for value in (evidence[item] for item in sorted(required))],
            "claim_boundary": {
                "task_scope": task.get("claim_boundary", "diagnostic/task-input eligibility only"),
                "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN",
                "recovery_safe": "UNKNOWN", "split_safe": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "qualification_credit": "none",
            },
        })
    all_global_excluded = all(record.get("global_promotion_status_unchanged") == "UNRESOLVED_EXCLUDED"
                              for task in task_outputs for record in task["cases"])
    return {
        "schema": SCHEMA,
        "status": "PASS_TASK_SCOPED_ELIGIBILITY_GLOBAL_UNRESOLVED_PRESERVED",
        "inputs": {
            "current": {"path": str(current_path), "sha256": current_sha},
            "lineage_v19": {"path": str(lineage_path), "sha256": sha256_file(lineage_path)},
            "source_index_v22": {"path": str(source_manifest_path), "sha256": sha256_file(source_manifest_path)},
            "evidence_manifest": {"path": str(evidence_manifest_path), "sha256": sha256_file(evidence_manifest_path)},
        },
        "universe": {"current_case_count": len(rows), "all_current_cases_exposed": True, "hidden_test_claim": False},
        "tasks": task_outputs,
        "diagnostics": {
            "evidence_count": len(evidence), "task_count": len(task_outputs),
            "global_promotion_exclusion_unchanged": all_global_excluded,
            "component_unit_preserved": all(task["component_unit_preserved"] for task in task_outputs),
            "loaded_product_reference_json_validated": True,
            "h5_bi4_trajectory_opened": False,
            "model_invoked": False,
        },
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def write_json(payload: dict[str, Any], output: Path | str) -> Path:
    path = Path(output).expanduser().resolve()
    if path.exists():
        raise TaskSplitError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def make_request(current_path: Path | str, lineage_path: Path | str, source_manifest_path: Path | str,
                 evidence_manifest_path: Path | str, output: Path | str, worktree_root: Path | str,
                 runtime_paths: Iterable[Path | str] | None = None) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    lineage_path, _ = read_json(lineage_path, "lineage-v19")
    source_manifest_path, _ = read_json(source_manifest_path, "v22 source access index")
    evidence_manifest_path, evidence_manifest = read_json(evidence_manifest_path, "task evidence manifest")
    _BASE._rows(current)
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_task_split_audit_v1.py"
    v1_worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_equivalence_split_audit_v1.py"
    if runtime_paths is None:
        runtime_paths = [root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
                         root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
                         root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
                         root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    paths = [worker, v1_worker, current_path, lineage_path, source_manifest_path, evidence_manifest_path,
             *[Path(path).expanduser().resolve() for path in runtime_paths]]
    for item in evidence_manifest.get("evidence", []):
        paths.append(require_file(item.get("path"), f"evidence {item.get('evidence_id')}"))
    # Bind nested output/receipt/reference JSONs discovered from each proof;
    # the guarded child then consumes the same bytes that the validator checks.
    for item in evidence_manifest.get("evidence", []):
        _, payload = read_json(item.get("path"), f"evidence {item.get('evidence_id')}")
        kind = item.get("kind")
        nested_names = ("output", "receipt") if kind == "all118_impact_v8" else (
            "request", "receipt", "report", "converter_report") if kind == "f1_raw_to_typed_proof" else ()
        for nested_name in nested_names:
            nested_path = payload.get(nested_name)
            if nested_path:
                paths.append(require_file(nested_path, f"evidence {item.get('evidence_id')} {nested_name}"))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes = {str(path): sha256_file(path) for path in unique if path.is_file()}
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": "ds02.stage2.task-equivalence-split-request.v1",
        "attempt_id": "current336-task-equivalence-split-v1", "case_id": "DS02_STAGE2_CURRENT336_TASK_SCOPED_ELIGIBILITY_V1",
        "family_id": "F1_F2_F3_F4_F5_F6_F7", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1,
        "max_wall_seconds": 900, "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "run", "--current", str(current_path), "--lineage", str(lineage_path), "--source-index", str(source_manifest_path), "--evidence-manifest", str(evidence_manifest_path), "--output", "{attempt_root}/current336-task-equivalence-split-v1.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": not missing, "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {"small_json_bytes_read": sum(path.stat().st_size for path in unique if path.is_file()), "original_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN", "qualification_credit": "none"},
        "missing_guard_sources": missing,
        "request_note": "Task-specific metadata/native-cause/source-role eligibility only; v1 global unresolved exclusions are preserved. JSON proof/report/receipt inputs are independently hashed; no H5/BI4/raw trajectory content is opened.",
    }
    write_json(request, output)
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--current", type=Path, required=True); run.add_argument("--lineage", type=Path, required=True)
    run.add_argument("--source-index", type=Path, required=True); run.add_argument("--evidence-manifest", type=Path, required=True); run.add_argument("--output", type=Path, required=True)
    req = sub.add_parser("make-request")
    req.add_argument("--current", type=Path, required=True); req.add_argument("--lineage", type=Path, required=True); req.add_argument("--source-index", type=Path, required=True); req.add_argument("--evidence-manifest", type=Path, required=True); req.add_argument("--output", type=Path, required=True); req.add_argument("--worktree-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        write_json(audit(args.current, args.lineage, args.source_index, args.evidence_manifest), args.output)
    else:
        make_request(args.current, args.lineage, args.source_index, args.evidence_manifest, args.output, args.worktree_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
