#!/usr/bin/env python3
"""Build the F2 fresh104 parser-repair and downstream adapter package.

The builder reads JSON, XML and source metadata only.  It may inspect the
Root379 JSON reports and execution receipts, but it never opens or hashes a
CSV, BI4, DAT, VTK, H5 or other scientific payload.  The four completed
Root379 reports are retained as explicit negative evidence; the other twelve
remain pending.  All new requests are disabled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
BASE = Path("/home/jade/Projects/DualSPHysics").resolve()
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
HERE = Path(__file__).resolve().parent
HANDOFF = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003"
FRESH100 = HANDOFF / "root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1"
FRESH102 = HANDOFF / "root_followup_102_f2_gencase_runtime_evidence_qa_v1"
FRESH103 = HANDOFF / "root_followup_103_f2_fresh102_native_path_xmf_adapter_v1"
M103 = FRESH103 / "F2_STAGE1_FRESH103_NATIVE_PATH_XMF_ADAPTER_MANIFEST.json"
ROOT378 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_actual16_GenCase354_semantic103_initialQA_378"
LAB = INTEGRATION / "lagrangian-fluid-lab"
PYTHON = LAB / ".venv/bin/python"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
ROOT142 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230D = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230 = ROOT230D / "root_native_home_floor_inventory_policy.py"
ROOT230LAUNCH = ROOT230D / "launch.py"
ROOT230CONTRACT = ROOT230D / "source-policy-contract.json"
GPU_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
PARTVTK = BASE / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
FRESH_ID = "fresh104"
SCOPE = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
LOGICAL_GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
STRICT_DISPATCH_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}


def sha(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"source builder refuses scientific/non-static path: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def bind(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "exists": True}


def recorded(path: str, digest: str | None, source: str) -> dict[str, Any]:
    return {"path": str(Path(path).resolve()), "sha256": digest, "read_or_hashed_here": False, "digest_source": source}


def closure_from_template(template: Mapping[str, Any]) -> dict[str, str]:
    """Rehash safe metadata; preserve producer digests for raw inputs."""
    output: dict[str, str] = {}
    for raw_path, expected in (template.get("input_sha256") or {}).items():
        path = Path(str(raw_path)).resolve()
        if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f"invalid producer digest for {path}")
            output[str(path)] = expected
        else:
            actual = sha(path)
            if actual != expected:
                raise ValueError(f"metadata input changed: {path}: {actual} != {expected}")
            output[str(path)] = actual
    return output


def add_static(files: dict[str, str], path: Path) -> None:
    path = Path(path).resolve()
    files[str(path)] = sha(path)


def future_map(paths: list[Path | str]) -> tuple[list[str], dict[str, None]]:
    values = [str(Path(path).resolve()) for path in paths]
    return values, {value: None for value in values}


def strict_guard(native: bool) -> dict[str, Any]:
    return {
        "strict_guard_digest": LOGICAL_GUARD,
        "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA,
        "source_only": True,
        "worktree_root": str(INFRA),
        "input_closure": "set(input_files)==set(input_sha256); raw producer inputs may remain unread; future outputs stay null",
        "runtime_v2": {"path": str(RUNTIME), "sha256": sha(RUNTIME)},
        "strict_dispatch": {"path": str(STRICT), "sha256": sha(STRICT)},
        "root142_inventory_policy": {"path": str(ROOT142), "sha256": sha(ROOT142)},
        "root230_inventory_policy": {"path": str(ROOT230), "sha256": sha(ROOT230)},
        "root_inventory_policy": {"path": str(ROOT230 if native else ROOT142), "sha256": sha(ROOT230 if native else ROOT142)},
        "resource_window": {"path": str(RESOURCE), "sha256": sha(RESOURCE)},
    }


def actual_qa_observation(root_request: Mapping[str, Any]) -> dict[str, Any]:
    """Read only Root379 JSON metadata; never touch its CSV path."""
    attempt = str(root_request["attempt_id"])
    case_root = Path(str(root_request["raw_output_root"])).resolve().parent
    attempt_root = case_root / attempt
    report_path = attempt_root / "actual-initial-qa.json"
    receipt_path = attempt_root / "execution-receipt.json"
    report = load(report_path) if report_path.is_file() else None
    receipt = load(receipt_path) if receipt_path.is_file() else None
    report_binding = bind(report_path) if report is not None else {"path": str(report_path), "sha256": None, "exists": False}
    receipt_binding = bind(receipt_path) if receipt is not None else {"path": str(receipt_path), "sha256": None, "exists": False}
    status = report.get("status") if report else None
    checks = report.get("checks", {}) if report else {}
    passed = bool(status == "pass" and checks and all(value is True for value in checks.values()) and receipt and receipt.get("status") == "completed" and receipt.get("returncode") == 0)
    return {
        "case_id": str(root_request["case_id"]),
        "attempt_id": attempt,
        "request_path": str(Path(str(root_request["_request_path"])).resolve()),
        "request_sha256": root_request["_request_sha256"],
        "attempt_root": str(attempt_root),
        "report": report_binding,
        "receipt": receipt_binding,
        "report_status": status,
        "receipt_status": receipt.get("status") if receipt else None,
        "receipt_returncode": receipt.get("returncode") if receipt else None,
        "checks": checks,
        "passed": passed if report is not None else None,
        "negative_evidence": bool(report is not None and not passed),
        "csv_path_recorded_by_root": ((report or {}).get("csv_summary") or {}).get("csv", {}).get("path") if report else None,
        "csv_sha256_recorded_by_root": ((report or {}).get("csv_summary") or {}).get("csv", {}).get("sha256") if report else None,
        "csv_read_or_hashed_by_source_builder": False,
    }


def qa_retry_request(case: Mapping[str, Any], root_request: Mapping[str, Any], observation: Mapping[str, Any], manifest_row: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"])
    slug = cid.lower()
    attempt = f"root-stage1-f2-{slug}-prepared-report-qa-csv-parser-repair-104"
    worker = HERE / "workers/fresh104_initial_qa_csv_parser.py"
    files = closure_from_template(load(Path(str(case["initial_qa_adapter_request"]["path"]))))
    for path in [worker, HERE / "metadata/contracts/csv-parser-contract.json", HERE / "metadata/contracts/runtime-strict-guard.json", Path(str(observation["request_path"]))]:
        add_static(files, path)
    for item in (observation["report"], observation["receipt"]):
        if item.get("exists"):
            add_static(files, Path(str(item["path"])))
    gencase_receipt = Path(str(root_request["gencase_receipt"])).resolve()
    xml = Path(str(root_request["prepared_generated_xml"])).resolve()
    report = Path(str(root_request["prepared_input_report"])).resolve()
    evidence = Path(str(root_request["runtime_evidence_sidecar"])).resolve()
    report_out = "{attempt_root}/actual-initial-qa.json"
    command = [str(PYTHON), str(worker), "--case-id", cid, "--definition", str(xml), "--gencase-receipt", str(gencase_receipt), "--prepared-input-report", str(report), "--runtime-evidence", str(evidence), "--partvtk", str(PARTVTK), "--partvtk-output-dir", "{attempt_root}/partvtk", "--output", report_out]
    if observation.get("csv_path_recorded_by_root"):
        command += ["--csv", str(observation["csv_path_recorded_by_root"]), "--expected-csv-sha256", str(observation["csv_sha256_recorded_by_root"])]
    out = {
        "schema": "ds02.runner-request.v3", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE, "case_id": cid,
        "attempt_id": attempt, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "launch_owner": "root", "root_only": True,
        "execution_allowed": False, "launch_allowed": False, "disabled": True, "source_only": True, "future_hashes_null": True,
        "disabled_reason": "Enable only after Root reviews the failed/pending semantic-adapter-103 evidence and registers this corrected CSV parser. A pass is never inferred from the prepared count or old report.",
        "retry_of_attempt": str(root_request["attempt_id"]), "upstream_qa103_request": str(observation["request_path"]), "upstream_qa103_request_sha256": observation["request_sha256"],
        "upstream_qa103_observation": observation, "gencase_attempt_id": str(root_request["gencase_attempt_id"]), "depends_on_attempts": [str(root_request["gencase_attempt_id"])],
        "command": command, "cwd": str(HERE), "gencase_receipt": str(gencase_receipt), "gencase_receipt_sha256": root_request["gencase_receipt_sha256"],
        "gencase_receipt_semantics": "raw immutable Root353 execution receipt; missing dimension is supplied by prepared producer evidence only",
        "prepared_generated_xml": str(xml), "prepared_generated_xml_sha256": root_request["prepared_generated_xml_sha256"], "prepared_input_report": str(report), "prepared_input_report_sha256": root_request["prepared_input_report_sha256"],
        "runtime_evidence_sidecar": str(evidence), "runtime_evidence_sidecar_sha256": root_request["runtime_evidence_sidecar_sha256"], "prepared_flat_prefix": str(Path(str(report)).parent),
        "expected_dimension": 3, "expected_particles": int(root_request["expected_particles"]), "prepared_report_observed_counts": root_request["prepared_report_observed_counts"], "prepared_report_count_source": root_request["prepared_report_count_source"],
        "registered_existing_csv": recorded(str(observation["csv_path_recorded_by_root"]), observation["csv_sha256_recorded_by_root"], "Root379 actual report; source builder did not read or hash CSV") if observation.get("csv_path_recorded_by_root") else None,
        "registered_csv_parser_mode": "if present, audit existing Root379 CSV; otherwise invoke official PartVTK then parse its CSV",
        "parser_contract": str((HERE / "metadata/contracts/csv-parser-contract.json").resolve()), "parser_contract_sha256": sha(HERE / "metadata/contracts/csv-parser-contract.json"),
        "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_guard": strict_guard(native=False),
        "input_files": sorted(files), "input_sha256": {path: files[path] for path in sorted(files)},
        "future_input_files": [report_out, "{attempt_root}/execution-receipt.json", "{attempt_root}/partvtk/initial*.csv"],
        "future_input_sha256": {report_out: None, "{attempt_root}/execution-receipt.json": None, "{attempt_root}/partvtk/initial*.csv": None},
        "output_contract": {"actual_qa_report_sha256": None, "execution_receipt_sha256": None, "scientific_csv_sha256": None, "actual_counts": None, "qa_passed": None},
        "no_arrays_read": True, "no_jobs_started": True, "no_shared_registry_write": True, "no_science_payload_bound": False,
        "qualification_claim": "none", "production_claim": "none", "canonical_grant": False, "canonical_physical_binding_sha256": None,
    }
    path = HERE / "requests" / f"{cid}-initial-qa-csv-parser-repair-disabled.json"
    dump(path, out)
    return path, out


def native_request(case: Mapping[str, Any], root_request: Mapping[str, Any], observation: Mapping[str, Any], qa_path: Path, qa_req: Mapping[str, Any], manifest_row: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"])
    slug = cid.lower()
    base = load(Path(str(manifest_row["native_request"]["path"])))
    old_attempt = str(base["attempt_id"])
    attempt = f"root-stage1-f2-{slug}-full401-native-fresh104"
    files = closure_from_template(base)
    for path in [qa_path, HERE / "metadata/contracts/native-contract.json", HERE / "metadata/contracts/runtime-strict-guard.json", Path(str(observation["request_path"]))]:
        add_static(files, path)
    for item in (observation["report"], observation["receipt"]):
        if item.get("exists"):
            add_static(files, Path(str(item["path"])))
    command = [str(value).replace(old_attempt, attempt) for value in base["command"]]
    raw_root = Path(str(root_request["raw_output_root"])).resolve().parent
    native_receipt = raw_root / attempt / "execution-receipt.json"
    run_out = raw_root / attempt / "solver_output" / "Run.out"
    qa_report = raw_root / str(qa_req["attempt_id"]) / "actual-initial-qa.json"
    out = dict(base)
    out.update({
        "fresh_id": FRESH_ID, "attempt_id": attempt, "command": command, "cwd": str(Path(str(root_request["prepared_flat_prefix"])).resolve()),
        "depends_on_attempts": [str(root_request["gencase_attempt_id"]), str(root_request["attempt_id"]), str(qa_req["attempt_id"])],
        "upstream_qa103_attempt_id": str(root_request["attempt_id"]), "upstream_qa103_observation": observation,
        "initial_qa_attempt_id": str(qa_req["attempt_id"]), "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path),
        "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None, "initial_qa_gate": {"required_attempt": str(qa_req["attempt_id"]), "passed": None, "enable_only_after_actual_report_pass": True},
        "gencase_attempt_id": str(root_request["gencase_attempt_id"]), "gencase_prefix": str(base["gencase_prefix"]), "gencase_receipt": str(root_request["gencase_receipt"]), "gencase_receipt_sha256": root_request["gencase_receipt_sha256"],
        "gencase_semantic_dimension_source": "fresh102/root353 prepared producer evidence; raw receipt unchanged",
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None, "prepared_particle_count": int(root_request["expected_particles"]), "prepared_particle_counts": root_request["prepared_report_observed_counts"],
        "native_receipt": str(native_receipt), "native_receipt_sha256": None, "run_out": str(run_out), "run_out_sha256": None,
        "future_input_files": [str(native_receipt), str(run_out), str(native_receipt.parent / "solver_output" / "data")], "future_input_sha256": {str(native_receipt): None, str(run_out): None, str(native_receipt.parent / "solver_output" / "data"): None},
        "future_output_paths": {"execution_receipt": str(native_receipt), "run_out": str(run_out), "solver_output": str(native_receipt.parent / "solver_output"), "frames": None},
        "expected_output": {"frame_count": 401, "full_window_s": 4.0, "save_interval_s": 0.01, "solver_dimension": 3, "particle_counts": None, "native_output_hash": None},
        "output_contract": {"actual_frame_count": None, "actual_particle_counts": None, "execution_receipt_sha256": None, "run_out_sha256": None},
        "root230_dispatch": base.get("root230_dispatch"), "shared_gpu_lease_policy": {"profile": "Root230 live UUID lease at enable time", "resolved_gpu_uuid": None, "lease_handle": None, "source_agent_must_not_resolve": True},
        "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_guard": strict_guard(native=True),
        "input_files": sorted(files), "input_sha256": {path: files[path] for path in sorted(files)},
        "source_only": True, "execution_allowed": False, "launch_allowed": False, "disabled": True, "future_hashes_null": True,
        "disabled_reason": "Enable only after the fresh104 CSV parser worker produces an actual QA pass; Root230 must resolve a live UUID lease at enable time. The four failed semantic-103 reports remain negative evidence.",
        "canonical_physical_binding_sha256": None, "canonical_grant": False, "production_claim": "none", "qualification_claim": "none",
    })
    path = HERE / "requests" / f"{cid}-native401-disabled.json"
    dump(path, out)
    return path, out


def typed_request(case: Mapping[str, Any], root_request: Mapping[str, Any], observation: Mapping[str, Any], qa_path: Path, qa_req: Mapping[str, Any], native_path: Path, native_req: Mapping[str, Any], manifest_row: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"])
    slug = cid.lower()
    base_path = FRESH100 / "requests" / f"{cid}-typed-disabled.json"
    base = load(base_path)
    old_native = next((str(value) for value in base.get("depends_on_attempts", []) if "native" in str(value)), None)
    attempt = f"root-stage1-f2-{slug}-full401-typed-nvme-fresh104"
    files = closure_from_template(base)
    for path in [qa_path, native_path, HERE / "metadata/contracts/typed-contract.json", HERE / "metadata/contracts/runtime-strict-guard.json", Path(str(observation["request_path"]))]:
        add_static(files, path)
    for item in (observation["report"], observation["receipt"]):
        if item.get("exists"):
            add_static(files, Path(str(item["path"])))
    command = [str(value).replace(old_native, str(native_req["attempt_id"])) if old_native else str(value) for value in base["command"]]
    raw_root = Path(str(root_request["raw_output_root"])).resolve().parent
    typed_root = raw_root / attempt
    typed_receipt = typed_root / "execution-receipt.json"
    conversion = typed_root / "conversion-report.json"
    trajectory = typed_root / "trajectory.h5"
    native_receipt = Path(str(native_req["native_receipt"]))
    qa_report = raw_root / str(qa_req["attempt_id"]) / "actual-initial-qa.json"
    out = dict(base)
    scope = dict(base.get("physical_condition_hash_scope") or {})
    scope.update({"actual_converter_physical_condition_sha256": None, "canonical_physical_binding_sha256": None, "canonical_grant": False})
    out.update({
        "fresh_id": FRESH_ID, "attempt_id": attempt, "command": command, "depends_on_attempts": [str(root_request["gencase_attempt_id"]), str(qa_req["attempt_id"]), str(native_req["attempt_id"])],
        "upstream_qa103_attempt_id": str(root_request["attempt_id"]), "upstream_qa103_observation": observation,
        "initial_qa_attempt_id": str(qa_req["attempt_id"]), "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path), "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None,
        "native_attempt_id": str(native_req["attempt_id"]), "native_request": str(native_path), "native_request_sha256": sha(native_path), "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "gencase_attempt_id": str(root_request["gencase_attempt_id"]), "gencase_receipt": str(root_request["gencase_receipt"]), "gencase_receipt_sha256": root_request["gencase_receipt_sha256"],
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "conversion_report": str(conversion), "conversion_report_sha256": None, "trajectory_h5": str(trajectory), "trajectory_h5_sha256": None,
        "future_input_files": [str(native_receipt), str(conversion), str(trajectory), str(typed_receipt)], "future_input_sha256": {str(native_receipt): None, str(conversion): None, str(trajectory): None, str(typed_receipt): None},
        "future_outputs": {"execution_receipt": None, "execution_receipt_sha256": None, "conversion_report": None, "conversion_report_sha256": None, "trajectory_h5": None, "trajectory_h5_sha256": None},
        "physical_condition_hash_scope": scope, "physical_condition_sha256": scope.get("source_plan_physical_condition_sha256"), "source_plan_physical_condition_sha256": scope.get("source_plan_physical_condition_sha256"), "prospective_legacy_scope_sha256": scope.get("prospective_legacy_scope_sha256"),
        "producer_scope_schema": "legacy-owner-scope.v0", "canonical_physical_binding_sha256": None, "canonical_grant": False,
        "metadata_only_preflight_actual_conversion": False, "metadata_only_preflight": base.get("metadata_only_preflight"), "metadata_only_preflight_sha256": base.get("metadata_only_preflight_sha256"),
        "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_guard": strict_guard(native=False),
        "input_files": sorted(files), "input_sha256": {path: files[path] for path in sorted(files)},
        "source_only": True, "execution_allowed": False, "launch_allowed": False, "disabled": True, "future_hashes_null": True, "no_jobs_started": True, "no_shared_registry_write": True,
        "disabled_reason": "Enable only after fresh104 corrected QA passes and the Root230 native attempt is completed/0. Direct conversion remains legacy-owner scope; source and canonical scopes are retained separately and no canonical grant is inferred.",
    })
    path = HERE / "requests" / f"{cid}-typed-nvme-disabled.json"
    dump(path, out)
    return path, out


def main() -> int:
    m103 = load(M103)
    if m103.get("fresh_id") != "fresh103" or m103.get("case_count") != 16:
        raise SystemExit("fresh103 manifest must contain 16 cases")
    dump(HERE / "metadata/contracts/csv-parser-contract.json", {
        "schema": "ds02.f2.stage1.fresh104.csv-parser-contract.v1", "source_only": True, "future_root_worker_only": True,
        "producer": "official PartVTK only", "delimiter": ";", "header_detection": "scan preface until Pos.x + Type + Mk + Idp typed header",
        "units_row": "skip exactly one immediate row containing official unit markers and no numeric Idp/Type/Mk",
        "required_columns": ["Pos.x", "Pos.y", "Pos.z", "Vel.x", "Vel.y", "Vel.z", "Rhop", "Mass", "Idp", "Type", "Mk"],
        "checks": ["row count from data rows only", "finite numeric fields", "unique complete Idp", "Type/Mk partition", "positive Mass/Rhop", "3-D XML contract"],
        "existing_csv_mode": "Root may supply a registered existing CSV and its producer-recorded SHA; source builder never reads or hashes that CSV",
        "old_failure_preserved": "Root379 fresh103 reports remain immutable negative evidence",
    })
    dump(HERE / "metadata/contracts/native-contract.json", {"schema": "ds02.f2.stage1.fresh104.native-contract.v1", "dispatch": "Root230", "dimension": 3, "frames": 401, "window_s": 4.0, "save_interval_s": 0.01, "solver_options": "reuse fresh103 exact command; no added options", "prepared_prefix": "flat prepared prefix", "future_hashes_null": True, "source_only": True})
    dump(HERE / "metadata/contracts/typed-contract.json", {"schema": "ds02.f2.stage1.fresh104.typed-contract.v1", "worker": "fresh100 directconvert + NVME wrapper", "cpu_task_kind": "conversion", "cpu_threads": 2, "nvme_root": "/tmp/ds02-nvme-conversion", "nvme_staging_peak_limit_bytes": 25769803776, "legacy_scope_allowed": True, "canonical_grant": False, "source_scope_separate": True, "future_hashes_null": True, "source_only": True})
    dump(HERE / "metadata/contracts/runtime-strict-guard.json", {"schema": "ds02.f2.stage1.fresh104.runtime-strict-guard.v1", "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_dispatch": str(STRICT), "runtime": str(RUNTIME), "root230": str(ROOT230), "root230_launch": str(ROOT230LAUNCH), "source_only": True, "no_shared_state_write": True, "no_science_payload_read_by_builder": True})

    rows = {str(row["case_id"]): row for row in m103["cases"]}
    generated: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    pending = 0
    for cid in sorted(rows):
        row = rows[cid]
        root_path = ROOT378 / f"{cid}-initial-qa-request.json"
        root_req = load(root_path)
        root_req["_request_path"] = str(root_path.resolve())
        root_req["_request_sha256"] = sha(root_path)
        observation = actual_qa_observation(root_req)
        if observation["report"] ["exists"]:
            observed.append({"case_id": cid, **observation})
        else:
            pending += 1
        qa_path, qa_req = qa_retry_request(row, root_req, observation, row)
        native_path, native_req = native_request(row, root_req, observation, qa_path, qa_req, row)
        typed_path, typed_req = typed_request(row, root_req, observation, qa_path, qa_req, native_path, native_req, row)
        generated.append({
            "case_id": cid, "physical_case_id": row.get("physical_case_id"), "root378_request": bind(root_path), "root378_attempt_id": root_req["attempt_id"],
            "root378_actual_qa": observation, "csv_parser_repair_request": bind(qa_path), "native_request": bind(native_path), "typed_request": bind(typed_path),
            "prepared_gencase_dimension": row.get("prepared_gencase_dimension"), "prepared_gencase_particle_count": row.get("prepared_gencase_particle_count"), "prepared_gencase_particle_counts": row.get("prepared_gencase_particle_counts"),
            "actual_native_receipt": None, "actual_typed_receipt": None, "actual_h5_sha256": None, "canonical_physical_binding_sha256": None, "canonical_grant": False,
            "independent_case_count_increment": 0,
        })
    dump(HERE / "evidence/fresh103-qa-outcomes.json", {"schema": "ds02.f2.stage1.fresh104.fresh103-qa-outcomes.v1", "root378_handoff": str(ROOT378), "observed_reports": observed, "observed_report_count": len(observed), "observed_pass_count": sum(1 for item in observed if item.get("passed") is True), "pending_report_count": pending, "four_root379_failures_preserved": all(item.get("report_status") == "fail" and item.get("receipt_returncode") == 2 for item in observed), "csv_paths_read_or_hashed_by_source_builder": False, "source_builder_science_payload_reads": []})
    dump(HERE / "evidence/source-entry-audit.json", {"schema": "ds02.f2.stage1.fresh104.source-entry-audit.v1", "case_count": 16, "observed_root379_reports": len(observed), "pending_root379_reports": pending, "qa_parser_repair_requests": 16, "native_requests": 16, "typed_requests": 16, "all_requests_disabled": True, "future_hashes_null": True, "qa_pass_claim": False, "native_claim": False, "typed_claim": False, "canonical_grant": False, "independent_case_count_increment": 0, "science_payloads_read_or_hashed": []})
    manifest = {"schema": "ds02.f2.stage1.fresh104.actual-qa-native-typed-adapter-manifest.v1", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE, "source_only": True, "execution_allowed": False, "case_count": 16, "cases": generated, "observed_qa_reports": len(observed), "observed_qa_passes": sum(1 for item in observed if item.get("passed") is True), "pending_qa_reports": pending, "four_root379_failures_preserved": True, "parser_repair_worker": bind(HERE / "workers/fresh104_initial_qa_csv_parser.py"), "validator": bind(HERE / "workers/fresh104_source_contract_validator.py"), "builder": bind(HERE / "build_fresh104.py"), "readme": bind(HERE / "README.md"), "contracts": {"csv": bind(HERE / "metadata/contracts/csv-parser-contract.json"), "native": bind(HERE / "metadata/contracts/native-contract.json"), "typed": bind(HERE / "metadata/contracts/typed-contract.json"), "strict": bind(HERE / "metadata/contracts/runtime-strict-guard.json")}, "logical_strict_guard_digest": LOGICAL_GUARD, "actual_strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "all_requests_disabled": True, "future_hashes_null": True, "no_jobs_started": True, "no_science_arrays_read": True, "no_shared_registry_write": True, "independent_case_count_increment": 0}
    dump(HERE / "F2_STAGE1_FRESH104_ACTUAL_QA_NATIVE_TYPED_ADAPTER_MANIFEST.json", manifest)
    print(json.dumps({"schema": "ds02.f2.stage1.fresh104.build-result.v1", "package": str(HERE), "case_count": 16, "observed_qa_reports": len(observed), "observed_qa_passes": 0, "pending_qa_reports": pending, "qa_parser_repair_requests": 16, "native_requests": 16, "typed_requests": 16, "future_hashes_null": True, "source_only": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
