#!/usr/bin/env python3
"""Build the F2 fresh102 GenCase evidence and QA/native handoff.

The Root353 GenCase receipts already exist outside this worktree. This builder
reads only JSON, generated XML, and source metadata. It never opens or hashes
motion ``.dat``, BI4, H5, CSV, VTK, or XMF payloads. The motion asset digest
used in disabled requests is copied from the actual prepared-input-report
producer record; the Root-owned QA/solver job performs the eventual runtime
digest/read when enabled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
BASE = Path("/home/jade/Projects/DualSPHysics").resolve()
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
HERE = Path(__file__).resolve().parent
FRESH100 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1"
MANIFEST100 = FRESH100 / "F2_STAGE1_FRESH100_MOTION_ENTRY_MANIFEST.json"
ROOT353 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_fresh100_motion_GenCase_strict_guard_rebind_353"
LAB = INTEGRATION / "lagrangian-fluid-lab"
PYTHON = LAB / ".venv/bin/python"
FRESH100_AUDIT = FRESH100 / "workers/f2_prepared_report_contract_audit.py"
FRESH100_QA_ADAPTER = FRESH100 / "workers/f2_stage1_prepared_report_qa_worker.py"
FRESH100_QA = FRESH100 / "workers/f2_stage1_initial_qa_worker.py"
FRESH100_BUILDER = FRESH100 / "build_fresh100.py"
VALIDATOR = HERE / "workers/fresh102_source_contract_validator.py"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
ROOT142 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT142LAUNCH = ROOT142.parent / "launch.py"
ROOT230D = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230 = ROOT230D / "root_native_home_floor_inventory_policy.py"
ROOT230LAUNCH = ROOT230D / "launch.py"
ROOT230CONTRACT = ROOT230D / "source-policy-contract.json"
GPU_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SOLVER = BASE / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
PARTVTK = BASE / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SCOPE = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
FRESH_ID = "fresh102"
STRICT_GUARD_DIGEST = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
ROOT142_PROFILE = "root_home_floor_no_legacy_dataset_walk_v1"
ROOT230_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"

RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
COUNT_KEYS = ("fixed", "moving", "floating", "fluid")
RESOURCE_CONTRACT = {
    "conversion_concurrency": 2,
    "cpu_threads": 2,
    "home_min_free_bytes": 536870912000,
    "nvme_free_space_floor_bytes": 107374182400,
    "nvme_staging_peak_limit_bytes": 25769803776,
    "nvme_staging_root": "/tmp/ds02-nvme-conversion",
    "max_wall_seconds": 3600,
}


def sha(path: Path) -> str:
    """Hash only JSON/XML/Python/text metadata in this source preparation."""
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload hash refused: {path}")
    if path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"non-static input refused: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def recorded_payload(path: Path, expected: Any, label: str) -> dict[str, Any]:
    """Bind a producer-recorded raw payload digest without reading the payload."""
    path = Path(path).resolve()
    if path.suffix.lower() not in RAW_SUFFIXES:
        raise ValueError(f"{label} is not an explicitly recorded raw payload: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing producer payload: {path}")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"{label} does not carry a producer SHA-256")
    # stat is provenance/liveness only. No bytes are opened and no digest is
    # recomputed in this source-only builder.
    return {"path": str(path), "sha256": expected, "bytes": path.stat().st_size, "read_or_hashed_here": False}


def bind(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "exists": True}


def dump(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def static_files(*paths: Path) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if str(path) in seen:
            continue
        seen.add(str(path))
        sha(path)
        result.append(path)
    return result


def recorded_digest(template: Mapping[str, Any], path: Path) -> str:
    """Use an already registered digest for a binary/raw worker input.

    The old fresh100 request is the producer record for the official binary
    and motion asset. This function never opens either file.
    """
    key = str(Path(path).resolve())
    digest = (template.get("input_sha256") or {}).get(key)
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"fresh100 has no recorded digest for {key}")
    return digest


def strict_guard(*, native: bool) -> dict[str, Any]:
    root_policy = ROOT230 if native else ROOT142
    return {
        "strict_guard_digest": STRICT_GUARD_DIGEST,
        "source_only": True,
        "worktree_root": str(INFRA),
        "input_closure": "set(input_files)==set(input_sha256); JSON/XML/Python metadata plus producer-recorded motion payload; future scientific outputs remain null",
        "runtime_v2": {"path": str(RUNTIME), "sha256": sha(RUNTIME)},
        "strict_dispatch": {"path": str(STRICT), "sha256": sha(STRICT)},
        "root142_inventory_policy": {"path": str(ROOT142), "sha256": sha(ROOT142)},
        "root230_inventory_policy": {"path": str(ROOT230), "sha256": sha(ROOT230)},
        "root_inventory_policy": {"path": str(root_policy), "sha256": sha(root_policy)},
        "resource_window": {"path": str(RESOURCE), "sha256": sha(RESOURCE)},
    }


def load_actual_case(row: Mapping[str, Any]) -> dict[str, Any]:
    cid = str(row["case_id"])
    root_req_path = ROOT353 / f"{cid}-gencase-request.json"
    root_req = read_json(root_req_path)
    raw_root = Path(str(root_req["raw_output_root"])).resolve()
    attempt = str(root_req["attempt_id"])
    attempt_root = raw_root / attempt
    receipt_path = attempt_root / "execution-receipt.json"
    report_path = attempt_root / "prepared" / "prepared-input-report.json"
    xml_path = attempt_root / "prepared" / f"{cid}.xml"
    receipt = read_json(receipt_path)
    report = read_json(report_path)
    owner_path = Path(row["owner"]["path"]).resolve()
    metadata_path = Path(row["metadata"]["path"]).resolve()
    binding_path = Path(row["binding"]["path"]).resolve()
    owner = read_json(owner_path)
    metadata = read_json(metadata_path)
    binding = read_json(binding_path)
    qa_template = read_json(Path(row["requests"]["initial-qa"]["path"]).resolve())
    native_template = read_json(Path(row["requests"]["native"]["path"]).resolve())

    if root_req.get("case_id") != cid or not str(root_req.get("status", "")).startswith("root_"):
        raise ValueError(f"Root353 request is not the recorded enabled request: {cid}")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"Root353 receipt is not completed/0: {cid}")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError(f"Root353 GenCase is not actual 3-D: {cid}")
    if receipt.get("request", {}).get("attempt_id") not in {None, attempt}:
        raise ValueError(f"receipt/request attempt mismatch: {cid}")
    if report.get("schema") != "ds02.root.actual-native-source-preflight.v1" or report.get("case_id") != cid:
        raise ValueError(f"prepared report identity mismatch: {cid}")
    counts = report.get("generated_xml_particle_counts")
    if not isinstance(counts, dict) or any(not isinstance(counts.get(key), int) or counts[key] < 0 for key in COUNT_KEYS):
        raise ValueError(f"prepared report counts missing: {cid}")
    total = report.get("actual_total_particles")
    if not isinstance(total, int) or total <= 0 or sum(counts[key] for key in COUNT_KEYS) != total:
        raise ValueError(f"prepared report count closure failed: {cid}")
    if not xml_path.is_file():
        raise FileNotFoundError(xml_path)
    xml_hash = sha(xml_path)
    if report.get("xml_sha256") != xml_hash:
        raise ValueError(f"prepared XML digest does not close report: {cid}")
    try:
        if ET.parse(xml_path).getroot().tag != "case":
            raise ValueError(f"prepared XML root is not case: {cid}")
    except ET.ParseError as exc:
        raise ValueError(f"prepared XML parse failed: {cid}") from exc
    assets = report.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError(f"prepared report has no producer assets: {cid}")
    motion_asset = next((item for item in assets if isinstance(item, dict) and item.get("role") == "official GenCase mvrotfile control asset"), None)
    if not isinstance(motion_asset, dict):
        raise ValueError(f"prepared report has no official motion asset: {cid}")
    motion_path = Path(str(motion_asset.get("copied_to"))).resolve()
    motion_sha = motion_asset.get("verified_post_gencase_sha256") or motion_asset.get("sha256")
    motion_binding = recorded_payload(motion_path, motion_sha, f"{cid} motion asset")
    if motion_asset.get("sha256") != motion_asset.get("verified_post_gencase_sha256"):
        raise ValueError(f"producer motion digest was not restored/verified: {cid}")

    return {
        "row": dict(row), "case_id": cid, "root_request_path": root_req_path,
        "root_request": root_req, "receipt_path": receipt_path, "receipt": receipt,
        "report_path": report_path, "report": report, "xml_path": xml_path,
        "xml_sha256": xml_hash, "attempt_root": attempt_root, "gencase_attempt": attempt,
        "owner_path": owner_path, "owner": owner, "metadata_path": metadata_path,
        "metadata": metadata, "binding_path": binding_path, "binding": binding,
        "qa_template": qa_template, "native_template": native_template,
        "motion_binding": motion_binding, "counts": counts, "total": total,
        "source_plan_hash": owner.get("source_plan_physical_condition_sha256", row.get("source_plan_physical_condition_sha256")),
        "physical_hash": owner.get("physical_condition_sha256", row.get("physical_condition_sha256")),
        "legacy_hash": (owner.get("typed_scope_contract") or {}).get("prospective_legacy_scope_sha256"),
    }


def make_sidecar(case: Mapping[str, Any]) -> Path:
    cid = str(case["case_id"])
    path = HERE / "evidence/gencase-runtime" / f"{cid}.gencase-runtime-evidence.json"
    receipt: Mapping[str, Any] = case["receipt"]
    report: Mapping[str, Any] = case["report"]
    raw_counts = {key: receipt.get(key) for key in ("fixed_particles", "moving_particles", "floating_particles", "fluid_particles", "total_particles")}
    missing_partition = [key for key in ("fixed_particles", "moving_particles", "floating_particles") if not isinstance(receipt.get(key), int)]
    checks = {
        "root353_receipt_completed_zero": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        "root353_solver_dimension_three": receipt.get("solver_dimension_from_gencase") == 3,
        "prepared_report_schema_and_case": report.get("schema") == "ds02.root.actual-native-source-preflight.v1" and report.get("case_id") == cid,
        "prepared_report_counts_close": sum(case["counts"].values()) == case["total"],
        "prepared_xml_sha_closes_report": report.get("xml_sha256") == case["xml_sha256"],
        "prepared_report_has_no_approval": report.get("q_n") == "not_granted" and report.get("production_approval") == "none",
        "prepared_report_has_no_case_increment": report.get("independent_case_count_increment") == 0,
        "raw_receipt_partition_not_used": True,
    }
    value = {
        "schema": "ds02.f2.stage1.fresh102.gencase-runtime-evidence.v1",
        "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE,
        "case_id": cid, "physical_case_id": case["owner"].get("physical_case_id"),
        "source_plan_physical_condition_sha256": case["source_plan_hash"],
        "physical_condition_sha256": case["physical_hash"],
        "prospective_legacy_scope_sha256": case["legacy_hash"],
        "canonical_physical_binding_sha256": case["owner"].get("canonical_physical_binding_sha256"),
        "producer_scope_schema": case["owner"].get("producer_scope_schema"),
        "source_only": True, "execution_allowed": False,
        "raw_gencase_receipt": {
            "path": str(case["receipt_path"]), "sha256": sha(case["receipt_path"]),
            "status": receipt.get("status"), "returncode": receipt.get("returncode"),
            "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
            "output_root": receipt.get("output_root"),
            "observed_top_level_count_fields": raw_counts,
            "partition_count_fields_missing_from_raw_receipt": missing_partition,
            "partition_counts_used_for_binding": False,
            "raw_receipt_immutable": True,
        },
        "prepared_input_report": {
            "path": str(case["report_path"]), "sha256": sha(case["report_path"]),
            "schema": report.get("schema"), "prefix": report.get("prefix"),
            "generated_xml_particle_counts": dict(case["counts"]),
            "actual_total_particles": case["total"],
            "xml_sha256_producer_record": report.get("xml_sha256"),
            "bi4_sha256_producer_record": report.get("bi4_sha256"),
            "bi4_read_or_rehashed_here": False,
            "native_initial_typed_QA": report.get("native_initial_typed_QA"),
            "q_n": report.get("q_n"), "production_approval": report.get("production_approval"),
        },
        "prepared_generated_xml": {
            "path": str(case["xml_path"]), "sha256": case["xml_sha256"],
            "bytes": case["xml_path"].stat().st_size,
            "matches_prepared_report": report.get("xml_sha256") == case["xml_sha256"],
        },
        "motion_asset_provenance": {
            **case["motion_binding"],
            "source": "prepared-input-report producer record",
            "read_or_hashed_here": False,
            "read_by_future_root_qa_worker_when_enabled": True,
        },
        "root353_request": bind(case["root_request_path"]),
        "contract_checks": checks,
        "claims": {
            "actual_gencase_prepared_evidence": True,
            "native_initial_qa": "pending Root-owned PartVTK audit",
            "native_solver": "not run by fresh102",
            "typed_conversion": "not run by fresh102",
            "visual_acceptance": "none",
            "precision_or_qn": "not granted",
            "independent_case_count_increment": 0,
            "raw_receipt_not_rewritten": True,
        },
    }
    dump(path, value)
    return path


def metadata_closure(case: Mapping[str, Any], sidecar_path: Path, *, native: bool) -> tuple[list[Path], dict[str, str]]:
    template = case["native_template"] if native else case["qa_template"]
    root_policy = ROOT230 if native else ROOT142
    paths = static_files(
        case["root_request_path"], case["receipt_path"], case["report_path"], case["xml_path"],
        case["owner_path"], case["metadata_path"], case["binding_path"],
        MANIFEST100, FRESH100_AUDIT, FRESH100_QA_ADAPTER, FRESH100_QA, FRESH100_BUILDER,
        VALIDATOR,
        RUNTIME, STRICT, ROOT142, ROOT142LAUNCH, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT,
        GPU_POLICY, RESOURCE, sidecar_path,
    )
    # Keep executable and producer motion inputs in registration closure, but
    # use only already recorded hashes. This source builder never opens either.
    executable = PARTVTK if not native else SOLVER
    if not executable.is_file():
        raise FileNotFoundError(executable)
    paths.append(executable)
    expected = {str(path): sha(path) for path in paths if path != executable}
    expected[str(executable)] = recorded_digest(template, executable)
    motion_path = Path(case["motion_binding"]["path"])
    paths.append(motion_path)
    expected[str(motion_path)] = case["motion_binding"]["sha256"]
    return paths, expected


def strict_fields(*, native: bool) -> dict[str, Any]:
    root_policy = ROOT230 if native else ROOT142
    return {
        "strict_guard_digest": STRICT_GUARD_DIGEST,
        "strict_guard": strict_guard(native=native),
        "root_dataset_inventory_profile": ROOT230_PROFILE if native else ROOT142_PROFILE,
        "root_inventory_policy_source": str(root_policy),
        "root_inventory_policy_source_sha256": sha(root_policy),
        "resource_contract": RESOURCE_CONTRACT,
        "resource_window": str(RESOURCE),
        "resource_window_sha256": sha(RESOURCE),
    }


def make_qa_request(case: Mapping[str, Any], sidecar_path: Path) -> Path:
    cid = str(case["case_id"])
    slug = cid.lower()
    attempt = f"root-stage1-f2-{slug}-prepared-report-qa-102"
    out_root = Path(case["root_request"]["raw_output_root"]).resolve()
    qa_output = out_root / attempt / "actual-initial-qa.json"
    audit_output = out_root / attempt / "prepared-report-contract.json"
    worker = FRESH100_QA_ADAPTER
    command = [
        str(PYTHON), str(worker), "--case-id", cid,
        "--definition", str(case["xml_path"]),
        "--gencase-receipt", str(case["receipt_path"]),
        "--prepared-input-report", str(case["report_path"]),
        "--prepared-report-output", str(audit_output),
        "--partvtk", str(PARTVTK), "--partvtk-output-dir", "{attempt_root}/partvtk",
        "--output", "{attempt_root}/actual-initial-qa.json",
    ]
    files, hashes = metadata_closure(case, sidecar_path, native=False)
    req = {
        "schema": "ds02.runner-request.v3", "family_id": "F2", "scope_id": SCOPE,
        "case_id": cid, "physical_case_id": case["owner"].get("physical_case_id"),
        "attempt_id": attempt, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "command": command, "cwd": str(HERE), "max_wall_seconds": 1800,
        "estimated_storage_bytes": 268435456, "worktree_root": str(INFRA),
        "raw_output_root": str(out_root), "launch_owner": "root", "root_only": True,
        "root_review_required": True, "disabled": True, "execution_allowed": False,
        "launch_allowed": False, "launch": False, "source_only": True,
        "future_hashes_null": True, "no_arrays_read": True,
        "no_science_payload_bound": True,
        "no_jobs_started": True, "no_shared_registry_write": True,
        "production_claim": "none", "qualification_claim": "none",
        "numerical_precision_status": "not accepted",
        "physical_condition_sha256": case["physical_hash"],
        "source_plan_physical_condition_sha256": case["source_plan_hash"],
        "prospective_legacy_scope_sha256": case["legacy_hash"],
        "canonical_physical_binding_sha256": case["owner"].get("canonical_physical_binding_sha256"),
        "producer_scope_schema": case["owner"].get("producer_scope_schema"),
        "gencase_attempt_id": case["gencase_attempt"],
        "depends_on_attempts": [case["gencase_attempt"]],
        "depends_on_attempt": case["gencase_attempt"],
        "gencase_receipt": str(case["receipt_path"]),
        "gencase_receipt_sha256": sha(case["receipt_path"]),
        "prepared_input_report": str(case["report_path"]),
        "prepared_input_report_sha256": sha(case["report_path"]),
        "prepared_generated_xml": str(case["xml_path"]),
        "prepared_generated_xml_sha256": case["xml_sha256"],
        "runtime_evidence_sidecar": str(sidecar_path),
        "runtime_evidence_sidecar_sha256": sha(sidecar_path),
        "motion_control_asset": case["motion_binding"],
        "motion_control_asset_digest_source": "Root353 prepared-input-report producer record; fresh102 did not read or rehash .dat",
        "required_prepared_report_fields": [
            "schema", "case_id", "prefix", "definition_sha256", "xml_sha256", "bi4_sha256",
            "generated_xml_particle_counts", "actual_total_particles", "assets",
            "native_initial_typed_QA", "mass_evidence", "q_n", "production_approval",
            "independent_case_count_increment",
        ],
        "required_checks": [
            "prepared report contract completed/0", "actual GenCase success", "actual 3-D XML",
            "finite frame zero", "positive fluid", "unique Idp", "Type/Mk/Zone partition",
            "domain/non-overlap/source lattice",
        ],
        "output_contract": {
            "prepared_report_contract_sha256": None, "actual_qa_report_sha256": None,
            "actual_counts": None, "mass_kg": None, "scientific_csv_sha256": None,
        },
        "input_files": [str(path) for path in files], "input_sha256": hashes,
        "disabled_reason": "Enable only after Root reviews the immutable Root353 receipt and prepared-report evidence; this audit is the sole producer of actual native initial QA.",
        **strict_fields(native=False),
    }
    path = HERE / "requests" / f"{cid}-initial-qa-disabled.json"
    dump(path, req)
    return path


def make_native_request(case: Mapping[str, Any], sidecar_path: Path, qa_path: Path) -> Path:
    cid = str(case["case_id"])
    slug = cid.lower()
    attempt = f"root-stage1-f2-{slug}-full401-native-fresh102"
    out_root = Path(case["root_request"]["raw_output_root"]).resolve()
    native_output = out_root / attempt / "solver_output"
    qa_attempt = f"root-stage1-f2-{slug}-prepared-report-qa-102"
    files, hashes = metadata_closure(case, sidecar_path, native=True)
    command = [str(SOLVER), str(case["report"]["prefix"]), "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"]
    req = {
        "schema": "ds02.runner-request.v3", "family_id": "F2", "scope_id": SCOPE,
        "case_id": cid, "physical_case_id": case["owner"].get("physical_case_id"),
        "attempt_id": attempt, "kind": "qualification", "cpu_task_kind": "solver", "cpu_threads": 2,
        "command": command, "cwd": str(case["xml_path"].parent), "max_wall_seconds": 3600,
        "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 8589934592,
        "target_gpu_index": None, "worktree_root": str(INFRA), "raw_output_root": str(out_root),
        "launch_owner": "root", "root_only": True, "root_review_required": True,
        "disabled": True, "execution_allowed": False, "launch_allowed": False, "launch": False,
        "source_only": True, "future_hashes_null": True, "no_arrays_read": True,
        "no_science_payload_bound": True, "no_jobs_started": True, "no_shared_registry_write": True,
        "production_claim": "none", "qualification_claim": "none",
        "numerical_precision_status": "not accepted",
        "physical_condition_sha256": case["physical_hash"],
        "source_plan_physical_condition_sha256": case["source_plan_hash"],
        "prospective_legacy_scope_sha256": case["legacy_hash"],
        "canonical_physical_binding_sha256": case["owner"].get("canonical_physical_binding_sha256"),
        "producer_scope_schema": case["owner"].get("producer_scope_schema"),
        "depends_on_attempts": [case["gencase_attempt"], qa_attempt],
        "gencase_attempt_id": case["gencase_attempt"], "initial_qa_attempt_id": qa_attempt,
        "gencase_receipt": str(case["receipt_path"]), "gencase_receipt_sha256": sha(case["receipt_path"]),
        "gencase_prefix": str(case["report"]["prefix"]),
        "prepared_input_report": str(case["report_path"]), "prepared_input_report_sha256": sha(case["report_path"]),
        "prepared_generated_xml": str(case["xml_path"]), "prepared_generated_xml_sha256": case["xml_sha256"],
        "runtime_evidence_sidecar": str(sidecar_path), "runtime_evidence_sidecar_sha256": sha(sidecar_path),
        "motion_control_asset": case["motion_binding"],
        "motion_control_asset_digest_source": "Root353 prepared-input-report producer record; fresh102 did not read or rehash .dat",
        "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path),
        "initial_qa_report": str(out_root / qa_attempt / "actual-initial-qa.json"), "initial_qa_report_sha256": None,
        "root230_dispatch": {
            "entry": str(ROOT230LAUNCH), "entry_sha256": sha(ROOT230LAUNCH),
            "gpu_policy": str(GPU_POLICY), "gpu_policy_sha256": sha(GPU_POLICY),
            "home_floor_policy": str(ROOT230), "home_floor_policy_sha256": sha(ROOT230),
            "source_policy_contract": str(ROOT230CONTRACT), "source_policy_contract_sha256": sha(ROOT230CONTRACT),
            "root_owned": True,
        },
        "solver_options_policy": "exact native command only; XML mvrotfile is authoritative; no mdbc/noslip",
        "numerical_recipe_sha256": case["native_template"].get("numerical_recipe_sha256"),
        "expected_output": {"frame_count": 401, "full_window_s": 4.0, "save_interval_s": 0.01, "solver_dimension": 3, "native_output_hash": None, "particle_counts": None},
        "native_initial_qa_required": True,
        "output_contract": {"actual_frame_count": None, "actual_particle_counts": None, "execution_receipt_sha256": None, "run_out_sha256": None},
        "future_output_paths": {"solver_output": str(native_output), "execution_receipt": str(out_root / attempt / "execution-receipt.json"), "run_out": str(native_output / "Run.out"), "frames": None},
        "input_files": [str(path) for path in files], "input_sha256": hashes,
        "disabled_reason": "Enable only after the actual Root-owned fresh102 initial QA report is completed/pass and Root230 independently approves the lease; native 4 s/401 frame evidence remains future.",
        **strict_fields(native=True),
    }
    path = HERE / "requests" / f"{cid}-native-disabled.json"
    dump(path, req)
    return path


def main() -> int:
    manifest100 = read_json(MANIFEST100)
    if manifest100.get("fresh_id") != "fresh100" or manifest100.get("case_count") != 16:
        raise SystemExit("fresh100 manifest is not the expected 16-case source")
    cases = [load_actual_case(row) for row in sorted(manifest100["cases"], key=lambda item: item["case_id"])]
    sidecars = [make_sidecar(case) for case in cases]
    generated: list[dict[str, Any]] = []
    qa_audit_rows: list[dict[str, Any]] = []
    for case, sidecar in zip(cases, sidecars):
        qa_path = make_qa_request(case, sidecar)
        native_path = make_native_request(case, sidecar, qa_path)
        generated.append({
            "case_id": case["case_id"], "physical_case_id": case["owner"].get("physical_case_id"),
            "physical_condition_sha256": case["physical_hash"], "source_plan_physical_condition_sha256": case["source_plan_hash"],
            "prospective_legacy_scope_sha256": case["legacy_hash"], "gencase_attempt_id": case["gencase_attempt"],
            "gencase_receipt": bind(case["receipt_path"]), "prepared_input_report": bind(case["report_path"]),
            "prepared_generated_xml": bind(case["xml_path"]), "runtime_evidence_sidecar": bind(sidecar),
            "initial_qa_request": bind(qa_path), "native_request": bind(native_path),
            "observed_prepared_counts": dict(case["counts"]), "observed_prepared_total": case["total"],
            "future_initial_qa_report_sha256": None, "future_native_receipt_sha256": None,
            "future_native_output_hash": None, "independent_case_count_increment": 0,
        })
        qa_audit_rows.append({
            "case_id": case["case_id"], "worker": bind(FRESH100_QA), "adapter": bind(FRESH100_QA_ADAPTER), "prepared_report_audit": bind(FRESH100_AUDIT),
            "raw_receipt_fields_used_for_gate": ["status", "returncode", "solver_dimension_from_gencase", "output_root", "output_files"],
            "raw_receipt_partition_count_fields_used": [], "partition_count_source": "prepared-input-report for contract; Root PartVTK CSV for actual native QA",
            "qa_worker_reads_scientific_payload_only_when_root_enables": True, "source_builder_read_or_hashed_dat_bi4_h5_csv": False,
        })
    qa_audit_path = HERE / "evidence/qa-worker-contract-audit.json"
    dump(qa_audit_path, {
        "schema": "ds02.f2.stage1.fresh102.qa-worker-contract-audit.v1", "fresh_id": FRESH_ID, "fresh100_immutable": True,
        "worker_review": {
            "prepared_report_contract_audit": "counts come from prepared-input-report.generated_xml_particle_counts and actual_total_particles; raw receipt only gates completed/0",
            "initial_qa_worker": "raw receipt supplies terminal status, 3-D dimension and output root; frame-zero counts/UID/Mk/Type/finite/domain checks come from the Root PartVTK CSV",
            "adapter_order": "prepared report contract audit runs before the initial QA worker", "raw_receipt_top_level_partition_counts_used": False,
        },
        "source_builder_scientific_payloads_opened": [], "motion_dat_read_or_hashed_here": False,
        "bi4_h5_csv_vtk_xmf_read_or_hashed_here": False, "cases": qa_audit_rows,
    })
    source_audit_path = HERE / "evidence/source-entry-audit.json"
    dump(source_audit_path, {
        "schema": "ds02.f2.stage1.fresh102.source-entry-audit.v1", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE,
        "case_count": len(generated), "actual_gencase_evidence_count": len(generated), "initial_qa_requests": len(generated), "native_requests": len(generated),
        "all_requests_disabled": True, "future_hashes_null": True, "root353_request_scope": str(ROOT353),
        "raw_receipts_unchanged": True, "raw_receipt_partition_counts_not_used": True,
        "source_builder_read_or_hashed_scientific_payloads": [], "motion_dat_read_or_hashed": False, "bi4_read_or_hashed": False,
        "h5_read_or_hashed": False, "csv_read_or_hashed": False, "vtk_read_or_hashed": False,
        "qa_worker_contract_audit": bind(qa_audit_path), "source_contract_validator": bind(VALIDATOR),
        "strict_guard_digest": STRICT_GUARD_DIGEST, "strict_dispatch_inputs_bound": True,
        "canonical_physical_binding_sha256": None, "qualification_or_production_grant": False, "independent_case_count_increment": 0,
        "future_artifact_hashes": "null until Root-owned initial QA/native producers complete",
    })
    manifest_path = HERE / "F2_STAGE1_FRESH102_GENCASE_RUNTIME_EVIDENCE_QA_MANIFEST.json"
    dump(manifest_path, {
        "schema": "ds02.f2.stage1.fresh102.gencase-runtime-evidence-qa-manifest.v1", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE,
        "source_only": True, "execution_allowed": False, "case_count": len(generated), "actual_gencase_evidence_count": len(generated),
        "initial_qa_request_count": len(generated), "native_request_count": len(generated), "all_requests_disabled": True, "future_hashes_null": True,
        "no_science_arrays_read": True, "no_jobs_started": True, "no_shared_registry_write": True, "raw_receipts_unchanged": True,
        "raw_receipt_partition_counts_not_used": True, "canonical_physical_binding_sha256": None, "qualification_grant": False,
        "production_claim": "none", "independent_case_count_increment": 0, "strict_guard_digest": STRICT_GUARD_DIGEST, "strict_dispatch_inputs_bound": True,
        "cases": generated, "evidence": {"source_entry_audit": bind(source_audit_path), "qa_worker_contract_audit": bind(qa_audit_path), "source_contract_validator": bind(VALIDATOR)},
    })
    (HERE / "README.md").write_text(
        """# F2 fresh102 GenCase runtime evidence and initial-QA handoff

