#!/usr/bin/env python3
"""Adopt the Core execution contract and compute evidence-based completion.

Legacy campaign bytes are referenced, never rewritten or interpreted as fresh
budget. A completed job is not a qualified scope or a successful model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import posixpath
from pathlib import Path
import subprocess

try:
    from scripts.core_runtime import atomic_json, canonical, digest
    from scripts.core_material_acceptance import validate_source_coverage
except ModuleNotFoundError:
    from core_runtime import atomic_json, canonical, digest
    from core_material_acceptance import validate_source_coverage

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1"
SEEDS = [17, 29, 43]
MODELS = ["mlp", "graph_raw", "graph_residual"]
FORMAL_UPDATES = 32000
MINIMUM_T1_CASE_RUNS = 432
MINIMUM_MATERIAL_CASE_RUNS = 288


def expected_runs():
    return [f"{model}-seed{seed}" for model in MODELS for seed in SEEDS]


def _rooted_path(value, data_root, label):
    """Resolve a portable reference without allowing symlink/path escapes."""
    if not isinstance(value, (str, Path)):
        raise ValueError(f"{label} path must be a relative path within data_root")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path must be portable and within data_root")
    root = Path(data_root).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} path must be within data_root") from exc
    return path


def adopt(lab=LAB, root=ROOT):
    lab, root = Path(lab).resolve(), Path(root).resolve()
    path = root / "adoption.json"
    if path.exists():
        return json.loads(path.read_text())
    historical = []
    for relative in ("campaigns/l2-multifamily/ledger.json",
                     "campaigns/l2-multifamily/resume-c6b28c8/resource-reconciliation.json",
                     "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"):
        source = lab / relative
        if source.exists():
            historical.append({"path": relative, "sha256": digest(source)})
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=lab, text=True).strip()
    document = {
        "schema": "core.adoption.v1", "adopted_at_utc": datetime.now(timezone.utc).isoformat(),
        "authorization": "User explicitly requested implementation of the complete Core plan, both hosts, GPU colocation, and milestone-measured resource policy.",
        "baseline_commit": commit, "release_role": "internal_development",
        "historical_evidence": historical, "historical_usage_reset": False,
        "resource_policy": {"global_hours_cap": None, "milestone_estimates_required": True,
                            "hosts": ["ada", "h200"], "fixed_jobs_per_gpu_cap": None,
                            "gpu_reservation_peak_factor": 1.2, "gpu_safety_fraction": .1,
                            "gpu_safety_min_mib": 4096, "host_ram_safety_fraction": .15,
                            "cpu_reservation_fraction": .8, "initial_heavy_io_tokens": 2,
                            "failed_attempts_counted": True,
                            "no_interruption_of_unrelated_processes": True},
        "targets": {"t1_distinct_families": 3, "cases_per_t1_family": 32,
                    "macro_t2_distinct_families": 2, "material_cases_per_family": 32,
                    "training_runs": expected_runs(), "updates_per_run": FORMAL_UPDATES,
                    "minimum_t1_case_runs": MINIMUM_T1_CASE_RUNS,
                    "minimum_material_case_runs": MINIMUM_MATERIAL_CASE_RUNS,
                    "evaluation_missing": 0, "different_host_reproduction_required": True},
        "qualification_axes": ["T1_numerical", "T2_macro", "T2_path", "external_physical_validation"],
        "family_priority": ["F3", "F4", "F1", "F2"],
        "material_family_priority": ["F3", "F4", "F1", "F2"],
        "retry_policy": {"hypotheses_per_failure_mechanism": 2,
                         "canaries_per_hypothesis": 1, "repaired_infrastructure_retries": 1,
                         "no_threshold_relaxation_after_results": True},
        "training": {"model_configs": MODELS, "seeds": SEEDS, "updates": FORMAL_UPDATES,
                     "centers_per_update": 256, "history_states": 1, "hidden": 64,
                     "message_passing_layers": 2, "radius_over_h": 2, "max_neighbors": 64,
                     "optimizer": "Adam", "learning_rate": .001,
                     "full_validation_steps": [8000, 16000, 24000, 32000]},
        "scientific_matrices": {"new_t1_range": {"space_cells": 13, "time_cadence_cells": 2},
                                "macro_t2_per_scope": 33},
        "completion_policy": "typed evidence and complete denominators; not file existence, job exit, or report count",
    }
    atomic_json(path, document)
    return document


def load_evidence(reference, data_root):
    """Verify receipt identity and content; failure is explicit, never a pass."""
    if (not isinstance(reference, dict) or not {"path", "sha256"} <= set(reference)
            or not isinstance(reference["sha256"], str)):
        raise ValueError("a hashed evidence reference is required")
    path = _rooted_path(reference["path"], data_root, "evidence")
    if digest(path) != reference["sha256"]:
        raise ValueError("evidence hash mismatch: " + str(Path(reference["path"])))
    return json.loads(path.read_text())


def _contract_evidence_reference(name, registry, data_root):
    """Resolve a typed contract without mutating the scientific registry.

    Contract audits are infrastructure-wide evidence.  They are indexed in a
    separate, hash-bound catalog so a later audit does not rewrite a historical
    CFD scope review's central-registry snapshot.  A registry entry still wins
    when one is explicitly present, preserving the original completion API.
    """
    reference = registry.get(name)
    if reference is not None:
        return reference
    try:
        catalog_path = _rooted_path(
            "campaigns/core-v1/contract-evidence.json", data_root, "contract catalog")
    except ValueError:
        return None
    if not catalog_path.is_file():
        return None
    try:
        catalog = json.loads(catalog_path.read_text())
        contracts = catalog.get("contracts", {})
        reference = contracts.get(name)
        if not isinstance(reference, dict):
            return None
        # The catalog itself is not a scientific qualification record, but its
        # entry must still be a normal portable hashed evidence reference.
        if not {"path", "sha256"} <= set(reference):
            return None
        return reference
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


_REPRODUCTION_CLAIM_FIELDS = (
    "source_host", "reproduction_host", "source_data_root", "reproduction_data_root",
    "diagnostic_only", "cross_host_reproduction", "full_horizon_reproduction",
    "full_product_reproduction", "reader_reproduced", "prediction_reproduced",
    "scoring_reproduced", "predictor_future_state_inputs",
)
_REPRODUCTION_EVIDENCE_ROLES = {
    "source_host", "reproduction_host", "data_roots", "reader", "prediction", "scoring",
}


def _canonical_data_root(value):
    """Lexically normalize a remote POSIX root without consulting this host."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if not value.startswith("/"):
        return None
    return posixpath.normpath(value)


