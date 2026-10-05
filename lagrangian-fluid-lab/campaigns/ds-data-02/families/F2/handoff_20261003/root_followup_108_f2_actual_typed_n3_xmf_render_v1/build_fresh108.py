#!/usr/bin/env python3
"""Build the F2 fresh108 actual-typed -> N3 XMF -> Root023 handoff.

This source-only builder reads JSON/XML/Python/text metadata and producer
attestations.  It never opens, hashes, copies, or decodes H5/BI4/CSV/DAT/VTK
payloads and never invokes a runner, converter, XMF exporter, or renderer.
Only conversion cases whose immutable Root typed receipt and conversion report
are already completed/0 are bound; all other typed cases remain deferred.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
HERE = Path(__file__).resolve().parent
LAB = INTEGRATION / "lagrangian-fluid-lab"
FRESH107 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_107_f2_actual_native_typed_scope_bind_v1"
MANIFEST107 = FRESH107 / "F2_STAGE1_FRESH107_ACTUAL_NATIVE_TYPED_SCOPE_BIND_MANIFEST.json"
ACTUAL_TYPED = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_actual16_native420_full401_fresh107_typed_NVMe_434"
PREFLIGHT_REVIEW = ACTUAL_TYPED / "actual-root-registered-conversion-preflight-review.json"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
DIRECT = LAB / "scripts/ds_data02_direct_convert.py"
NVME = LAB / "scripts/ds_data02_nvme_convert_v1.py"
ROOT142 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230D = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230 = ROOT230D / "root_native_home_floor_inventory_policy.py"
ROOT230LAUNCH = ROOT230D / "launch.py"
ROOT230CONTRACT = ROOT230D / "source-policy-contract.json"
GPU_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SCOPE_ID = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
STRICT_GUARD_DIGEST = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
RESOURCE_CONTRACT = {
    "conversion_concurrency": 2,
    "cpu_threads": 2,
    "home_min_free_bytes": 536870912000,
    "nvme_free_space_floor_bytes": 107374182400,
    "nvme_staging_peak_limit_bytes": 25769803776,
    "nvme_staging_root": "/tmp/ds02-nvme-conversion",
    "max_wall_seconds": 5400,
}


def sha(path: Path) -> str:
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix in RAW_SUFFIXES:
        raise ValueError(f"scientific payload hash refused: {path}")
    if suffix not in STATIC_SUFFIXES:
        raise ValueError(f"non-metadata input refused: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"metadata object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def static_paths(paths: list[Path]) -> list[Path]:
    result = unique(paths)
    for path in result:
        if path.suffix.lower() in RAW_SUFFIXES:
            raise AssertionError(f"raw scientific path in static closure: {path}")
        sha(path)
    return result


def static_map(paths: list[Path]) -> dict[str, str]:
    return {str(path): sha(path) for path in static_paths(paths)}


def metadata_ref(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "exists": True}


def hex64(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} is not a 64-character digest")
    int(value, 16)
    return value


def receipt_completed(path: Path, label: str) -> dict[str, Any]:
    value = read_json(path)
    if value.get("status") != "completed" or value.get("returncode") != 0:
        raise ValueError(f"{label} is not completed/0: {path}")
    return value


def owner_source_paths(owner: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for key in ("owner_metadata", "prepared_generated_xml", "prepared_input_report", "gencase_semantic_receipt",
                "initial_qa_report", "qa_execution_receipt", "semantic_execution_receipt"):
        row = owner.get(key)
        if isinstance(row, dict) and row.get("path"):
            paths.append(Path(row["path"]))
    native = owner.get("actual_native")
    if isinstance(native, dict) and isinstance(native.get("receipt"), dict):
        paths.append(Path(native["receipt"]["path"]))
    return paths


def common_static() -> list[Path]:
    return [
        HERE / "workers/export_xmf.py", HERE / "workers/render_native023.py", HERE / "workers/fresh108_source_contract_validator.py",
        HERE / "metadata/contracts/xmf-contract.json", HERE / "metadata/contracts/render-contract.json",
        HERE / "metadata/contracts/runtime-strict-guard.json", HERE / "metadata/contracts/typed-producer-contract.json",
        HERE / "metadata/contracts/base-binary-contract.json",
        RUNTIME, STRICT, DIRECT, NVME, ROOT142, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT, GPU_POLICY, RESOURCE,
        FRESH107 / "evidence/legacy-scope-probe.json", MANIFEST107, PREFLIGHT_REVIEW,
    ]


def build_guard(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_only": True,
        "worktree_root": str(INFRA),
        "strict_guard_digest": template.get("strict_guard_digest", STRICT_GUARD_DIGEST),
        "input_closure": "set(input_files)==set(input_sha256); JSON/XML/Python/text metadata only; H5 is producer-attested and worker-read at Root execution",
        "runtime_v2": {"path": str(RUNTIME), "sha256": sha(RUNTIME)},
        "strict_dispatch": {"path": str(STRICT), "sha256": sha(STRICT)},
        "root142_inventory_policy": {"path": str(ROOT142), "sha256": sha(ROOT142)},
        "root230_native_policy": {"path": str(ROOT230), "sha256": sha(ROOT230)},
        "resource_window": {"path": str(RESOURCE), "sha256": sha(RESOURCE)},
    }


def case_selection_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = read_json(MANIFEST107)
    manifest_by_case = {row["case_id"]: row for row in manifest["cases"]}
    completed: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for request_path in sorted(ACTUAL_TYPED.glob("*-typed-request.json")):
        request = read_json(request_path)
        case_id = request["case_id"]
        row = manifest_by_case.get(case_id)
        reason: str | None = None
        report_path = Path(request["conversion_report"]).resolve()
        receipt_path = report_path.parent / "execution-receipt.json"
        report: dict[str, Any] | None = None
        receipt: dict[str, Any] | None = None
        if not report_path.is_file():
            reason = "conversion_report_not_present"
        else:
            report = read_json(report_path)
            if report.get("conversion_status") != "completed":
                reason = "conversion_report_not_completed"
            elif not receipt_path.is_file():
                reason = "typed_execution_receipt_not_present"
            else:
                receipt = read_json(receipt_path)
                if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
                    reason = "typed_execution_receipt_not_completed0"
        if row is None:
            reason = reason or "fresh107_native_binding_not_found"
        if row is not None and row.get("actual_native_status") != "completed/0":
            reason = reason or "native_not_completed0"
        if row is not None:
            qa_path = Path(row["actual_qa_report"]["path"])
            sem_path = Path(row["actual_semantic_receipt"]["path"])
            if not qa_path.is_file() or read_json(qa_path).get("status") != "pass":
                reason = reason or "initial_qa_not_passed"
            if not sem_path.is_file():
                reason = reason or "semantic_gencase_receipt_missing"
            else:
                sem = read_json(sem_path)
                if (sem.get("status"), sem.get("returncode")) != ("completed", 0):
                    reason = reason or "semantic_gencase_not_completed0"
        if reason:
            deferred.append({
                "case_id": case_id,
                "actual_typed_request": metadata_ref(request_path),
                "attempt_id": request.get("attempt_id"),
                "conversion_report": str(report_path),
                "reason": reason,
                "producer_h5_sha256": None,
            })
            continue
        assert row is not None and report is not None and receipt is not None
        if report.get("frames") != 401 or report.get("particles") != 418104:
            raise ValueError(f"unexpected completed report dimensions for {case_id}")
        h5_path = Path(str(report.get("output_hdf5")))
        h5_sha = hex64(report.get("output_sha256"), f"producer H5 digest {case_id}")
        scopes = report.get("hash_scopes", {})
        physical = scopes.get("physical_condition", {})
        if scopes.get("physical_condition_sha256") != row.get("legacy_scope_sha256"):
            raise ValueError(f"actual legacy scope mismatch for {case_id}")
        if physical.get("schema") != "legacy-owner-scope.v0":
            raise ValueError(f"unexpected producer scope schema for {case_id}")
        if physical.get("family_id") != "F2" or physical.get("dimension") not in (None, 3):
            raise ValueError(f"unexpected producer physical scope for {case_id}")
        completed.append({
            "case_id": case_id,
            "actual_request_path": request_path,
            "actual_request": request,
            "actual_typed_receipt_path": receipt_path,
            "actual_typed_receipt": receipt,
            "conversion_report_path": report_path,
            "conversion_report": report,
            "fresh107_row": row,
            "trajectory_h5": h5_path,
            "producer_h5_sha256": h5_sha,
            "physical_case_id": physical.get("physical_case_id"),
            "legacy_scope_sha256": scopes["physical_condition_sha256"],
        })
    return completed, deferred


def producer_paths(case: dict[str, Any]) -> dict[str, Path]:
    row = case["fresh107_row"]
    owner = read_json(Path(row["scope_owner"]["path"]))
    report = case["conversion_report"]
    source_owner = report.get("source_provenance", {}).get("owner_metadata", {})
    paths: dict[str, Path] = {
        "scope_owner": Path(row["scope_owner"]["path"]).resolve(),
        "actual_native_receipt": Path(row["actual_native_receipt"]["path"]).resolve(),
        "qa_report": Path(row["actual_qa_report"]["path"]).resolve(),
        "semantic_receipt": Path(row["actual_semantic_receipt"]["path"]).resolve(),
        "typed_scope_request": Path(row["typed_request"]["path"]).resolve() if row.get("typed_request") else Path(row["typed_request"]["path"]).resolve(),
        "prepared_xml": Path(owner["prepared_generated_xml"]["path"]).resolve(),
        "prepared_input_report": Path(owner["prepared_input_report"]["path"]).resolve(),
        "qa_execution_receipt": Path(owner["qa_execution_receipt"]["path"]).resolve(),
        "semantic_execution_receipt": Path(owner["semantic_execution_receipt"]["path"]).resolve(),
        "gencase_receipt": Path(report["source_provenance"]["gencase_receipt"]["path"]).resolve(),
        "source_owner_metadata": Path(source_owner["path"]).resolve(),
    }
    # The source owner record is itself the actual scope probe output.  Keep
    # its declared legacy hash and whole-record digest separate from the
    # source-plan hash; never substitute it for a canonical physical hash.
    if owner.get("prospective_legacy_scope_sha256") != case["legacy_scope_sha256"]:
        raise ValueError(f"owner/report legacy scope mismatch: {case['case_id']}")
    for label, path in paths.items():
        if path.suffix.lower() in RAW_SUFFIXES:
            raise ValueError(f"raw producer path unexpectedly selected as metadata: {label} {path}")
        if not path.is_file():
            raise FileNotFoundError(f"missing metadata producer path {label}: {path}")
    return paths


def actual_attempt(path: Path) -> str:
    return path.parent.name


def base_request(meta: dict[str, Any], owner: dict[str, Any], static: list[Path], attempt: str,
                 guard: dict[str, Any], *, max_wall: int) -> dict[str, Any]:
    return {
        "schema": "ds02.runner-request.v3",
        "family_id": "F2", "scope_id": SCOPE_ID,
        "case_id": meta["case_id"], "physical_case_id": meta["physical_case_id"],
        "physical_condition_sha256": meta["legacy_scope_sha256"],
        "source_plan_physical_condition_sha256": meta["source_plan_sha256"],
        "prospective_legacy_scope_sha256": meta["legacy_scope_sha256"],
        "actual_converter_physical_condition_sha256": None,
        "canonical_physical_binding_sha256": None,
        "producer_scope_schema": "legacy-owner-scope.v0",
        "canonical_grant": False,
        "semantic_binding_status": "actual legacy-owner scope only; canonical physical binding not granted",
        "source_only": True, "execution_allowed": False, "launch_allowed": False, "launch": False,
        "launch_owner": "root", "root_only": True, "root_review_required": True, "disabled": True,
        "future_hashes_null": True, "no_arrays_read": True, "no_science_payload_bound": True,
        "no_jobs_started": True, "no_shared_registry_write": True,
        "production_claim": "none", "qualification_claim": "none", "numerical_precision_status": "not accepted",
        "attempt_id": attempt, "worktree_root": str(INFRA),
        "raw_output_root": str((DATA_ROOT / "families" / "F2" / meta["case_id"]).resolve()),
        "input_files": [str(path) for path in static],
        "input_sha256": {str(path): sha(path) for path in static},
        "strict_guard_digest": guard["strict_guard_digest"], "strict_guard": guard,
        "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_v1",
        "root_inventory_policy_source": str(ROOT142), "root_inventory_policy_source_sha256": sha(ROOT142),
        "resource_contract": RESOURCE_CONTRACT,
        "resource_window": str(RESOURCE), "resource_window_sha256": sha(RESOURCE),
        "max_wall_seconds": max_wall, "cpu_threads": 2,
    }


def make_case(case: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    cid = case["case_id"]
    report = case["conversion_report"]
    row = case["fresh107_row"]
    owner_path = Path(row["scope_owner"]["path"]).resolve()
    owner = read_json(owner_path)
    paths = producer_paths(case)
    typed_request_path = case["actual_request_path"].resolve()
    typed_receipt_path = case["actual_typed_receipt_path"].resolve()
    report_path = case["conversion_report_path"].resolve()
    native_receipt_path = paths["actual_native_receipt"]
    qa_report_path = paths["qa_report"]
    semantic_receipt_path = paths["semantic_receipt"]
    gencase_receipt_path = paths["gencase_receipt"]
    prepared_xml = paths["prepared_xml"]
    prepared_input_report = paths["prepared_input_report"]
    qa_execution_receipt = paths["qa_execution_receipt"]
    semantic_execution_receipt = paths["semantic_execution_receipt"]
    source_owner_metadata = paths["source_owner_metadata"]
    source_plan = owner["source_plan_physical_condition_sha256"]
    legacy_scope = case["legacy_scope_sha256"]
    actual_particles = int(report["particles"])
    physical_case_id = case["physical_case_id"]
    native_attempt = actual_attempt(native_receipt_path)
    qa_attempt = actual_attempt(qa_report_path)
    gencase_attempt = actual_attempt(gencase_receipt_path)
    semantic_attempt = actual_attempt(semantic_receipt_path)
    typed_attempt = case["actual_request"]["attempt_id"]
    xmf_attempt = f"root-stage1-f2-{cid.lower()}-actual-typed-n3-xmf-108"
    render_attempt = f"root-stage1-f2-{cid.lower()}-actual-typed-root023-render-108"
    xmf_binding_path = HERE / "xmf/bindings" / f"{cid}.xmf-binding.json"
    render_binding_path = HERE / "render/bindings" / f"{cid}.render-binding.json"
    xmf_request_path = HERE / "xmf/requests" / f"{cid}-xmf-disabled.json"
    render_request_path = HERE / "render/requests" / f"{cid}-render-disabled.json"
    xmf_case = Path(case["trajectory_h5"]).parent.parent / xmf_attempt / "xdmf/case.xmf"
    xmf_manifest = Path(case["trajectory_h5"]).parent.parent / xmf_attempt / "xdmf/manifest.json"
    render_root = Path(case["trajectory_h5"]).parent.parent / render_attempt
    source_static = static_paths(common_static() + [
        typed_request_path, typed_receipt_path, report_path,
        owner_path, source_owner_metadata,
        native_receipt_path, qa_report_path, qa_execution_receipt,
        semantic_receipt_path, semantic_execution_receipt, gencase_receipt_path,
        prepared_xml, prepared_input_report,
    ])
    guard = build_guard(template)
    expected_contract = {
        "dimension": 3, "frames": 401, "particles": actual_particles,
        "key": "(Zone,Idp)", "counts_source": "actual completed conversion-report",
        "vectors": "N 3", "scalars": "N",
    }
    producer = {
        "conversion_report": metadata_ref(report_path),
        "typed_execution_receipt": metadata_ref(typed_receipt_path),
        "trajectory_h5": {"path": str(case["trajectory_h5"]), "producer_sha256": case["producer_h5_sha256"], "source_preparer_read_or_hashed": False},
        "status": "completed/0",
        "frames": int(report["frames"]), "particles": actual_particles, "dimension": 3,
        "physical_condition_sha256": legacy_scope,
        "scope_schema": "legacy-owner-scope.v0",
    }
    xmf_binding = {
        "schema": "ds02.f2.stage1.fresh108.xmf-binding.v1",
        "fresh_id": "fresh108", "family_id": "F2", "scope_id": SCOPE_ID,
        "case_id": cid, "physical_case_id": physical_case_id,
        "producer_scope_schema": "legacy-owner-scope.v0",
        "semantic_binding_status": "actual legacy-owner scope only; canonical physical binding not granted",
        "physical_condition_sha256": legacy_scope,
        "source_plan_physical_condition_sha256": source_plan,
        "prospective_legacy_scope_sha256": legacy_scope,
        "actual_converter_physical_condition_sha256": None,
        "canonical_physical_binding_sha256": None, "canonical_grant": False,
        "scope_owner": str(owner_path), "scope_owner_sha256": sha(owner_path),
        "source_owner_metadata": str(source_owner_metadata), "source_owner_metadata_sha256": sha(source_owner_metadata),
        "typed_request": str(typed_request_path), "typed_request_sha256": sha(typed_request_path),
        "typed_scope_request": str(Path(row["typed_request"]["path"]).resolve()), "typed_scope_request_sha256": sha(Path(row["typed_request"]["path"]).resolve()),
        "typed_receipt": str(typed_receipt_path), "typed_receipt_sha256": sha(typed_receipt_path),
        "conversion_report": str(report_path), "conversion_report_sha256": sha(report_path),
        "trajectory_h5": str(case["trajectory_h5"]), "trajectory_h5_sha256": None,
        "trajectory_h5_producer_sha256": case["producer_h5_sha256"],
        "native_receipt": str(native_receipt_path), "native_receipt_sha256": sha(native_receipt_path),
        "gencase_receipt": str(gencase_receipt_path), "gencase_receipt_sha256": sha(gencase_receipt_path),
        "semantic_gencase_receipt": str(semantic_receipt_path), "semantic_gencase_receipt_sha256": sha(semantic_receipt_path),
        "prepared_generated_xml": str(prepared_xml), "prepared_generated_xml_sha256": sha(prepared_xml),
        "prepared_input_report": str(prepared_input_report), "prepared_input_report_sha256": sha(prepared_input_report),
        "initial_qa_report": str(qa_report_path), "initial_qa_report_sha256": sha(qa_report_path),
        "qa_execution_receipt": str(qa_execution_receipt), "qa_execution_receipt_sha256": sha(qa_execution_receipt),
        "semantic_execution_receipt": str(semantic_execution_receipt), "semantic_execution_receipt_sha256": sha(semantic_execution_receipt),
        "expected_dimension": 3, "actual_dimension": 3, "expected_native_frames": 401,
        "actual_frame_count": int(report["frames"]), "expected_particles": actual_particles, "actual_particles": actual_particles,
        "physical_window_s": [0.0, 4.0], "save_interval_s": 0.01,
        "actual_typed_status": "completed/0", "actual_partvtk_passed": bool(report.get("partvtk_validation", {}).get("all_passed")),
        "typed_identity_summary": {k: report.get("typed_identity", {}).get(k) for k in ("key", "observed_mks", "observed_types", "zone_source", "mass_semantics")},
        "expected_native_contract": expected_contract,
        "xmf_shape_contract": {"dynamic_vector_dimensions": "{actual_particles} 3", "dynamic_scalar_dimensions": "{actual_particles}", "particle_axis_preserved": True, "counts_from_actual_conversion_report": True},
        "producer_attestation": producer,
        "bound_metadata_sha256": static_map(source_static),
        "future_hashes_null": True, "source_only": True, "disabled": True, "execution_allowed": False, "launch_allowed": False,
        "independent_case_increment": 0, "visual_status": "pending Root023 full401 render review",
        "numerical_precision_status": "not accepted",
        "output_dir_contract": "{attempt_root}/xdmf must start empty; receipt/stdout remain in attempt root",
        "future_outputs": {"case_xmf": None, "case_xmf_sha256": None, "manifest": None, "manifest_sha256": None, "execution_receipt": None, "execution_receipt_sha256": None},
    }
    dump(xmf_binding_path, xmf_binding)
    xmf_static = static_paths(source_static + [xmf_binding_path])
    xreq = base_request({"case_id": cid, "physical_case_id": physical_case_id, "legacy_scope_sha256": legacy_scope, "source_plan_sha256": source_plan}, owner, xmf_static, xmf_attempt, guard, max_wall=5400)
    xreq.update({
        "kind": "cpu", "cpu_task_kind": "audit", "estimated_storage_bytes": 34359738368,
        "command": [str(LAB / ".venv/bin/python"), str(HERE / "workers/export_xmf.py"), "--binding", str(xmf_binding_path), "--output-dir", "{attempt_root}/xdmf"],
        "cwd": str(HERE), "depends_on_attempts": [gencase_attempt, semantic_attempt, qa_attempt, native_attempt, typed_attempt],
        "typed_receipt": str(typed_receipt_path), "typed_receipt_sha256": sha(typed_receipt_path),
        "conversion_report": str(report_path), "conversion_report_sha256": sha(report_path),
        "trajectory_h5": str(case["trajectory_h5"]), "trajectory_h5_sha256": None, "trajectory_h5_producer_sha256": case["producer_h5_sha256"],
        "native_receipt": str(native_receipt_path), "native_receipt_sha256": sha(native_receipt_path),
        "gencase_receipt": str(gencase_receipt_path), "gencase_receipt_sha256": sha(gencase_receipt_path),
        "initial_qa_report": str(qa_report_path), "initial_qa_report_sha256": sha(qa_report_path),
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": actual_particles,
        "actual_typed_status": "completed/0", "actual_h5_producer_sha256": case["producer_h5_sha256"],
        "physical_condition_hash_scope": {"source_plan_physical_condition_sha256": source_plan, "prospective_legacy_scope_sha256": legacy_scope, "actual_converter_physical_condition_sha256": None, "canonical_physical_binding_sha256": None, "canonical_grant": False},
        "producer_input_files": [str(case["trajectory_h5"])],
        "producer_input_sha256": {str(case["trajectory_h5"]): case["producer_h5_sha256"]},
        "future_input_files": [str(case["trajectory_h5"])],
        "future_input_sha256": {str(case["trajectory_h5"]): case["producer_h5_sha256"]},
        "future_outputs": xmf_binding["future_outputs"],
        "output_contract": {"case_xmf_sha256": None, "manifest_sha256": None, "actual_frame_count": None, "actual_particle_counts": None},
        "disabled_reason": "Enable only after Root reviews the completed typed producer metadata and preserves the producer H5 digest; XMF output remains future.",
    })
    dump(xmf_request_path, xreq)
    render_binding = {
        "schema": "ds02.f2.stage1.fresh108.render-binding.v1",
        "fresh_id": "fresh108", "family_id": "F2", "scope_id": SCOPE_ID,
        "case_id": cid, "physical_case_id": physical_case_id,
        "producer_scope_schema": "legacy-owner-scope.v0",
        "semantic_binding_status": "actual legacy-owner scope only; canonical physical binding not granted",
        "physical_condition_sha256": legacy_scope, "source_plan_physical_condition_sha256": source_plan,
        "prospective_legacy_scope_sha256": legacy_scope, "actual_converter_physical_condition_sha256": None,
        "canonical_physical_binding_sha256": None, "canonical_grant": False,
        "scope_owner": str(owner_path), "scope_owner_sha256": sha(owner_path),
        "typed_receipt": str(typed_receipt_path), "typed_receipt_sha256": sha(typed_receipt_path),
        "conversion_report": str(report_path), "conversion_report_sha256": sha(report_path),
        "trajectory_h5": str(case["trajectory_h5"]), "trajectory_h5_sha256": None, "trajectory_h5_producer_sha256": case["producer_h5_sha256"],
        "native_receipt": str(native_receipt_path), "native_receipt_sha256": sha(native_receipt_path),
        "xmf_binding": str(xmf_binding_path), "xmf_binding_sha256": sha(xmf_binding_path),
        "xmf_case": str(xmf_case), "xmf_case_sha256": None, "xmf_manifest": str(xmf_manifest), "xmf_manifest_sha256": None,
        "expected_dimension": 3, "expected_native_frames": 401, "actual_frame_count": int(report["frames"]), "expected_particles": actual_particles,
        "physical_window_s": [0.0, 4.0], "save_interval_s": 0.01, "expected_native_contract": expected_contract,
        "producer_attestation": producer,
        "camera_policy": {"bounds_source": "Root023 scans every native valid position across every saved frame", "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False, "fixed_camera_override": False, "native_geometry_retained": True},
        "contact_pages": 17, "bound_metadata_sha256": static_map(static_paths(source_static + [xmf_binding_path, render_binding_path]) if render_binding_path.exists() else source_static + [xmf_binding_path]),
        "future_hashes_null": True, "source_only": True, "disabled": True, "execution_allowed": False, "launch_allowed": False,
        "independent_case_increment": 0, "visual_status": "pending Root023 full401 render review", "numerical_precision_status": "not accepted",
        "output_dir_contract": "{attempt_root}/render must start empty; receipt/stdout remain in attempt root",
        "future_outputs": {"execution_receipt": None, "execution_receipt_sha256": None, "report": None, "report_sha256": None, "frames_dir": None, "frames_sha256": None, "contact_sheets": None, "gif": None, "gif_sha256": None, "pvsm": None, "pvsm_sha256": None},
    }
    dump(render_binding_path, render_binding)
    render_static = static_paths(source_static + [xmf_binding_path, render_binding_path])
    rreq = base_request({"case_id": cid, "physical_case_id": physical_case_id, "legacy_scope_sha256": legacy_scope, "source_plan_sha256": source_plan}, owner, render_static, render_attempt, guard, max_wall=7200)
    rreq.update({
        "kind": "cpu", "cpu_task_kind": "audit", "estimated_storage_bytes": 34359738368,
        "command": ["/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython", str(HERE / "workers/render_native023.py"), "--manifest", str(xmf_manifest), "--output-dir", "{attempt_root}/render"],
        "cwd": str(HERE), "depends_on_attempts": [typed_attempt, native_attempt, xmf_attempt],
        "xmf_attempt": xmf_attempt, "xmf_binding": str(xmf_binding_path), "xmf_binding_sha256": sha(xmf_binding_path),
        "xmf_case": str(xmf_case), "xmf_case_sha256": None, "xmf_manifest": str(xmf_manifest), "xmf_manifest_sha256": None,
        "typed_receipt": str(typed_receipt_path), "typed_receipt_sha256": sha(typed_receipt_path),
        "conversion_report": str(report_path), "conversion_report_sha256": sha(report_path),
        "trajectory_h5": str(case["trajectory_h5"]), "trajectory_h5_sha256": None, "trajectory_h5_producer_sha256": case["producer_h5_sha256"],
        "native_receipt": str(native_receipt_path), "native_receipt_sha256": sha(native_receipt_path),
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": actual_particles,
        "actual_typed_status": "completed/0", "actual_partvtk_passed": bool(report.get("partvtk_validation", {}).get("all_passed")),
        "actual_h5_producer_sha256": case["producer_h5_sha256"], "camera_policy": render_binding["camera_policy"],
        "producer_input_files": [str(case["trajectory_h5"]), str(xmf_manifest)],
        "producer_input_sha256": {str(case["trajectory_h5"]): case["producer_h5_sha256"], str(xmf_manifest): None},
        "future_input_files": [str(case["trajectory_h5"]), str(xmf_case), str(xmf_manifest)],
        "future_input_sha256": {str(case["trajectory_h5"]): case["producer_h5_sha256"], str(xmf_case): None, str(xmf_manifest): None},
        "future_outputs": render_binding["future_outputs"],
        "output_contract": {"execution_receipt_sha256": None, "report_sha256": None, "frames_sha256": None, "actual_frame_count": None},
        "disabled_reason": "Enable only after Root reviews the completed XMF manifest and preserves full native 401-frame geometry; renderer outputs remain future.",
    })
    dump(render_request_path, rreq)
    return {
        "case_id": cid, "physical_case_id": physical_case_id, "source_plan_physical_condition_sha256": source_plan,
        "prospective_legacy_scope_sha256": legacy_scope, "canonical_physical_binding_sha256": None,
        "completed_typed": True, "actual_typed_receipt": metadata_ref(typed_receipt_path),
        "actual_conversion_report": metadata_ref(report_path), "producer_h5_sha256": case["producer_h5_sha256"],
        "actual_native_receipt": metadata_ref(native_receipt_path), "actual_qa_report": metadata_ref(qa_report_path),
        "xmf_binding": metadata_ref(xmf_binding_path), "xmf_request": metadata_ref(xmf_request_path),
        "render_binding": metadata_ref(render_binding_path), "render_request": metadata_ref(render_request_path),
        "expected_frames": 401, "actual_frames": int(report["frames"]), "expected_particles": actual_particles, "actual_particles": actual_particles,
        "actual_h5_sha256_source": None, "actual_h5_sha256_producer": case["producer_h5_sha256"],
        "actual_xmf_sha256": None, "actual_render_sha256": None, "independent_case_count_increment": 0,
    }


def main() -> int:
    manifest107 = read_json(MANIFEST107)
    template_request = read_json(next(ACTUAL_TYPED.glob("*-typed-request.json")))
    template = {"strict_guard_digest": template_request.get("strict_guard_digest", STRICT_GUARD_DIGEST)}
    completed, deferred = case_selection_rows()
    if not completed:
        raise SystemExit("no completed typed conversion metadata available")
    dump(HERE / "metadata/contracts/xmf-contract.json", {
        "schema": "ds02.f2.stage1.fresh108.xmf-contract.v1",
        "worker": str((HERE / "workers/export_xmf.py").resolve()), "worker_sha256": sha(HERE / "workers/export_xmf.py"),
        "producer_scope_schema": "legacy-owner-scope.v0", "expected_frames": 401, "expected_dimension": 3,
        "counts_source": "actual completed conversion-report only", "dynamic_vector_dimensions": "{actual_particles} 3",
        "dynamic_scalar_dimensions": "{actual_particles}", "output_dir": "{attempt_root}/xdmf",
        "output_dir_must_start_empty": True, "raw_metadata_only_at_source": True,
        "producer_h5_digest_source": "actual conversion-report.output_sha256; source builder does not read/hash H5",
        "future_output_hashes_null": True,
    })
    dump(HERE / "metadata/contracts/render-contract.json", {
        "schema": "ds02.f2.stage1.fresh108.render-contract.v1",
        "worker": str((HERE / "workers/render_native023.py").resolve()), "worker_sha256": sha(HERE / "workers/render_native023.py"),
        "renderer": "Root023 CPU-only offscreen ParaView worker", "expected_frames": 401, "expected_dimension": 3,
        "camera_bounds_policy": {"bounds_source": "Root023 scans every native valid position across every saved frame", "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False, "fixed_camera_override": False, "native_geometry_retained": True},
        "output_dir": "{attempt_root}/render", "output_dir_must_start_empty": True, "raw_metadata_only_at_source": True,
        "future_output_hashes_null": True,
    })
    dump(HERE / "metadata/contracts/typed-producer-contract.json", {
        "schema": "ds02.f2.stage1.fresh108.typed-producer-contract.v1",
        "source_scope_schema": "legacy-owner-scope.v0", "source_plan_and_legacy_scope_separate": True,
        "actual_typed_status_required": "completed/0", "actual_frames": 401, "actual_dimension": 3, "actual_particles": 418104,
        "h5_sha256": "producer-attested conversion-report.output_sha256 only; source does not hash H5",
        "actual_converter_physical_condition_sha256": None, "canonical_physical_binding_sha256": None,
        "future_xmf_hashes": None, "future_render_hashes": None, "no_science_payload_read_or_hash_by_source": True,
    })
    dump(HERE / "metadata/contracts/base-binary-contract.json", {
        "schema": "ds02.f2.stage1.fresh108.base-binary-contract.v1",
        "root023_renderer": "/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython",
        "decoder_producer_attestation": {"path": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump", "sha256": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"},
        "native_recipe": {"frames": 401, "save_interval_s": 0.01, "window_s": [0.0, 4.0], "dimension": 3},
        "root_owned": True, "disabled": True, "scientific_payloads_read_or_hashed_by_source": [],
    })
    generated: list[dict[str, Any]] = []
    for case in sorted(completed, key=lambda row: row["case_id"]):
        generated.append(make_case(case, template))
    static_common = static_paths(common_static() + [HERE / "metadata/contracts/xmf-contract.json", HERE / "metadata/contracts/render-contract.json", HERE / "metadata/contracts/typed-producer-contract.json", HERE / "metadata/contracts/base-binary-contract.json"])
    dump(HERE / "evidence/typed-selection.json", {
        "schema": "ds02.f2.stage1.fresh108.typed-selection.v1", "source_only": True,
        "actual_typed_directory": str(ACTUAL_TYPED), "upstream_fresh107_manifest": str(MANIFEST107),
        "completed_count": len(generated), "deferred_count": len(deferred),
        "completed_cases": [{"case_id": row["case_id"], "producer_h5_sha256": row["producer_h5_sha256"], "frames": row["actual_frames"], "particles": row["actual_particles"]} for row in generated],
        "deferred_cases": deferred, "h5_read_or_hashed_by_source": False, "science_arrays_read_by_source": [],
        "status_semantics": "Only actual completed/0 typed receipts and completed conversion reports are bound; missing reports remain deferred.",
    })
    dump(HERE / "evidence/source-entry-audit.json", {
        "schema": "ds02.f2.stage1.fresh108.source-entry-audit.v1", "case_count": len(generated),
        "xmf_requests": len(generated), "render_requests": len(generated), "all_requests_disabled": True,
        "future_xmf_hashes_null": True, "future_render_hashes_null": True,
        "actual_h5_producer_digests_bound": True, "source_h5_hashes": [], "source_scientific_payloads_opened": [],
        "raw_suffixes_refused": sorted(RAW_SUFFIXES), "static_suffixes_allowed": sorted(STATIC_SUFFIXES),
        "source_plan_legacy_actual_converter_canonical_separate": True,
        "strict_guard_digest": template["strict_guard_digest"], "strict_dispatch_sha256": sha(STRICT),
        "upstream_preflight_review": metadata_ref(PREFLIGHT_REVIEW),
        "independent_case_count_increment": 0, "canonical_grant": False,
    })
    dump(HERE / "evidence/source-static-closure.json", {"schema": "ds02.f2.stage1.fresh108.source-static-closure.v1", "files": {str(path): sha(path) for path in static_common}, "scientific_payloads": [], "source_h5_read_or_hashed": False})
    preflight_review = read_json(PREFLIGHT_REVIEW)
    corrections = preflight_review.get("source_metadata_digest_corrections", [])
    if not isinstance(corrections, list):
        raise ValueError("upstream source_metadata_digest_corrections must be a list")
    dump(HERE / "evidence/upstream-digest-corrections.json", {
        "schema": "ds02.f2.stage1.fresh108.upstream-digest-corrections.v1",
        "source_only": True,
        "upstream_preflight_review": metadata_ref(PREFLIGHT_REVIEW),
        "correction_count": len(corrections),
        "corrections": corrections,
        "meaning": "Root preflight observed source-declared owner digests differing from the committed immutable owner bytes; fresh108 binds current immutable metadata bytes and preserves each source negative.",
        "scientific_payloads_read_or_hashed": [],
    })
    dump(HERE / "F2_STAGE1_FRESH108_ACTUAL_TYPED_N3_XMF_RENDER_MANIFEST.json", {
        "schema": "ds02.f2.stage1.fresh108.actual-typed-n3-xmf-render-manifest.v1",
        "fresh_id": "fresh108", "family_id": "F2", "scope_id": SCOPE_ID, "source_only": True,
        "execution_allowed": False, "case_count": len(generated), "deferred_typed_case_count": len(deferred),
        "cases": generated, "deferred_cases": deferred,
        "expected_native_frames": 401, "expected_dimension": 3, "producer_scope_schema": "legacy-owner-scope.v0",
        "source_plan_and_legacy_scope_separate": True, "canonical_physical_binding_sha256": None, "canonical_grant": False,
        "strict_guard_digest": template["strict_guard_digest"], "future_hashes_null": True,
        "all_requests_disabled": True, "no_science_arrays_read": True, "no_jobs_started": True, "no_shared_registry_write": True,
        "independent_case_count_increment": 0,
        "contracts": {name: metadata_ref(HERE / f"metadata/contracts/{name}.json") for name in ("xmf-contract", "render-contract", "typed-producer-contract", "base-binary-contract")},
        "workers": {"export_xmf": metadata_ref(HERE / "workers/export_xmf.py"), "render_native023": metadata_ref(HERE / "workers/render_native023.py")},
    })
    (HERE / "README.md").write_text(
        f"""# F2 fresh108 actual typed to N3 XMF and Root023 render handoff