Fresh102 binds the sixteen actual Root353 GenCase execution receipts to their
producer prepared-input-report JSON and generated XML. Raw receipts are
referenced and hashed as immutable JSON; they are not rewritten. Partition
counts come from the actual prepared report, not from a fabricated receipt
field.

Each case has one disabled CPU initial-QA request and one disabled full-window
native request. The QA request runs the existing fresh100 prepared-report
contract audit before the PartVTK frame-zero audit. The native request uses
the exact DP=0.01, 4 s, 0.01 s/401-frame recipe and depends on a future actual
QA pass. All future QA/native receipt and scientific-output hashes remain
null.

Source preparation opened only JSON/XML/Python/text metadata and did not read
or hash motion .dat, BI4, H5, CSV, VTK, or XMF payloads. The prepared motion
asset digest is carried from the Root353 producer report without re-reading
the asset; the Root-owned QA/solver job will perform its runtime input checks
when enabled. No qualification, production, visual, precision, or Q-N claim
is made.

The request closures bind the fresh100 workers, actual Root353 JSON
receipt/report/XML, source owner metadata, Root142/Root230 policy, strict
dispatch, runtime, resource approval, and per-case evidence sidecar.
""",
        encoding="utf-8",
    )
    print(json.dumps({"schema": "ds02.f2.stage1.fresh102.build-result.v1", "package": str(HERE), "case_count": len(generated), "initial_qa_requests": len(generated), "native_requests": len(generated), "future_hashes_null": True, "source_only": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