def _valid_sha256(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _component_output_passes(component, report):
    """Require a typed, successful output artifact for each product stage."""
    if not isinstance(report, dict):
        return False
    if component == "reader":
        return (
            report.get("schema") in ("core.reader_reproduction.v1", "core.verification.v1")
            and report.get("passed") is True
        )
    if component == "prediction":
        return (
            report.get("schema") == "core.model_reproduction.v1"
            and report.get("passed") is True
            and report.get("full_horizon_reproduction") is True
            and report.get("full_product_reproduction") is True
            and report.get("predictor_future_state_inputs") is False
        )
    if component == "scoring":
        metrics = report.get("metrics")
        return (
            report.get("schema") == "core.model_reproduction.score.v1"
            and isinstance(metrics, dict)
            and type(metrics.get("registered_cases")) is int
            and metrics["registered_cases"] > 0
            and metrics.get("complete_fraction") == 1.0
            and metrics.get("missing_execution") == 0
            and isinstance(report.get("cases"), list)
            and bool(report["cases"])
            and report.get("predictor_future_state_inputs") is False
        )
    return False


def _independent_reproduction_binding(receipt):
    """Canonical claims and evidence references that a root review must bind."""
    return {
        "claims": {field: receipt.get(field) for field in _REPRODUCTION_CLAIM_FIELDS},
        "supporting_evidence": receipt.get("supporting_evidence"),
    }


def _independent_reproduction_passes(receipt, data_root):
    """Require the complete, non-diagnostic product chain on a relocated root.

    A cross-host numerical comparison or full-horizon rollout alone is not a
    product reproduction.  The plan requires the reader, autonomous
    prediction, and scoring chain to work on another physical host and a
    distinct data root.  Summary booleans are insufficient: the separately
    hash-bound root review must bind the exact claims and hash-bound evidence
    for host identity, relocation, reader, prediction, and scoring.
    """
    if not isinstance(receipt, dict):
        return False
    source_host = receipt.get("source_host")
    reproduction_host = receipt.get("reproduction_host")
    source_root = _canonical_data_root(receipt.get("source_data_root"))
    reproduction_root = _canonical_data_root(receipt.get("reproduction_data_root"))
    base_claims_pass = (
        receipt.get("schema") == "core.reproduction.v1"
        and receipt.get("passed") is True
        and receipt.get("diagnostic_only") is False
        and receipt.get("cross_host_reproduction") is True
        and receipt.get("full_horizon_reproduction") is True
        and receipt.get("full_product_reproduction") is True
        and receipt.get("reader_reproduced") is True
        and receipt.get("prediction_reproduced") is True
        and receipt.get("scoring_reproduced") is True
        and receipt.get("predictor_future_state_inputs") is False
        and isinstance(source_host, str)
        and bool(source_host.strip())
        and isinstance(reproduction_host, str)
        and bool(reproduction_host.strip())
        and source_host.strip().rstrip(".").casefold()
        != reproduction_host.strip().rstrip(".").casefold()
        and source_root is not None
        and reproduction_root is not None
        and source_root != reproduction_root
    )
    if not base_claims_pass:
        return False

    try:
        evidence_refs = receipt.get("supporting_evidence")
        if not isinstance(evidence_refs, dict) or set(evidence_refs) != _REPRODUCTION_EVIDENCE_ROLES:
            return False
        evidence = {
            role: load_evidence(reference, data_root)
            for role, reference in evidence_refs.items()
        }
        source_host_evidence = evidence["source_host"]
        reproduction_host_evidence = evidence["reproduction_host"]
        roots_evidence = evidence["data_roots"]
        if any(not isinstance(item, dict) for item in evidence.values()):
            return False

        source_host_id = source_host_evidence.get("physical_host_id")
        reproduction_host_id = reproduction_host_evidence.get("physical_host_id")
        if not (
            source_host_evidence.get("schema") == "core.reproduction.host_identity.v1"
            and source_host_evidence.get("passed") is True
            and source_host_evidence.get("hostname") == source_host
            and isinstance(source_host_id, str) and bool(source_host_id.strip())
            and reproduction_host_evidence.get("schema") == "core.reproduction.host_identity.v1"
            and reproduction_host_evidence.get("passed") is True
            and reproduction_host_evidence.get("hostname") == reproduction_host
            and isinstance(reproduction_host_id, str) and bool(reproduction_host_id.strip())
            and source_host_id != reproduction_host_id
        ):
            return False

        if not (
            roots_evidence.get("schema") == "core.reproduction.data_roots.v1"
            and roots_evidence.get("passed") is True
            and roots_evidence.get("source_data_root") == receipt.get("source_data_root")
            and roots_evidence.get("reproduction_data_root") == receipt.get("reproduction_data_root")
            and roots_evidence.get("different_data_root") is True
            and _valid_sha256(roots_evidence.get("source_manifest_sha256"))
            and _valid_sha256(roots_evidence.get("reproduction_manifest_sha256"))
        ):
            return False
        source_manifest = load_evidence(roots_evidence.get("source_manifest"), data_root)
        reproduction_manifest = load_evidence(roots_evidence.get("reproduction_manifest"), data_root)
        if not (
            isinstance(source_manifest, dict)
            and source_manifest.get("schema") == "core.reproduction.package_manifest.v1"
            and source_manifest.get("data_root") == receipt.get("source_data_root")
            and isinstance(reproduction_manifest, dict)
            and reproduction_manifest.get("schema") == "core.reproduction.package_manifest.v1"
            and reproduction_manifest.get("data_root") == receipt.get("reproduction_data_root")
            and _valid_sha256(source_manifest.get("package_sha256"))
            and source_manifest.get("package_sha256") == reproduction_manifest.get("package_sha256")
            and roots_evidence.get("source_manifest_sha256") == roots_evidence["source_manifest"].get("sha256")
            and roots_evidence.get("reproduction_manifest_sha256")
            == roots_evidence["reproduction_manifest"].get("sha256")
        ):
            return False

        expected_component_claims = {
            "reader": "reader_reproduced",
            "prediction": "prediction_reproduced",
            "scoring": "scoring_reproduced",
        }
        for component, claim in expected_component_claims.items():
            report = evidence[component]
            if not (
                report.get("schema") == "core.reproduction.component.v1"
                and report.get("component") == component
                and report.get("passed") is True
                and report.get(claim) is True
                and report.get("physical_host_id") == reproduction_host_id
                and _canonical_data_root(report.get("data_root")) == reproduction_root
            ):
                return False
            if component == "prediction" and not (
                report.get("autonomous") is True
                and report.get("full_horizon") is True
                and report.get("future_state_inputs") is False
            ):
                return False
            output_ref = report.get("output_report")
            output_report = load_evidence(output_ref, data_root)
            if not _component_output_passes(component, output_report):
                return False

        root_review_ref = receipt.get("root_review")
        root_review = load_evidence(root_review_ref, data_root)
        if not isinstance(root_review, dict):
            return False
        review_binding = _independent_reproduction_binding(receipt)
        review_binding_sha256 = hashlib.sha256(canonical(review_binding).encode("utf-8")).hexdigest()
        required_review_checks = {
            "distinct_physical_hosts": True,
            "distinct_data_roots": True,
            "reader_evidence_verified": True,
            "prediction_evidence_verified": True,
            "scoring_evidence_verified": True,
        }
        return (
            root_review.get("schema") == "core.reproduction.root_review.v1"
            and root_review.get("status") in ("pass", "passed")
            and root_review.get("diagnostic_only") is False
            and root_review.get("full_core_reproduction_proven") is True
            and root_review.get("reviewed_binding_sha256") == review_binding_sha256
            and root_review.get("verified_checks") == required_review_checks
        )
    except (KeyError, ValueError, OSError, TypeError):
        return False


def _reject_nonformal_or_nonroot(payload, label):
    """Reject explicit diagnostic/blocked evidence instead of inferring credit."""
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is not a JSON object")
    if payload.get("qualification_only") is True or payload.get("diagnostic_only") is True:
        raise ValueError(f"{label} is qualification-only/diagnostic evidence")
    if (payload.get("formal_eligible") is False
            or payload.get("formal_release") is False
            or payload.get("formal") is False):
        raise ValueError(f"{label} is not formal evidence")
    if payload.get("root_review_only") is True or payload.get("root_admitted") is False:
        raise ValueError(f"{label} is not root-admitted evidence")
    root_admission = payload.get("root_admission")
    if isinstance(root_admission, dict) and root_admission.get("granted") is False:
        raise ValueError(f"{label} lacks root admission")
    root_review = payload.get("root_review")
    if root_review is False or (isinstance(root_review, dict) and root_review.get("granted") is False):
        raise ValueError(f"{label} lacks root review")


def _require_passed_root_review(reference, data_root, label):
    """Require a hash-bound root receipt before granting formal material credit."""
    if not isinstance(reference, dict):
        raise ValueError(f"{label} root review is missing")
    receipt = load_evidence(reference, data_root)
    if not isinstance(receipt, dict) or (
            receipt.get("status") not in ("pass", "passed", "approved", "accepted")
            and receipt.get("passed") is not True):
        raise ValueError(f"{label} root review is not passed")


def _validate_evaluation_receipt(receipt, *, axis, run_id, case_id):
    """Validate one formal evaluation receipt before counting its case.

    Registry membership alone is not evaluation evidence.  The receipt must
    retain its formal/autonomous identity, the selected case registry, and a
    fixed-denominator score/rollout row.  A model failure is admissible as a
    negative benchmark result, but it must still carry the same denominator
    and an explicit failure category.
    """
    if not isinstance(receipt, dict) or receipt.get("schema") != "core.evaluation.v1":
        raise ValueError("evaluation receipt schema mismatch")
    if receipt.get("execution_status") not in ("complete", "model_failed"):
        raise ValueError("evaluation missing or infrastructure failure")
    if receipt.get("axis") != axis or receipt.get("run_id") != run_id or receipt.get("case_id") != case_id:
        raise ValueError("evaluation identity mismatch")
    if (receipt.get("formal_eligible") is not True
            or receipt.get("diagnostic") is not False
            or receipt.get("autonomous") is not True
            or receipt.get("future_state_inputs") is not False):
        raise ValueError("evaluation is not a formal autonomous future-state-free result")

    registered_case_ids = receipt.get("registered_case_ids")
    selected_case_ids = receipt.get("selected_case_ids")
    if (not isinstance(registered_case_ids, list)
            or not registered_case_ids
            or len(set(registered_case_ids)) != len(registered_case_ids)
            or not isinstance(selected_case_ids, list)
            or not selected_case_ids
            or len(set(selected_case_ids)) != len(selected_case_ids)
            or case_id not in selected_case_ids
            or not set(selected_case_ids).issubset(registered_case_ids)):
        raise ValueError("evaluation case registry is missing or inconsistent")
    if receipt.get("registered_case_count") != len(registered_case_ids):
        raise ValueError("evaluation registered case denominator mismatch")
    if receipt.get("case_count") != len(selected_case_ids):
        raise ValueError("evaluation selected case denominator mismatch")

    expected_frames = receipt.get("expected_frames")
    if not isinstance(expected_frames, dict) or case_id not in expected_frames:
        raise ValueError("evaluation frame denominator is missing")
    expected = expected_frames[case_id]
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ValueError("evaluation frame denominator is invalid")
    cases = receipt.get("cases")
    row = cases.get(case_id) if isinstance(cases, dict) else None
    if not isinstance(row, dict):
        raise ValueError("evaluation case score row is missing")
    score = row.get("score")
    rollout = row.get("rollout")
    if not isinstance(score, dict) or not isinstance(rollout, dict):
        raise ValueError("evaluation score/rollout row is incomplete")
    if score.get("expected_frames") != expected:
        raise ValueError("evaluation score frame denominator mismatch")
    selection_score = score.get("selection_score")
    if (isinstance(selection_score, bool)
            or not isinstance(selection_score, (int, float))
            or not math.isfinite(float(selection_score))
            or not 0 <= float(selection_score) <= 1):
        raise ValueError("evaluation selection score is invalid")
    complete = score.get("complete")
    executed = score.get("executed")
    if not isinstance(complete, bool) or not isinstance(executed, bool):
        raise ValueError("evaluation score completion flags are invalid")
    failure_category = score.get("failure_category")
    if complete and (not executed or failure_category is not None):
        raise ValueError("completed evaluation score has invalid failure metadata")
    if not complete and (not isinstance(failure_category, str) or not failure_category):
        raise ValueError("incomplete evaluation score lacks failure category")
    if rollout.get("expected_frames") != expected or rollout.get("frames_expected") != expected:
        raise ValueError("evaluation rollout frame denominator mismatch")


def import_registered_f3(lab=LAB, root=ROOT):
    """Carry forward the explicitly preserved qualification, without enlarging it."""
    lab, root = Path(lab).resolve(), Path(root).resolve()
    canonical_path = lab / "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"
    gate_path = lab / "campaigns/l1-resume/continuation/F3-075-REF0081818-GATE.json"
    canonical_manifest = json.loads(canonical_path.read_text())
    gate = json.loads(gate_path.read_text())
    scores_path = lab / gate["scoring_evidence_path"]
    if digest(scores_path) != gate["scoring_evidence_sha256"]:
        raise ValueError("historical score evidence hash changed")
    scores = json.loads(scores_path.read_text())
    kinds = {x["kind"] for x in scores["panels"]}
    required = {"zero_drive_vs_initial", "output_interpolation", "temporal", "nominal_reference_spatial",
                "endpoint_low", "endpoint_high", "independent_internal_spatial"}
    if gate["status"] != "passed" or scores["status"] != "passed" or not required <= kinds or any(p["status"] != "passed" for p in scores["panels"]):
        raise ValueError("registered qualification no longer has all required passing panels")
    def reference(path):
        return {"path":str(Path(path).relative_to(lab)),"sha256":digest(path)}
    qualification_path = root / "evidence/f3-inherited-qualification.json"
    qualification = {"schema":"core.qualification.v1","scope_id":gate["recipe_id"],"family":"F3",
                     "T1_numerical":True,"T2_macro":False,"T2_path":False,"external_physical_validation":False,
                     "extent":"parameter_range","matrix_complete":True,"independent_checks_passed":True,
                     "qualification_origin":"explicitly preserved historical registered protocol; not a new Core 13+2 study",
                     "recipe":canonical_manifest["recipe"],"gate":reference(gate_path),"scores":reference(scores_path),
                     "panel_count":len(scores["panels"]),"canonical_manifest":reference(canonical_path)}
    atomic_json(qualification_path,qualification)
    cases=[]
    for row in canonical_manifest["cases"]:
        audit=row["independent_audit"]
        source=row["source_evidence"]["audit"]
        if digest(lab/source["path"]) != source["sha256"]:
            raise ValueError("historical case audit changed")
        if not audit.get("full_scan") or not audit.get("structural_pass") or not row["qualification_axes"]["T1_registered_numerical"]:
            raise ValueError("case lacks inherited complete structural/numerical evidence")
        path=root/"evidence/f3-cases"/(row["case_id"]+".json")
        atomic_json(path,{"schema":"core.case_audit.v1","case_id":row["case_id"],"hard_integrity_pass":True,
                          "source":"inherited full scan, bound by unchanged canonical manifest and source audit",
                          "source_audit":source,"canonical_manifest":reference(canonical_path),
                          "hdf5_sha256":row["file"]["sha256"],"original_full_scan":audit})
        cases.append({"case_id":row["case_id"],"physical_case_id":row["physical_case_id"],
                      "lineage_group_id":row["lineage_group_id"],"split":row["split"],
                      "hard_integrity_pass":True,"T1_numerical":True,"audit":reference(path)})
    registry_path=root/"registry.json"
    registry=json.loads(registry_path.read_text()) if registry_path.exists() else {"schema":"core.registry.v1","scopes":[],"training_runs":[],"evaluations":[]}
    new_scope={"scope_id":gate["recipe_id"],"family":"F3","qualification":reference(qualification_path),"cases":cases}
    existing=next((s for s in registry["scopes"] if s["scope_id"]==new_scope["scope_id"]),None)
    if existing is None:
        registry["scopes"].append(new_scope)
    elif existing["qualification"]!=new_scope["qualification"]:
        raise ValueError("registered F3 scope changed; explicit migration required")
    atomic_json(registry_path,registry)
    return {"imported_cases":len(cases),"inherited_t1_family":"F3","macro_t2_qualified":False,"registry":str(registry_path)}


def completion(registry, data_root):
    issues = []
    studies = []
    if not isinstance(registry, dict):
        registry = {}
        issues.append({"registry": "root", "reason": "registry must be a JSON object"})

    def entries(name):
        value = registry.get(name, [])
        if value is None:
            return []
        if not isinstance(value, list):
            issues.append({"registry": name, "reason": f"{name} must be a list"})
            return []
        return value

    expected_run_ids = tuple(expected_runs())
    expected_run_set = set(expected_run_ids)
    expected_run_ids_are_complete = (
        len(expected_run_ids) == len(expected_run_set)
        and all(isinstance(run_id, str) and run_id for run_id in expected_run_ids)
    )
    if not expected_run_ids_are_complete:
        issues.append({"registry": "training_runs", "reason": "expected training run denominator is invalid"})

    for study in entries('scope_studies'):
        if not isinstance(study, dict):
            issues.append({'scope_study': None, 'reason': 'scope study entry is not an object'})
            continue
        try:
            receipt = load_evidence(study['qualification'], data_root)
            _reject_nonformal_or_nonroot(receipt, "scope study")
            if (receipt.get('schema') != 'core.qualification.v1'
                    or receipt.get('scope_id') != study['scope_id']
                    or receipt.get('family') != study['family']):
                raise ValueError('scope study identity/schema mismatch')
            studies.append({'scope_id': study['scope_id'], 'family': study['family'],
                            'matrix_complete': receipt.get('matrix_complete') is True,
                            'T1_numerical': receipt.get('T1_numerical') is True,
                            'status': 'incomplete' if receipt.get('matrix_complete') is not True else
                                      'qualified' if receipt.get('T1_numerical') is True else 'completed_negative_result'})
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({'scope_study': study.get('scope_id'), 'reason': str(exc)})
    families = {}
    material = {}
    eval_ids = set()
    material_eval_ids = set()
    registered_case_owners = {}
    registered_physical_case_owners = {}
    for scope in entries("scopes"):
        if not isinstance(scope, dict):
            issues.append({"scope_id": None, "reason": "scope entry is not an object"})
            continue
        sid = scope.get("scope_id", "unknown")
        try:
            if not isinstance(sid, str) or not sid:
                raise ValueError("scope id is missing")
            family = scope.get("family")
            if not isinstance(family, str) or not family:
                raise ValueError("scope family is missing")
            receipt = load_evidence(scope["qualification"], data_root)
            _reject_nonformal_or_nonroot(receipt, "qualification")
            if (receipt.get("schema") != "core.qualification.v1"
                    or receipt.get("scope_id") != sid
                    or receipt.get("family") != family):
                raise ValueError("qualification schema/scope mismatch")
            if receipt.get("T1_numerical") is not True or receipt.get("extent") != "parameter_range":
                raise ValueError("T1 range not qualified")
            if (receipt.get("matrix_complete") is not True
                    or receipt.get("independent_checks_passed") is not True):
                raise ValueError("qualification matrix/independent checks incomplete")
            cases = scope.get("cases", [])
            if not isinstance(cases, list):
                raise ValueError("scope cases must be a list")
            accepted = [c for c in cases
                        if isinstance(c, dict)
                        and c.get("hard_integrity_pass") is True
                        and c.get("T1_numerical") is True]
            physical_ids = {
                c.get("physical_case_id") for c in accepted
                if isinstance(c.get("physical_case_id"), str) and c.get("physical_case_id")
            }
            ids = {
                c.get("case_id") for c in accepted
                if isinstance(c.get("case_id"), str) and c.get("case_id")
            }
            if (len(physical_ids) < 32 or len(ids) < 32
                    or len(ids) != len(accepted)
                    or len(physical_ids) != len(accepted)):
                raise ValueError("fewer than 32 distinct accepted physical cases")
            for c in accepted:
                if (not isinstance(c.get("physical_case_id"), str)
                        or not c.get("physical_case_id")
                        or not isinstance(c.get("case_id"), str)
                        or not c.get("case_id")
                        or not isinstance(c.get("split"), str)):
                    raise ValueError("accepted case identity/split is incomplete")
                case_id = c["case_id"]
                physical_case_id = c["physical_case_id"]
                previous_scope = registered_case_owners.get(case_id)
                if previous_scope is not None:
                    raise ValueError(
                        f"case id is registered in multiple scopes: {case_id}"
                    )
                previous_physical_scope = registered_physical_case_owners.get(physical_case_id)
                if previous_physical_scope is not None:
                    raise ValueError(
                        f"physical case id is registered in multiple scopes: {physical_case_id}"
                    )
                registered_case_owners[case_id] = sid
                registered_physical_case_owners[physical_case_id] = sid
                audit = load_evidence(c["audit"], data_root)
                _reject_nonformal_or_nonroot(audit, "case audit")
                if (audit.get("schema") != "core.case_audit.v1"
                        or audit.get("hard_integrity_pass") is not True
                        or audit.get("case_id") != c["case_id"]):
                    raise ValueError("case hard audit mismatch")
            families.setdefault(family, set()).update(ids)
            evaluation = {c["case_id"] for c in accepted if c["split"] in ("validation", "test", "id_test", "ood_test")}
            if len(evaluation) < 16:
                raise ValueError("fewer than 16 validation/evaluation cases")
            eval_ids.update(evaluation)
            if scope.get("material_qualification"):
                m = load_evidence(scope["material_qualification"], data_root)
                _reject_nonformal_or_nonroot(m, "material qualification")
                if (m.get("schema") != "core.material_qualification.v1"
                        or m.get("T2_macro") is not True or m.get("scope_id") != sid):
                    raise ValueError("material range unqualified")
                if (m.get("matrix_complete") is not True
                        or m.get("extent") != "parameter_range"):
                    raise ValueError("material matrix/range incomplete")
                formal_receipt = m.get("formal_acceptance_receipt")
                if not isinstance(formal_receipt, dict):
                    raise ValueError("material formal acceptance receipt is missing")
                if (formal_receipt.get("status") not in ("accepted", "complete", "passed", "qualified")
                        or formal_receipt.get("T2_macro") is not True):
                    raise ValueError("material formal acceptance receipt is not accepted")
                _reject_nonformal_or_nonroot(formal_receipt, "material formal acceptance receipt")
                _require_passed_root_review(
                    formal_receipt.get("root_review") or m.get("root_review"),
                    data_root, "material formal acceptance receipt")
                for c in accepted:
                    sidecar = load_evidence(c["material_audit"], data_root)
                    _reject_nonformal_or_nonroot(sidecar, "material case audit")
                    if (sidecar.get("schema") not in ("core.material.case_audit.v1", "core.material.sidecar.v1")
                            or sidecar.get("case_id") != c["case_id"]
                            or sidecar.get("macro_qualified") is not True):
                        raise ValueError("material sidecar not qualified")
                    if sidecar.get("window_complete") is not True:
                        raise ValueError("material sidecar window incomplete")
                    validate_source_coverage(sidecar.get("source_coverage"),
                                             m.get("required_source_ids"),
                                             m.get("maximum_source_unknown_fraction", .01))
                material.setdefault(family, set()).update(ids)
                material_eval_ids.update(evaluation)
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({"scope_id": sid, "reason": str(exc)})
    runs = {}
    seen_training_run_ids = set()
    for run in entries("training_runs"):
        if not isinstance(run, dict):
            issues.append({"run_id": None, "reason": "training run entry is not an object"})
            continue
        try:
            run_id = run["run_id"]
            if not isinstance(run_id, str) or run_id not in expected_run_set:
                raise ValueError("training run is not in expected formal run denominator")
            if run_id in seen_training_run_ids:
                raise ValueError("duplicate formal training run entry")
            seen_training_run_ids.add(run_id)
            receipt = load_evidence(run["receipt"], data_root)
            if not isinstance(receipt, dict):
                raise ValueError("training receipt is not a JSON object")
            if receipt.get("schema") != "core.training.v1" or receipt.get("run_id") != run_id:
                raise ValueError("training receipt identity/schema mismatch")
            if (receipt.get("completed_updates") != FORMAL_UPDATES
                    or receipt.get("checkpoint_verified") is not True):
                raise ValueError("formal training/checkpoint incomplete")
            config = receipt.get("config", {})
            if not isinstance(config, dict):
                raise ValueError("formal training config is missing")
            if (config.get("manifest_formal_release") is not True
                    or config.get("validation_formal_eligible") is not True
                    or config.get("evaluate_milestones") is not True):
                raise ValueError("training is not bound to the formal data and validation protocol")
            counts = config.get("validation_family_counts", {})
            if (not isinstance(counts, dict) or len(counts) < 3
                    or (families and set(counts) != set(families))
                    or any(not isinstance(n, int) or isinstance(n, bool) or n < 4
                           for n in counts.values())):
                raise ValueError(
                    "formal training lacks exactly the registered families with four validation cases each"
                )
            checkpoint = receipt.get("checkpoint", {})
            if (not isinstance(checkpoint, dict)
                    or checkpoint.get("schema") != "core.checkpoint.v1"
                    or checkpoint.get("update") != FORMAL_UPDATES):
                raise ValueError("formal terminal checkpoint identity/update mismatch")
            checkpoint_path = _rooted_path(checkpoint["path"], data_root, "checkpoint")
            if digest(checkpoint_path) != checkpoint.get("sha256"):
                raise ValueError("formal terminal checkpoint hash mismatch")
            if receipt.get("evidence_status") != "complete":
                raise ValueError("formal training evidence receipt is missing or incomplete")
            evidence = receipt.get("evidence")
            if (not isinstance(evidence, dict)
                    or evidence.get("schema") != "core.training.evidence.v1"
                    or evidence.get("status") != "complete"):
                raise ValueError("formal training evidence receipt is missing or incomplete")
            _reject_nonformal_or_nonroot(receipt, "training receipt")
            runs[run_id] = receipt
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({"run_id": run.get("run_id"), "reason": str(exc)})
    received = {"T1": set(), "T2_macro": set()}
    seen_evaluations = {"T1": set(), "T2_macro": set()}
    for entry in entries("evaluations"):
        if not isinstance(entry, dict):
            issues.append({"evaluation": entry, "reason": "evaluation entry is not an object"})
            continue
        try:
            receipt = load_evidence(entry["receipt"], data_root)
            _reject_nonformal_or_nonroot(receipt, "evaluation receipt")
            axis = receipt["axis"]
            if axis not in received:
                raise ValueError("evaluation axis is not registered")
            run_id, case_id = receipt["run_id"], receipt["case_id"]
            if (not isinstance(run_id, str) or not isinstance(case_id, str)
                    or not run_id or not case_id):
                raise ValueError("evaluation identity is incomplete")
            _validate_evaluation_receipt(
                receipt, axis=axis, run_id=run_id, case_id=case_id)
            key = (run_id, case_id)
            if key in seen_evaluations[axis]:
                raise ValueError("duplicate evaluation receipt")
            seen_evaluations[axis].add(key)
            received[axis].add(key)
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({"evaluation": entry, "reason": str(exc)})
    required_t1 = {(run, case) for run in expected_run_set for case in eval_ids}
    required_t2 = {(run, case) for run in expected_run_set for case in material_eval_ids}
    registered_received = {
        "T1": received["T1"] & required_t1,
        "T2_macro": received["T2_macro"] & required_t2,
    }
    unregistered_received = {
        "T1": received["T1"] - required_t1,
        "T2_macro": received["T2_macro"] - required_t2,
    }
    for axis, keys in unregistered_received.items():
        for run_id, case_id in sorted(keys):
            issues.append({
                "evaluation": {"axis": axis, "run_id": run_id, "case_id": case_id},
                "reason": "evaluation is outside the registered completion denominator",
            })
    checks = {
        "three_t1_families": len(families) >= 3,
        "two_macro_t2_families": len(material) >= 2,
        "nine_formal_training_runs": (
            expected_run_ids_are_complete
            and len(runs) == len(expected_run_set)
            and set(runs) == expected_run_set
        ),
        "t1_denominator_complete": (
            len(required_t1) >= MINIMUM_T1_CASE_RUNS
            and required_t1 <= registered_received["T1"]
        ),
        "material_denominator_complete": (
            len(required_t2) >= MINIMUM_MATERIAL_CASE_RUNS
            and required_t2 <= registered_received["T2_macro"]
        ),
        "independent_reproduction": False,
        "causal_lineage_contracts": False,
        "evidence_valid": not issues,
    }
    for name, schema in (("independent_reproduction", "core.reproduction.v1"),
                         ("causal_lineage_contracts", "core.contract_audit.v1")):
        try:
            reference = _contract_evidence_reference(name, registry, data_root)
            if reference is None:
                continue
            receipt = load_evidence(reference, data_root)
            checks[name] = receipt.get("schema") == schema and receipt.get("passed") is True
            if name == "independent_reproduction":
                checks[name] = _independent_reproduction_passes(receipt, data_root)
        except (KeyError, ValueError, OSError, TypeError):
            pass
    # Keep two distinct counts: the registered-material denominator (which is
    # empty until two T2 families are accepted) and the Core target denominator.
    # Only the intersection with ``required_t2`` is observed product evidence;
    # arbitrary receipts must never shrink the target denominator.
    registered_t1_missing = len(required_t1 - registered_received["T1"])
    registered_material_missing = len(required_t2 - registered_received["T2_macro"])
    target_t1_missing = max(0, MINIMUM_T1_CASE_RUNS - len(registered_received["T1"]))
    target_material_missing = max(0, MINIMUM_MATERIAL_CASE_RUNS - len(registered_received["T2_macro"]))
    completion_gaps = []
    if not checks["three_t1_families"]:
        completion_gaps.append({
            "gate": "three_t1_families",
            "observed": sorted(families),
            "required_minimum": 3,
            "reason": "Core requires three distinct qualified T1 mechanism families",
        })
    if not checks["two_macro_t2_families"]:
        completion_gaps.append({
            "gate": "two_macro_t2_families",
            "observed": sorted(material),
            "required_minimum": 2,
            "reason": "Core requires two distinct families with accepted macro T2 material paths",
        })
    if not checks["nine_formal_training_runs"]:
        completion_gaps.append({
            "gate": "nine_formal_training_runs",
            "observed_count": len(runs),
            "required_count": len(expected_run_set),
            "missing_run_ids": sorted(expected_run_set - set(runs)),
            "reason": "all registered model/seed runs must have formal terminal evidence",
        })
    if not checks["t1_denominator_complete"]:
        completion_gaps.append({
            "gate": "t1_denominator_complete",
            "observed_case_runs": len(registered_received["T1"]),
            "required_case_runs": MINIMUM_T1_CASE_RUNS,
            "missing_case_runs": target_t1_missing,
            "reason": "the fixed T1 evaluation denominator is incomplete",
        })
    if not checks["material_denominator_complete"]:
        completion_gaps.append({
            "gate": "material_denominator_complete",
            "observed_case_runs": len(registered_received["T2_macro"]),
            "required_case_runs": MINIMUM_MATERIAL_CASE_RUNS,
            "missing_case_runs": target_material_missing,
            "reason": "the fixed model-material evaluation denominator is incomplete",
        })
    if not checks["independent_reproduction"]:
        completion_gaps.append({
            "gate": "independent_reproduction",
            "reason": "requires a passed non-diagnostic full-product receipt proving reader, prediction, and scoring on another host and a distinct data root, plus passed root review",
        })
    if not checks["causal_lineage_contracts"]:
        completion_gaps.append({
            "gate": "causal_lineage_contracts",
            "reason": "the required causal/data-lineage contract audit is not registered as passed",
        })
    if not checks["evidence_valid"]:
        completion_gaps.append({
            "gate": "evidence_valid",
            "invalid_evidence_issue_count": len(issues),
            "reason": "one or more registered evidence records fail structural or hash validation",
        })
    return {"schema": "core.completion.v1", "can_finalize": all(checks.values()), "checks": checks,
            "scope_studies": studies,
            "t1_families": sorted(families), "macro_t2_families": sorted(material),
            "training_runs": sorted(runs), "missing_t1_case_runs": registered_t1_missing,
            "missing_material_case_runs": target_material_missing,
            "missing_registered_material_case_runs": registered_material_missing,
            "missing_registered_t1_case_runs": registered_t1_missing,
            "missing_target_t1_case_runs": target_t1_missing,
            "missing_target_material_case_runs": target_material_missing,
            "unregistered_t1_case_runs": max(0, MINIMUM_T1_CASE_RUNS - len(required_t1)),
            "unregistered_material_case_runs": max(0, MINIMUM_MATERIAL_CASE_RUNS - len(required_t2)),
            "unregistered_t1_evidence_case_runs": len(unregistered_received["T1"]),
            "unregistered_material_evidence_case_runs": len(unregistered_received["T2_macro"]),
            "required_t1_case_runs": len(required_t1),
            "required_material_case_runs": len(required_t2),
            "observed_t1_case_runs": len(registered_received["T1"]),
            "observed_material_case_runs": len(registered_received["T2_macro"]),
            "expected_training_runs": sorted(expected_run_set),
            "missing_training_runs": sorted(expected_run_set - set(runs)),
            "minimum_t1_case_runs": MINIMUM_T1_CASE_RUNS,
            "minimum_material_case_runs": MINIMUM_MATERIAL_CASE_RUNS,
            "issues": issues,
            "completion_gaps": completion_gaps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("adopt")
    sub.add_parser("import-f3")
    p = sub.add_parser("status")
    p.add_argument("--registry", type=Path)
    p.add_argument("--write-snapshot", action="store_true",
                   help="explicitly update the hash-bound completion snapshot")
    args = parser.parse_args()
    if args.command == "adopt":
        result = adopt(args.lab_root, args.root)
    elif args.command == "import-f3":
        result = import_registered_f3(args.lab_root,args.root)
    else:
        path = args.registry or args.root / "registry.json"
        registry = json.loads(path.read_text()) if path.exists() else {}
        result = completion(registry, args.lab_root)
        if args.write_snapshot:
            atomic_json(args.root / "completion.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