Fresh108 binds only the currently completed Root typed conversion reports and
execution receipts. The current metadata snapshot selects {len(generated)}
completed cases and leaves {len(deferred)} later typed cases deferred until
their producer report is present.

Each selected case has a disabled dynamic N3 XMF request and a disabled Root023
full-401-frame renderer request. XMF dimensions are derived from the actual
conversion report at Root execution: vectors are N 3 and scalars are N. The
renderer keeps all native geometry and asks Root023 to scan every saved frame
for bounds; no camera or domain bounds are prefilled.

The producer H5 path and its conversion-report output_sha256 are bound as an
attestation. The source builder did not read, hash, copy, or decode
H5/BI4/CSV/DAT/VTK payloads. XMF/render receipts, output hashes, canonical
physical scope, Q-N, precision, and production status remain null or ungranted.
Source-plan, actual legacy-owner scope, future converter scope, and canonical
physical binding remain separate.

The package does not launch jobs or modify shared registry/ledger state. Root
must independently review and enable each disabled request.
""", encoding="utf-8")
    print(json.dumps({"schema": "ds02.f2.stage1.fresh108.build-result.v1", "package": str(HERE), "completed_typed_cases": len(generated), "deferred_typed_cases": len(deferred), "xmf_requests": len(generated), "render_requests": len(generated), "future_hashes_null": True, "source_only": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
