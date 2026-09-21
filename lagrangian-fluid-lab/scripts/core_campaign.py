#!/usr/bin/env python3
"""Adopt the Core execution contract and compute evidence-based completion.

Legacy campaign bytes are referenced, never rewritten or interpreted as fresh
budget. A completed job is not a qualified scope or a successful model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
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


def expected_runs():
    return [f"{model}-seed{seed}" for model in MODELS for seed in SEEDS]


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
                    "training_runs": expected_runs(), "updates_per_run": 32000,
                    "minimum_t1_case_runs": 432, "minimum_material_case_runs": 288,
                    "evaluation_missing": 0, "different_host_reproduction_required": True},
        "qualification_axes": ["T1_numerical", "T2_macro", "T2_path", "external_physical_validation"],
        "family_priority": ["F3", "F4", "F1", "F2"],
        "material_family_priority": ["F3", "F4", "F1", "F2"],
        "retry_policy": {"hypotheses_per_failure_mechanism": 2,
                         "canaries_per_hypothesis": 1, "repaired_infrastructure_retries": 1,
                         "no_threshold_relaxation_after_results": True},
        "training": {"model_configs": MODELS, "seeds": SEEDS, "updates": 32000,
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
    if not isinstance(reference, dict) or not {"path", "sha256"} <= set(reference):
        raise ValueError("a hashed evidence reference is required")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("evidence path must be portable and within data_root")
    path = Path(data_root) / relative
    if digest(path) != reference["sha256"]:
        raise ValueError("evidence hash mismatch: " + str(relative))
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
    catalog_path = Path(data_root) / "campaigns/core-v1/contract-evidence.json"
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
    for study in registry.get('scope_studies', []):
        try:
            receipt = load_evidence(study['qualification'], data_root)
            if (receipt.get('schema') != 'core.qualification.v1'
                    or receipt.get('scope_id') != study['scope_id']
                    or receipt.get('family') != study['family']):
                raise ValueError('scope study identity/schema mismatch')
            studies.append({'scope_id': study['scope_id'], 'family': study['family'],
                            'matrix_complete': receipt.get('matrix_complete') is True,
                            'T1_numerical': receipt.get('T1_numerical') is True,
                            'status': 'incomplete' if not receipt.get('matrix_complete') else
                                      'qualified' if receipt.get('T1_numerical') else 'completed_negative_result'})
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({'scope_study': study.get('scope_id'), 'reason': str(exc)})
    families = {}
    material = {}
    eval_ids = set()
    material_eval_ids = set()
    for scope in registry.get("scopes", []):
        sid = scope.get("scope_id", "unknown")
        try:
            receipt = load_evidence(scope["qualification"], data_root)
            if receipt.get("schema") != "core.qualification.v1" or receipt.get("scope_id") != sid:
                raise ValueError("qualification schema/scope mismatch")
            if not receipt.get("T1_numerical") or receipt.get("extent") != "parameter_range":
                raise ValueError("T1 range not qualified")
            if not receipt.get("matrix_complete") or not receipt.get("independent_checks_passed"):
                raise ValueError("qualification matrix/independent checks incomplete")
            cases = scope.get("cases", [])
            accepted = [c for c in cases if c.get("hard_integrity_pass") and c.get("T1_numerical")]
            if len({c["physical_case_id"] for c in accepted}) < 32:
                raise ValueError("fewer than 32 distinct accepted physical cases")
            ids = {c["case_id"] for c in accepted}
            for c in accepted:
                audit = load_evidence(c["audit"], data_root)
                if not audit.get("hard_integrity_pass") or audit.get("case_id") != c["case_id"]:
                    raise ValueError("case hard audit mismatch")
            family = scope["family"]
            families.setdefault(family, set()).update(ids)
            evaluation = {c["case_id"] for c in accepted if c["split"] in ("validation", "test", "id_test", "ood_test")}
            if len(evaluation) < 16:
                raise ValueError("fewer than 16 validation/evaluation cases")
            eval_ids.update(evaluation)
            if scope.get("material_qualification"):
                m = load_evidence(scope["material_qualification"], data_root)
                if m.get("schema") != "core.material_qualification.v1" or not m.get("T2_macro") or m.get("scope_id") != sid:
                    raise ValueError("material range unqualified")
                if not m.get("matrix_complete") or m.get("extent") != "parameter_range":
                    raise ValueError("material matrix/range incomplete")
                for c in accepted:
                    sidecar = load_evidence(c["material_audit"], data_root)
                    if sidecar.get("case_id") != c["case_id"] or not sidecar.get("macro_qualified"):
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
    for run in registry.get("training_runs", []):
        try:
            receipt = load_evidence(run["receipt"], data_root)
            if receipt.get("schema") != "core.training.v1" or receipt.get("run_id") != run["run_id"]:
                raise ValueError("training receipt identity/schema mismatch")
            if receipt.get("completed_updates") != 32000 or not receipt.get("checkpoint_verified"):
                raise ValueError("formal training/checkpoint incomplete")
            config = receipt.get("config", {})
            if (config.get("manifest_formal_release") is not True
                    or config.get("validation_formal_eligible") is not True
                    or config.get("evaluate_milestones") is not True):
                raise ValueError("training is not bound to the formal data and validation protocol")
            counts = config.get("validation_family_counts", {})
            if (not isinstance(counts, dict) or len(counts) < 3
                    or any(not isinstance(n, int) or isinstance(n, bool) or n < 4
                           for n in counts.values())):
                raise ValueError("formal training lacks three families with four validation cases each")
            checkpoint = receipt.get("checkpoint", {})
            if checkpoint.get("schema") != "core.checkpoint.v1" or checkpoint.get("update") != 32000:
                raise ValueError("formal terminal checkpoint identity/update mismatch")
            checkpoint_path = Path(data_root) / checkpoint["path"]
            if digest(checkpoint_path) != checkpoint.get("sha256"):
                raise ValueError("formal terminal checkpoint hash mismatch")
            runs[run["run_id"]] = receipt
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({"run_id": run.get("run_id"), "reason": str(exc)})
    received = {"T1": set(), "T2_macro": set()}
    for entry in registry.get("evaluations", []):
        try:
            receipt = load_evidence(entry["receipt"], data_root)
            if receipt.get("schema") != "core.evaluation.v1":
                raise ValueError("evaluation receipt schema mismatch")
            if receipt.get("execution_status") not in ("complete", "model_failed"):
                raise ValueError("evaluation missing or infrastructure failure")
            key = (receipt["run_id"], receipt["case_id"])
            received[receipt["axis"]].add(key)
        except (KeyError, ValueError, OSError, TypeError) as exc:
            issues.append({"evaluation": entry, "reason": str(exc)})
    required_t1 = {(run, case) for run in expected_runs() for case in eval_ids}
    required_t2 = {(run, case) for run in expected_runs() for case in material_eval_ids}
    checks = {
        "three_t1_families": len(families) >= 3,
        "two_macro_t2_families": len(material) >= 2,
        "nine_formal_training_runs": set(expected_runs()) <= set(runs),
        "t1_denominator_complete": len(required_t1) >= 432 and required_t1 <= received["T1"],
        "material_denominator_complete": len(required_t2) >= 288 and required_t2 <= received["T2_macro"],
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
                checks[name] = checks[name] and receipt.get("source_host") != receipt.get("reproduction_host") and bool(receipt.get("source_host"))
        except (KeyError, ValueError, OSError, TypeError):
            pass
    # Keep two distinct counts: the registered-material denominator (which is
    # empty until two T2 families are accepted) and the Core target denominator.
    # Reporting only the former as ``missing_material_case_runs`` made an
    # unstarted 288-run material evaluation look complete.
    registered_material_missing = len(required_t2 - received["T2_macro"])
    target_material_missing = max(0, 288 - len(received["T2_macro"]))
    return {"schema": "core.completion.v1", "can_finalize": all(checks.values()), "checks": checks,
            "scope_studies": studies,
            "t1_families": sorted(families), "macro_t2_families": sorted(material),
            "training_runs": sorted(runs), "missing_t1_case_runs": len(required_t1 - received["T1"]),
            "missing_material_case_runs": target_material_missing,
            "missing_registered_material_case_runs": registered_material_missing,
            "unregistered_t1_case_runs": max(0, 432 - len(required_t1)),
            "unregistered_material_case_runs": max(0, 288 - len(required_t2)),
            "minimum_t1_case_runs": 432, "minimum_material_case_runs": 288,
            "issues": issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("adopt")
    sub.add_parser("import-f3")
    p = sub.add_parser("status")
    p.add_argument("--registry", type=Path)
    args = parser.parse_args()
    if args.command == "adopt":
        result = adopt(args.lab_root, args.root)
    elif args.command == "import-f3":
        result = import_registered_f3(args.lab_root,args.root)
    else:
        path = args.registry or args.root / "registry.json"
        registry = json.loads(path.read_text()) if path.exists() else {}
        result = completion(registry, args.lab_root)
        atomic_json(args.root / "completion.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
