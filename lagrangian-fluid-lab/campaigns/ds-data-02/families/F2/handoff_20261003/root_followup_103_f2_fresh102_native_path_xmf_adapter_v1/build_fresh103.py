#!/usr/bin/env python3
"""Build the F2 fresh103 metadata adapter.

Fresh102 recorded real GenCase prepared reports, but the first Root-owned QA
attempts exposed a contract mismatch: the raw execution receipt does not carry
``solver_dimension_from_gencase`` even though the fresh102 producer sidecar
records the completed 3-D prepared evidence.  This package keeps that receipt
immutable, supplies a disabled QA wrapper that derives a semantic receipt only
at execution time, and rebinds the downstream native/XMF/render requests.

This builder reads JSON, XML and source text metadata only.  It does not open
or hash motion DAT, BI4, H5, CSV, VTK, XMF or any other scientific payload.
Recorded hashes for those inputs are carried forward from the Root-owned
fresh102 request as provenance.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
BASE = Path("/home/jade/Projects/DualSPHysics").resolve()
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
HERE = Path(__file__).resolve().parent
HANDOFF = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003"
FRESH100 = HANDOFF / "root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1"
FRESH101 = HANDOFF / "root_followup_101_f2_stage1_typed401_xmf_render_v1"
FRESH102 = HANDOFF / "root_followup_102_f2_gencase_runtime_evidence_qa_v1"
M101 = FRESH101 / "F2_STAGE1_FRESH101_TYPED401_XMF_RENDER_MANIFEST.json"
M102 = FRESH102 / "F2_STAGE1_FRESH102_GENCASE_RUNTIME_EVIDENCE_QA_MANIFEST.json"
LAB = INTEGRATION / "lagrangian-fluid-lab"
PYTHON = LAB / ".venv/bin/python"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
ROOT142D = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142"
ROOT142 = ROOT142D / "root_home_floor_inventory_policy.py"
ROOT230D = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230 = ROOT230D / "root_native_home_floor_inventory_policy.py"
ROOT230LAUNCH = ROOT230D / "launch.py"
ROOT230CONTRACT = ROOT230D / "source-policy-contract.json"
GPU_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
PARTVTK = BASE / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
SCOPE = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
FRESH_ID = "fresh103"
LOGICAL_GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
STRICT_DISPATCH_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
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
    "max_wall_seconds": 5400,
}


def sha(path: Path) -> str:
    """Hash only source/metadata files; scientific payloads are refused."""
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"non-static/scientific path refused: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
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
    for raw in paths:
        path = Path(raw).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def static_files(*paths: Path) -> list[Path]:
    result = unique(list(paths))
    for path in result:
        sha(path)
    return result


def bind(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "exists": True}


def recorded_bind(path: str, digest: str, *, source: str) -> dict[str, Any]:
    """Carry a Root producer digest without opening the payload here."""
    return {"path": str(Path(path).resolve()), "sha256": digest, "read_or_hashed_here": False, "digest_source": source}


def clone_recorded_input(template: Mapping[str, Any], path: str) -> tuple[str, str]:
    key = str(Path(path).resolve())
    digest = (template.get("input_sha256") or {}).get(key)
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"missing producer-recorded input digest: {key}")
    return key, digest


def add_static_input(files: dict[str, str], path: Path) -> None:
    path = Path(path).resolve()
    files[str(path)] = sha(path)


def add_recorded_input(files: dict[str, str], template: Mapping[str, Any], path: str) -> None:
    key, digest = clone_recorded_input(template, path)
    files[key] = digest


def closure_from_template(template: Mapping[str, Any]) -> dict[str, str]:
    """Preserve existing raw/binary registrations; rehash only safe metadata."""
    output: dict[str, str] = {}
    for raw_path, expected in (template.get("input_sha256") or {}).items():
        path = Path(raw_path).resolve()
        if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f"invalid recorded input digest: {path}")
            output[str(path)] = expected
        else:
            actual = sha(path)
            if actual != expected:
                raise ValueError(f"metadata input changed: {path}")
            output[str(path)] = actual
    return output


def future_map(paths: list[Path]) -> tuple[list[str], dict[str, None]]:
    values = [str(Path(path).resolve()) for path in unique(paths)]
    return values, {value: None for value in values}


def strict_guard(*, native: bool) -> dict[str, Any]:
    root_policy = ROOT230 if native else ROOT142
    return {
        "strict_guard_digest": LOGICAL_GUARD,
        "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA,
        "source_only": True,
        "worktree_root": str(INFRA),
        "input_closure": "set(input_files)==set(input_sha256); producer-recorded raw inputs may remain unread; future outputs remain null",
        "runtime_v2": {"path": str(RUNTIME), "sha256": sha(RUNTIME)},
        "strict_dispatch": {"path": str(STRICT), "sha256": sha(STRICT)},
        "root142_inventory_policy": {"path": str(ROOT142), "sha256": sha(ROOT142)},
        "root230_inventory_policy": {"path": str(ROOT230), "sha256": sha(ROOT230)},
        "root_inventory_policy": {"path": str(root_policy), "sha256": sha(root_policy)},
        "resource_window": {"path": str(RESOURCE), "sha256": sha(RESOURCE)},
    }


def verify_static_xml(path: Path, case_id: str) -> None:
    if ET.parse(path).getroot().tag != "case":
        raise ValueError(f"prepared XML root mismatch: {case_id}")


def actual_evidence(row102: Mapping[str, Any], m102: Mapping[str, Any]) -> dict[str, Any]:
    cid = str(row102["case_id"])
    side_path = Path(row102["runtime_evidence_sidecar"]["path"]).resolve()
    side = load(side_path)
    receipt = side["raw_gencase_receipt"]
    report = side["prepared_input_report"]
    xml = side["prepared_generated_xml"]
    receipt_path = Path(str(receipt["path"])).resolve()
    report_path = Path(str(report["path"])).resolve()
    xml_path = Path(str(xml["path"])).resolve()
    receipt_sha = sha(receipt_path)
    report_sha = sha(report_path)
    xml_sha = sha(xml_path)
    if receipt_sha != receipt["sha256"] or report_sha != report["sha256"] or xml_sha != xml["sha256"]:
        raise ValueError(f"fresh102 recorded digest does not close: {cid}")
    if side.get("source_only") is not True or side.get("execution_allowed") is not False:
        raise ValueError(f"fresh102 sidecar is not source-only: {cid}")
    if side.get("contract_checks", {}).get("root353_solver_dimension_three") is not True:
        raise ValueError(f"fresh102 3-D producer sidecar check missing: {cid}")
    if side.get("raw_gencase_receipt", {}).get("raw_receipt_immutable") is not True:
        raise ValueError(f"fresh102 raw receipt immutability missing: {cid}")
    counts = report.get("generated_xml_particle_counts")
    total = report.get("actual_total_particles")
    if not isinstance(counts, dict) or any(not isinstance(counts.get(k), int) or counts[k] < 0 for k in COUNT_KEYS):
        raise ValueError(f"fresh102 prepared counts missing: {cid}")
    if not isinstance(total, int) or total <= 0 or sum(counts[k] for k in COUNT_KEYS) != total:
        raise ValueError(f"fresh102 prepared count closure failed: {cid}")
    if report.get("bi4_read_or_rehashed_here") is not False:
        raise ValueError(f"fresh102 BI4 source-side read claim changed: {cid}")
    verify_static_xml(xml_path, cid)

    # A completed fresh102 QA attempt may already exist.  It is historical
    # evidence only; its result is never treated as a pass or as a producer.
    native_row = row102["native_request"]
    native_req = load(Path(native_row["path"]))
    qa_attempt = str(row102["initial_qa_request"]["path"])
    qa_req = load(Path(qa_attempt))
    qa_output = Path(str(qa_req["raw_output_root"])) / str(qa_req["attempt_id"]) / "actual-initial-qa.json"
    observed = None
    if qa_output.is_file():
        q = load(qa_output)
        observed = {
            "path": str(qa_output.resolve()), "sha256": sha(qa_output),
            "status": q.get("status"), "returncode_semantics": "historical fresh102 QA output; not reused as pass",
            "checks": q.get("checks", {}), "gencase_receipt": q.get("gencase_receipt", {}),
        }
    raw_receipt_doc = load(receipt_path)
    return {
        "case_id": cid, "physical_case_id": side.get("physical_case_id"), "side_path": side_path, "side": side,
        "receipt_path": receipt_path, "receipt_sha": receipt_sha, "receipt": raw_receipt_doc,
        "report_path": report_path, "report_sha": report_sha, "report": report,
        "xml_path": xml_path, "xml_sha": xml_sha,
        "counts": counts, "total": total, "observed_qa": observed,
        "qa_req_path": Path(qa_attempt).resolve(), "qa_req": qa_req,
        "native_req_path": Path(native_row["path"]).resolve(), "native_req": native_req,
        "gencase_attempt": str(row102["gencase_attempt_id"]),
    }


def static_input_set(case: Mapping[str, Any], *, worker: Path, extra: list[Path]) -> dict[str, str]:
    """Use fresh102 closure and add only metadata/source files for fresh103."""
    files = closure_from_template(case["qa_req"])
    add_static_input(files, worker)
    for path in extra:
        add_static_input(files, path)
    return files


def scope_from_old(old_binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_plan_physical_condition_sha256": old_binding["source_plan_physical_condition_sha256"],
        "prospective_legacy_scope_sha256": old_binding["physical_condition_sha256"],
        "actual_converter_physical_condition_sha256": None,
        "canonical_physical_binding_sha256": None,
        "canonical_grant": False,
        "producer_scope_schema": "legacy-owner-scope.v0",
        "scope_separation": "source plan, prospective legacy owner scope, actual converter scope, canonical scope and trajectory H5 remain distinct",
    }


def qa_request(case: Mapping[str, Any], old_binding: Mapping[str, Any], xmf_contract: Path) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"])
    old = dict(case["qa_req"])
    slug = cid.lower()
    attempt = f"root-stage1-f2-{slug}-prepared-report-qa-semantic-adapter-103"
    worker = HERE / "workers/fresh103_initial_qa_adapter.py"
    audit = FRESH100 / "workers/f2_prepared_report_contract_audit.py"
    inner = FRESH100 / "workers/f2_stage1_initial_qa_worker.py"
    report_out = f"{{attempt_root}}/prepared-report-contract.json"
    qa_out = f"{{attempt_root}}/actual-initial-qa.json"
    raw_template = case["qa_req"]
    files = static_input_set(case, worker=worker, extra=[audit, inner, xmf_contract])
    add_static_input(files, case["side_path"])
    # The request closure must bind the actual JSON/XML producer outputs.  Raw
    # BI4/DAT and the official PartVTK binary remain recorded parent inputs.
    for p in (case["receipt_path"], case["report_path"], case["xml_path"]):
        add_static_input(files, p)
    guard = strict_guard(native=False)
    out = dict(old)
    out.update({
        "fresh_id": FRESH_ID,
        "attempt_id": attempt,
        "depends_on_attempt": case["gencase_attempt"],
        "depends_on_attempts": [case["gencase_attempt"]],
        "command": [str(PYTHON), str(worker), "--case-id", cid,
                     "--definition", str(case["xml_path"]),
                     "--gencase-receipt", str(case["receipt_path"]),
                     "--prepared-input-report", str(case["report_path"]),
                     "--runtime-evidence", str(case["side_path"]),
                     "--prepared-report-output", report_out,
                     "--partvtk", str(PARTVTK),
                     "--partvtk-output-dir", "{attempt_root}/partvtk",
                     "--output", qa_out],
        "cwd": str(HERE),
        "gencase_receipt": str(case["receipt_path"]),
        "gencase_receipt_sha256": case["receipt_sha"],
        "gencase_receipt_semantics": "raw immutable execution receipt; missing dimension field is supplied only by runtime semantic adapter",
        "runtime_evidence_sidecar": str(case["side_path"]),
        "runtime_evidence_sidecar_sha256": sha(case["side_path"]),
        "prepared_generated_xml": str(case["xml_path"]),
        "prepared_generated_xml_sha256": case["xml_sha"],
        "prepared_input_report": str(case["report_path"]),
        "prepared_input_report_sha256": case["report_sha"],
        "prepared_flat_prefix": str(case["report_path"].parent),
        "raw_output_root": case["receipt"].get("output_root"),
        "semantic_receipt": {"path": None, "sha256": None, "created_only_in_attempt_root": True, "raw_receipt_rewritten": False},
        "observed_prior_qa": case["observed_qa"],
        "strict_guard_digest": LOGICAL_GUARD,
        "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA,
        "strict_guard": guard,
        "input_files": sorted(files),
        "input_sha256": {path: files[path] for path in sorted(files)},
        "future_input_files": [qa_out, report_out, "{attempt_root}/partvtk/initial*.csv"],
        "future_input_sha256": {qa_out: None, report_out: None, "{attempt_root}/partvtk/initial*.csv": None},
        "output_contract": {
            "prepared_report_contract_sha256": None,
            "actual_qa_report_sha256": None,
            "actual_counts": None,
            "scientific_csv_sha256": None,
            "raw_gencase_receipt_sha256": case["receipt_sha"],
            "semantic_gencase_receipt_sha256": None,
        },
        "expected_dimension": 3,
        "expected_particles": case["total"],
        "prepared_report_observed_counts": case["counts"],
        "prepared_report_count_source": "actual Root353 prepared-input-report via fresh102 sidecar; not raw receipt partition fields",
        "source_only": True,
        "no_science_payload_bound": False,
        "disabled_reason": "Fresh102 raw GenCase receipt is immutable and lacks solver_dimension_from_gencase; enable only after Root reviews the semantic adapter and its actual PartVTK result.",
    })
    path = HERE / "requests" / f"{cid}-initial-qa-semantic-adapter-disabled.json"
    dump(path, out)
    return path, out


def native_request(case: Mapping[str, Any], qa_path: Path, qa_req: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"])
    out = dict(case["native_req"])
    slug = cid.lower()
    attempt = f"root-stage1-f2-{slug}-full401-native-fresh103"
    files = closure_from_template(case["native_req"])
    add_static_input(files, qa_path)
    add_static_input(files, HERE / "metadata/contracts/native-path-contract.json")
    guard = strict_guard(native=True)
    out.update({
        "fresh_id": FRESH_ID,
        "attempt_id": attempt,
        "depends_on_attempts": [case["gencase_attempt"], qa_req["attempt_id"]],
        "initial_qa_attempt_id": qa_req["attempt_id"],
        "initial_qa_request": str(qa_path),
        "initial_qa_request_sha256": sha(qa_path),
        "initial_qa_report": f"{{qa_attempt_root}}/actual-initial-qa.json",
        "initial_qa_report_sha256": None,
        "runtime_evidence_sidecar": str(case["side_path"]),
        "runtime_evidence_sidecar_sha256": sha(case["side_path"]),
        "gencase_receipt": str(case["receipt_path"]),
        "gencase_receipt_sha256": case["receipt_sha"],
        "gencase_semantic_dimension_source": "fresh102 prepared evidence sidecar; raw receipt remains immutable",
        "strict_guard_digest": LOGICAL_GUARD,
        "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA,
        "strict_guard": guard,
        "input_files": sorted(files),
        "input_sha256": {path: files[path] for path in sorted(files)},
        "future_input_files": ["{attempt_root}/execution-receipt.json", "{attempt_root}/solver_output/Run.out", "{attempt_root}/solver_output/data"],
        "future_input_sha256": {"{attempt_root}/execution-receipt.json": None, "{attempt_root}/solver_output/Run.out": None, "{attempt_root}/solver_output/data": None},
        "expected_output": {"frame_count": 401, "full_window_s": 4.0, "save_interval_s": 0.01, "solver_dimension": 3, "particle_counts": None, "native_output_hash": None},
        "output_contract": {"actual_frame_count": None, "actual_particle_counts": None, "execution_receipt_sha256": None, "run_out_sha256": None},
        "expected_dimension": 3,
        "expected_native_frames": 401,
        "expected_particles": None,
        "prepared_particle_count": case["total"],
        "prepared_particle_counts": case["counts"],
        "source_only": True,
        "disabled_reason": "Enable only after the fresh103 semantic QA adapter produces a real pass; fresh102 QA attempts are retained as historical negative evidence.",
    })
    path = HERE / "requests" / f"{cid}-native-disabled.json"
    dump(path, out)
    return path, out


def xmf_binding(case: Mapping[str, Any], qa_path: Path, native_path: Path, qa_req: Mapping[str, Any], native_req: Mapping[str, Any], old_binding: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"])
    slug = cid.lower()
    raw_root = Path(str(native_req["raw_output_root"])).resolve()
    typed_template = Path(str(old_binding["typed_binding"])).resolve()
    typed_template_sha = sha(typed_template)
    typed_attempt = f"root-stage1-f2-{slug}-full401-typed-fresh103"
    typed_receipt = raw_root / typed_attempt / "execution-receipt.json"
    conversion_report = raw_root / typed_attempt / "conversion-report.json"
    trajectory_h5 = raw_root / typed_attempt / "trajectory.h5"
    native_receipt = raw_root / str(native_req["attempt_id"]) / "execution-receipt.json"
    qa_report = raw_root / str(qa_req["attempt_id"]) / "actual-initial-qa.json"
    gencase = case["receipt_path"]
    xmf_case = raw_root / f"root-stage1-f2-{slug}-full401-xmf-fresh103" / "xdmf" / "case.xmf"
    xmf_manifest = xmf_case.parent / "manifest.json"
    path = HERE / "xmf/bindings" / f"{cid}.xmf-binding.json"
    scope = scope_from_old(old_binding)
    contract = {"dimension": 3, "frames": 401, "particle_counts": None, "type_partition": None, "key": "(Zone,Idp)", "counts_source": "actual conversion-report only; prepared GenCase count is upstream evidence, not typed count"}
    value = {
        "schema": "ds02.f2.stage1.fresh103.xmf-binding.v1", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE,
        "case_id": cid, "physical_case_id": case["physical_case_id"], "producer_scope_schema": "legacy-owner-scope.v0",
        "semantic_binding_status": "legacy-owner scope only; fresh102 prepared evidence bound; native/typed/XMF not actual",
        **scope,
        "owner_metadata": old_binding["owner_metadata"], "owner_metadata_sha256": old_binding["owner_metadata_sha256"],
        "source_definition": old_binding["source_definition"], "source_definition_sha256": old_binding["source_definition_sha256"],
        "source_metadata": old_binding["source_metadata"], "source_metadata_sha256": old_binding["source_metadata_sha256"],
        "typed_binding_template": str(typed_template), "typed_binding_template_sha256": typed_template_sha,
        "typed_attempt_id": typed_attempt, "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None,
        "conversion_report": str(conversion_report), "conversion_report_sha256": None, "trajectory_h5": str(trajectory_h5), "trajectory_h5_sha256": None,
        "native_request": str(native_path), "native_request_sha256": sha(native_path), "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path), "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None,
        "gencase_receipt": str(gencase), "gencase_receipt_sha256": case["receipt_sha"],
        "runtime_evidence_sidecar": str(case["side_path"]), "runtime_evidence_sidecar_sha256": sha(case["side_path"]),
        "prepared_input_report": str(case["report_path"]), "prepared_input_report_sha256": case["report_sha"],
        "prepared_generated_xml": str(case["xml_path"]), "prepared_generated_xml_sha256": case["xml_sha"],
        "prepared_gencase_particle_count": case["total"], "prepared_gencase_particle_counts": case["counts"],
        "prepared_gencase_dimension": 3, "prepared_gencase_dimension_source": "fresh102 producer sidecar contract check; raw receipt unchanged",
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "physical_window_s": [0.0, 4.0], "save_interval_s": 0.01, "all_native_frames_required": True,
        "expected_native_contract": contract,
        "xmf_shape_contract": {"dynamic_vector_dimensions": "{actual_particles} 3", "dynamic_scalar_dimensions": "{actual_particles}", "particle_axis_preserved": True, "counts_from_actual_conversion_report": True, "n_times_3_required": True},
        "future_hashes_null": True, "source_only": True, "disabled": True, "execution_allowed": False, "launch_allowed": False,
        "independent_case_increment": 0, "visual_status": "pending actual native, typed conversion, XMF and Root023 review", "numerical_precision_status": "not accepted",
        "output_dir_contract": "{attempt_root}/xdmf must start empty; receipt/stdout remain in attempt root",
        "future_outputs": {"case_xmf": None, "case_xmf_sha256": None, "manifest": None, "manifest_sha256": None, "execution_receipt": None, "execution_receipt_sha256": None},
        "bound_metadata_sha256": {},
    }
    common = [old_binding["owner_metadata"], old_binding["source_metadata"], old_binding["source_definition"], typed_template, qa_path, native_path, case["side_path"], case["receipt_path"], case["report_path"], case["xml_path"], FRESH101 / "metadata/contracts/xmf-contract.json", FRESH101 / "metadata/contracts/typed-conversion-contract.json", FRESH101 / "metadata/contracts/runtime-strict-guard.json", FRESH101 / "metadata/base-binary-contract.json", HERE / "metadata/contracts/native-path-contract.json", HERE / "workers/export_xmf.py", RUNTIME, STRICT, ROOT142, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT, GPU_POLICY, RESOURCE]
    value["bound_metadata_sha256"] = {str(p.resolve()): sha(p) for p in static_files(*common)}
    dump(path, value)
    return path, value


def xmf_request(case: Mapping[str, Any], qa_path: Path, native_path: Path, qa_req: Mapping[str, Any], native_req: Mapping[str, Any], binding_path: Path, old_request: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"]); slug = cid.lower(); raw_root = Path(str(native_req["raw_output_root"])).resolve()
    attempt = f"root-stage1-f2-{slug}-full401-xmf-fresh103"
    typed_attempt = f"root-stage1-f2-{slug}-full401-typed-fresh103"
    native_attempt = str(native_req["attempt_id"]); qa_attempt = str(qa_req["attempt_id"])
    worker = FRESH101 / "workers/export_xmf.py"
    files = closure_from_template(old_request)
    # Keep old recorded raw/binary inputs, but rebind every metadata producer.
    for path in (binding_path, qa_path, native_path, case["side_path"], case["receipt_path"], case["report_path"], case["xml_path"], HERE / "metadata/contracts/native-path-contract.json"):
        add_static_input(files, path)
    guard = strict_guard(native=False)
    xmf_case = raw_root / attempt / "xdmf" / "case.xmf"; xmf_manifest = xmf_case.parent / "manifest.json"
    typed_receipt = raw_root / typed_attempt / "execution-receipt.json"; conversion = raw_root / typed_attempt / "conversion-report.json"; h5 = raw_root / typed_attempt / "trajectory.h5"
    native_receipt = raw_root / native_attempt / "execution-receipt.json"; qa_report = raw_root / qa_attempt / "actual-initial-qa.json"
    future_files, future_sha = future_map([typed_receipt, conversion, h5, native_receipt, qa_report, xmf_case, xmf_manifest, raw_root / native_attempt / "solver_output" / "Run.out"])
    old_binding = load(FRESH101 / "xmf/bindings" / f"{cid}.xmf-binding.json")
    scope = scope_from_old(old_binding)
    contract = {"dimension": 3, "frames": 401, "particle_counts": None, "type_partition": None, "key": "(Zone,Idp)", "counts_source": "actual conversion-report only"}
    out = dict(old_request)
    out.update({
        "fresh_id": FRESH_ID, "attempt_id": attempt, "depends_on_attempts": [case["gencase_attempt"], qa_attempt, native_attempt, typed_attempt],
        "command": [str(PYTHON), str(worker), "--binding", str(binding_path), "--output-dir", "{attempt_root}/xdmf"], "cwd": str(HERE),
        "typed_request_required_before_xmf": True, "typed_request_template": old_binding["typed_binding"], "typed_request_template_sha256": sha(Path(old_binding["typed_binding"])),
        "typed_attempt_id": typed_attempt, "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None, "conversion_report": str(conversion), "conversion_report_sha256": None, "trajectory_h5": str(h5), "trajectory_h5_sha256": None,
        "native_request": str(native_path), "native_request_sha256": sha(native_path), "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path), "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None,
        "gencase_receipt": str(case["receipt_path"]), "gencase_receipt_sha256": case["receipt_sha"], "runtime_evidence_sidecar": str(case["side_path"]), "runtime_evidence_sidecar_sha256": sha(case["side_path"]),
        "prepared_input_report": str(case["report_path"]), "prepared_input_report_sha256": case["report_sha"], "prepared_generated_xml": str(case["xml_path"]), "prepared_generated_xml_sha256": case["xml_sha"],
        "prepared_gencase_particle_count": case["total"], "prepared_gencase_particle_counts": case["counts"], "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None, "expected_native_contract": contract,
        "physical_condition_hash_scope": scope, "physical_condition_sha256": scope["prospective_legacy_scope_sha256"], "prospective_legacy_scope_sha256": scope["prospective_legacy_scope_sha256"], "source_plan_physical_condition_sha256": scope["source_plan_physical_condition_sha256"],
        "canonical_physical_binding_sha256": None, "canonical_grant": False, "producer_scope_schema": "legacy-owner-scope.v0",
        "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_guard": guard,
        "input_files": sorted(files), "input_sha256": {p: files[p] for p in sorted(files)}, "future_input_files": future_files, "future_input_sha256": future_sha,
        "output_contract": {"case_xmf_sha256": None, "manifest_sha256": None, "actual_frame_count": None, "actual_particle_counts": None, "trajectory_h5_sha256": None},
        "future_outputs": {"case_xmf": None, "case_xmf_sha256": None, "manifest": None, "manifest_sha256": None, "execution_receipt": None, "execution_receipt_sha256": None},
        "source_only": True, "disabled": True, "execution_allowed": False, "launch_allowed": False, "future_hashes_null": True,
        "disabled_reason": "Enable only after fresh103 semantic QA pass, native401 completed/0, and a separately completed typed conversion; no future payload hash is inferred from the prepared GenCase count.",
    })
    path = HERE / "xmf/requests" / f"{cid}-xmf-disabled.json"; dump(path, out); return path, out


def render_binding(case: Mapping[str, Any], qa_path: Path, native_path: Path, xmf_path: Path, xmf_binding_path: Path, qa_req: Mapping[str, Any], native_req: Mapping[str, Any], old_binding: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"]); slug = cid.lower(); raw_root = Path(str(native_req["raw_output_root"])).resolve(); attempt = f"root-stage1-f2-{slug}-full401-root023-render-fresh103"
    typed_attempt = f"root-stage1-f2-{slug}-full401-typed-fresh103"; xmf_attempt = f"root-stage1-f2-{slug}-full401-xmf-fresh103"
    typed_receipt = raw_root / typed_attempt / "execution-receipt.json"; conversion = raw_root / typed_attempt / "conversion-report.json"; h5 = raw_root / typed_attempt / "trajectory.h5"; native_receipt = raw_root / str(native_req["attempt_id"]) / "execution-receipt.json"; xmf_case = raw_root / xmf_attempt / "xdmf" / "case.xmf"; xmf_manifest = xmf_case.parent / "manifest.json"
    scope = scope_from_old(old_binding)
    path = HERE / "render/bindings" / f"{cid}.render-binding.json"
    contract = {"dimension": 3, "frames": 401, "particle_counts": None, "type_partition": None, "key": "(Zone,Idp)", "counts_source": "actual XMF manifest/conversion report only"}
    camera = {"bounds_source": "Root023 scans every native valid position across every saved frame", "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False, "fixed_camera_override": False, "native_geometry_retained": True}
    value = {"schema": "ds02.f2.stage1.fresh103.render-binding.v1", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE, "case_id": cid, "physical_case_id": case["physical_case_id"], "producer_scope_schema": "legacy-owner-scope.v0", "semantic_binding_status": "legacy-owner scope only; canonical physical binding not granted", **scope, "owner_metadata": old_binding["owner_metadata"], "owner_metadata_sha256": old_binding["owner_metadata_sha256"], "source_definition": old_binding["source_definition"], "source_definition_sha256": old_binding["source_definition_sha256"], "source_metadata": old_binding["source_metadata"], "source_metadata_sha256": old_binding["source_metadata_sha256"], "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None, "conversion_report": str(conversion), "conversion_report_sha256": None, "trajectory_h5": str(h5), "trajectory_h5_sha256": None, "native_request": str(native_path), "native_request_sha256": sha(native_path), "native_receipt": str(native_receipt), "native_receipt_sha256": None, "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path), "initial_qa_report": str(raw_root / str(qa_req["attempt_id"]) / "actual-initial-qa.json"), "initial_qa_report_sha256": None, "xmf_request": str(xmf_path), "xmf_request_sha256": sha(xmf_path), "xmf_binding": str(xmf_binding_path), "xmf_binding_sha256": sha(xmf_binding_path), "xmf_case": str(xmf_case), "xmf_case_sha256": None, "xmf_manifest": str(xmf_manifest), "xmf_manifest_sha256": None, "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None, "prepared_gencase_particle_count": case["total"], "prepared_gencase_particle_counts": case["counts"], "expected_native_contract": contract, "physical_window_s": [0.0, 4.0], "save_interval_s": 0.01, "camera_policy": camera, "contact_pages": 17, "future_hashes_null": True, "source_only": True, "disabled": True, "execution_allowed": False, "launch_allowed": False, "independent_case_increment": 0, "visual_status": "pending actual XMF and Root023 full401 render review", "numerical_precision_status": "not accepted", "future_outputs": {"execution_receipt": None, "execution_receipt_sha256": None, "report": None, "report_sha256": None, "frames_dir": None, "frames_sha256": None, "contact_sheets": None, "gif": None, "gif_sha256": None, "pvsm": None, "pvsm_sha256": None}, "bound_metadata_sha256": {}}
    common = [old_binding["owner_metadata"], old_binding["source_metadata"], old_binding["source_definition"], qa_path, native_path, xmf_path, xmf_binding_path, case["side_path"], case["receipt_path"], case["report_path"], case["xml_path"], FRESH101 / "metadata/contracts/render-contract.json", FRESH101 / "metadata/contracts/xmf-contract.json", FRESH101 / "metadata/contracts/typed-conversion-contract.json", FRESH101 / "metadata/contracts/runtime-strict-guard.json", FRESH101 / "metadata/base-binary-contract.json", HERE / "metadata/contracts/native-path-contract.json", FRESH101 / "workers/render_native023.py", RUNTIME, STRICT, ROOT142, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT, GPU_POLICY, RESOURCE]
    value["bound_metadata_sha256"] = {str(p.resolve()): sha(p) for p in static_files(*common)}
    dump(path, value); return path, value


def render_request(case: Mapping[str, Any], qa_path: Path, native_path: Path, xmf_path: Path, xmf_binding_path: Path, qa_req: Mapping[str, Any], native_req: Mapping[str, Any], render_binding_path: Path, old_request: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case["case_id"]); slug = cid.lower(); raw_root = Path(str(native_req["raw_output_root"])).resolve(); attempt = f"root-stage1-f2-{slug}-full401-root023-render-fresh103"; xmf_attempt = f"root-stage1-f2-{slug}-full401-xmf-fresh103"; typed_attempt = f"root-stage1-f2-{slug}-full401-typed-fresh103"; native_attempt = str(native_req["attempt_id"])
    worker = FRESH101 / "workers/render_native023.py"
    files = closure_from_template(old_request)
    for path in (render_binding_path, xmf_path, xmf_binding_path, qa_path, native_path, case["side_path"], case["receipt_path"], case["report_path"], case["xml_path"], HERE / "metadata/contracts/native-path-contract.json"):
        add_static_input(files, path)
    guard = strict_guard(native=False)
    typed_receipt = raw_root / typed_attempt / "execution-receipt.json"; conversion = raw_root / typed_attempt / "conversion-report.json"; h5 = raw_root / typed_attempt / "trajectory.h5"; native_receipt = raw_root / native_attempt / "execution-receipt.json"; xmf_case = raw_root / xmf_attempt / "xdmf" / "case.xmf"; xmf_manifest = xmf_case.parent / "manifest.json"; future_files, future_sha = future_map([typed_receipt, conversion, h5, native_receipt, xmf_case, xmf_manifest])
    out = dict(old_request)
    out.update({"fresh_id": FRESH_ID, "attempt_id": attempt, "depends_on_attempts": [native_attempt, typed_attempt, xmf_attempt], "command": ["/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython", str(worker), "--manifest", str(xmf_manifest), "--output-dir", "{attempt_root}/render"], "cwd": str(HERE), "xmf_attempt": xmf_attempt, "xmf_request": str(xmf_path), "xmf_request_sha256": sha(xmf_path), "xmf_binding": str(xmf_binding_path), "xmf_binding_sha256": sha(xmf_binding_path), "xmf_case": str(xmf_case), "xmf_case_sha256": None, "xmf_manifest": str(xmf_manifest), "xmf_manifest_sha256": None, "typed_attempt_id": typed_attempt, "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None, "conversion_report": str(conversion), "conversion_report_sha256": None, "trajectory_h5": str(h5), "trajectory_h5_sha256": None, "native_request": str(native_path), "native_request_sha256": sha(native_path), "native_receipt": str(native_receipt), "native_receipt_sha256": None, "initial_qa_request": str(qa_path), "initial_qa_request_sha256": sha(qa_path), "initial_qa_report": str(raw_root / str(qa_req["attempt_id"]) / "actual-initial-qa.json"), "initial_qa_report_sha256": None, "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None, "prepared_gencase_particle_count": case["total"], "prepared_gencase_particle_counts": case["counts"], "expected_native_contract": {"dimension": 3, "frames": 401, "particle_counts": None, "type_partition": None, "key": "(Zone,Idp)", "counts_source": "actual XMF manifest/conversion report only"}, "camera_policy": {"bounds_source": "Root023 scans every native valid position across every saved frame", "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False, "fixed_camera_override": False, "native_geometry_retained": True}, "physical_condition_hash_scope": {"source_plan_physical_condition_sha256": load(FRESH101 / "render/bindings" / f"{cid}.render-binding.json")["source_plan_physical_condition_sha256"], "prospective_legacy_scope_sha256": load(FRESH101 / "render/bindings" / f"{cid}.render-binding.json")["physical_condition_sha256"], "actual_converter_physical_condition_sha256": None, "canonical_physical_binding_sha256": None, "canonical_grant": False}, "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_guard": guard, "input_files": sorted(files), "input_sha256": {p: files[p] for p in sorted(files)}, "future_input_files": future_files, "future_input_sha256": future_sha, "output_contract": {"execution_receipt_sha256": None, "report_sha256": None, "frames_sha256": None, "actual_frame_count": None}, "future_outputs": {"execution_receipt": None, "execution_receipt_sha256": None, "report": None, "report_sha256": None, "frames_dir": None, "frames_sha256": None, "contact_sheets": None, "gif": None, "gif_sha256": None, "pvsm": None, "pvsm_sha256": None}, "source_only": True, "disabled": True, "execution_allowed": False, "launch_allowed": False, "future_hashes_null": True, "disabled_reason": "Enable only after actual native401, typed conversion and XMF manifest review; Root023 remains downstream and no fixed camera is prefilled."})
    path = HERE / "render/requests" / f"{cid}-render-disabled.json"; dump(path, out); return path, out


def main() -> int:
    m101 = load(M101); m102 = load(M102)
    if m101.get("fresh_id") != "fresh101" or m101.get("case_count") != 16 or m102.get("fresh_id") != "fresh102" or m102.get("case_count") != 16:
        raise SystemExit("fresh101/fresh102 manifests must each contain 16 cases")
    old101 = {row["case_id"]: row for row in m101["cases"]}; rows102 = {row["case_id"]: row for row in m102["cases"]}
    if set(old101) != set(rows102):
        raise SystemExit("fresh101/fresh102 case sets differ")

    # Keep the already-reviewed producer workers local to this source package;
    # copying Python source does not execute or inspect scientific payloads.
    for worker_name in ("export_xmf.py", "render_native023.py"):
        destination = HERE / "workers" / worker_name
        shutil.copy2(FRESH101 / "workers" / worker_name, destination)

    dump(HERE / "metadata/contracts/native-path-contract.json", {"schema": "ds02.f2.stage1.fresh103.native-path-contract.v1", "prepared_counts": "actual fresh102 prepared-input-report", "prepared_dimension": 3, "raw_receipt_immutable": True, "raw_receipt_partition_fields_not_used": True, "semantic_dimension_source": "fresh102 producer sidecar contract_checks.root353_solver_dimension_three", "expected_frames": 401, "window_s": [0.0, 4.0], "save_interval_s": 0.01, "n_times_3_contract": True, "future_hashes_null": True, "source_only": True})
    dump(HERE / "metadata/contracts/runtime-strict-guard.json", {"schema": "ds02.f2.stage1.fresh103.runtime-strict-guard.v1", "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_dispatch": str(STRICT), "strict_dispatch_sha256": sha(STRICT), "runtime": str(RUNTIME), "runtime_sha256": sha(RUNTIME), "worktree_root": str(INFRA), "source_only": True, "metadata_input_closure": "JSON/XML/Python/text plus producer-recorded raw payload digests; no raw payload read during preparation", "future_payload_hashes": "null until Root-owned producer receipts exist"})
    dump(HERE / "metadata/contracts/qa-semantic-adapter.json", {"schema": "ds02.f2.stage1.fresh103.qa-semantic-adapter.v1", "raw_receipt_immutable": True, "raw_receipt_status_required": "completed/0", "raw_receipt_dimension_field_optional": True, "derived_dimension": 3, "derived_dimension_source": "fresh102 prepared evidence sidecar; not a rewritten execution receipt", "inner_worker": str(FRESH100 / "workers/f2_stage1_initial_qa_worker.py"), "semantic_receipt_lifetime": "attempt-local only", "semantic_output_root": "prepared-input-report.parent (flat generated XML/BI4/motion prefix)", "raw_output_root_preserved_in_final_report": True, "output_report_must_bind_raw_receipt": True, "partvtk_arrays_read_only_when_root_enables": True, "future_hashes_null": True})
    dump(HERE / "metadata/contracts/xmf-contract.json", {"schema": "ds02.f2.stage1.fresh103.xmf-contract.v1", "worker": str(FRESH101 / "workers/export_xmf.py"), "expected_frames": 401, "expected_dimension": 3, "expected_particles": None, "counts_source": "actual conversion-report only", "dynamic_vector_dimensions": "{actual_particles} 3", "dynamic_scalar_dimensions": "{actual_particles}", "n_times_3_required": True, "future_output_hashes_null": True})
    dump(HERE / "metadata/contracts/render-contract.json", {"schema": "ds02.f2.stage1.fresh103.render-contract.v1", "worker": str(FRESH101 / "workers/render_native023.py"), "expected_frames": 401, "expected_dimension": 3, "expected_particles": None, "camera_bounds_policy": {"bounds_source": "Root023 scans every native valid position across every saved frame", "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False, "fixed_camera_override": False}, "future_output_hashes_null": True})

    generated: list[dict[str, Any]] = []
    observed_failures: list[dict[str, Any]] = []
    for cid in sorted(old101):
        old = old101[cid]; evidence = actual_evidence(rows102[cid], m102)
        old_xmf_binding = load(Path(old["xmf_binding"]["path"]))
        old_xmf_request = load(Path(old["xmf_request"]["path"]))
        old_render_binding = load(Path(old["render_binding"]["path"]))
        old_render_request = load(Path(old["render_request"]["path"]))
        qa_path, qa = qa_request(evidence, old_xmf_binding, HERE / "metadata/contracts/qa-semantic-adapter.json")
        native_path, native = native_request(evidence, qa_path, qa)
        xb_path, xb = xmf_binding(evidence, qa_path, native_path, qa, native, old_xmf_binding)
        xr_path, xr = xmf_request(evidence, qa_path, native_path, qa, native, xb_path, old_xmf_request)
        # fresh101 render bindings deliberately omit source-definition fields;
        # reuse the matching XMF binding as the source metadata authority.
        rb_path, rb = render_binding(evidence, qa_path, native_path, xr_path, xb_path, qa, native, old_xmf_binding)
        rr_path, rr = render_request(evidence, qa_path, native_path, xr_path, xb_path, qa, native, rb_path, old_render_request)
        generated.append({"case_id": cid, "physical_case_id": evidence["side"].get("physical_case_id"), "source_plan_physical_condition_sha256": old_xmf_binding["source_plan_physical_condition_sha256"], "prospective_legacy_scope_sha256": old_xmf_binding["physical_condition_sha256"], "canonical_physical_binding_sha256": None, "prepared_gencase_particle_count": evidence["total"], "prepared_gencase_particle_counts": evidence["counts"], "prepared_gencase_dimension": 3, "gencase_evidence": bind(evidence["side_path"]), "gencase_receipt": {"path": str(evidence["receipt_path"]), "sha256": evidence["receipt_sha"], "status": evidence["receipt"].get("status"), "returncode": evidence["receipt"].get("returncode"), "raw_receipt_immutable": True}, "initial_qa_adapter_request": bind(qa_path), "native_request": bind(native_path), "xmf_binding": bind(xb_path), "xmf_request": bind(xr_path), "render_binding": bind(rb_path), "render_request": bind(rr_path), "observed_prior_qa": evidence["observed_qa"], "actual_native_receipt": None, "actual_typed_receipt": None, "actual_h5_sha256": None, "actual_xmf_sha256": None, "actual_render_sha256": None, "expected_frames": 401, "expected_particles": None, "independent_case_count_increment": 0})
        if evidence["observed_qa"] is not None:
            observed_failures.append({"case_id": cid, **evidence["observed_qa"]})

    dump(HERE / "evidence/qa-failure-and-semantic-adapter.json", {"schema": "ds02.f2.stage1.fresh103.qa-failure-and-semantic-adapter.v1", "fresh102_raw_receipts_unchanged": True, "observed_failed_or_pending_reports": observed_failures, "all_observed_reports_are_historical_negative_or_pending": True, "raw_receipt_dimension_field_is_not_patched": True, "fresh103_semantic_receipt_is_attempt_local": True, "arrays_read_during_source_preparation": False})
    dump(HERE / "evidence/source-entry-audit.json", {"schema": "ds02.f2.stage1.fresh103.source-entry-audit.v1", "fresh101_immutable": True, "fresh102_immutable": True, "case_count": 16, "initial_qa_adapter_requests": 16, "native_requests": 16, "xmf_requests": 16, "render_requests": 16, "all_requests_disabled": True, "future_hashes_null": True, "prepared_total_observed": 418104, "prepared_counts_observed": {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114}, "actual_prepared_dimension": 3, "dimension_source": "fresh102 producer sidecar contract check; raw receipts remain byte-identical", "strict_guard_digest": LOGICAL_GUARD, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "static_scientific_payloads_read_or_hashed": [], "raw_payload_digests_reused_from_root_records": True, "canonical_grant": False, "independent_case_count_increment": 0, "qa_pass_claim": False, "native_typed_visual_claim": False})
    dump(HERE / "evidence/fresh101-fresh102-contract-audit.json", {"schema": "ds02.f2.stage1.fresh103.upstream-contract-audit.v1", "fresh101_manifest": bind(M101), "fresh102_manifest": bind(M102), "fresh101_case_count": 16, "fresh102_case_count": 16, "fresh101_layout": {"xmf_bindings": 16, "xmf_requests": 16, "render_bindings": 16, "render_requests": 16}, "fresh102_layout": {"gencase_sidecars": 16, "initial_qa_requests": 16, "native_requests": 16}, "logical_strict_guard_digest": LOGICAL_GUARD, "actual_strict_dispatch_sha256": STRICT_DISPATCH_SHA, "n_times_3": {"dimension": 3, "vector_dimensions": "{actual_particles} 3", "scalar_dimensions": "{actual_particles}", "prepared_count": 418104, "typed_count": None}, "scope_separation": "source plan / prospective legacy owner / actual converter / canonical binding remain separate", "future_hashes_null": True, "arrays_read_or_hashed": False})
    manifest = {"schema": "ds02.f2.stage1.fresh103.native-path-xmf-adapter-manifest.v1", "fresh_id": FRESH_ID, "family_id": "F2", "scope_id": SCOPE, "source_only": True, "execution_allowed": False, "case_count": 16, "cases": generated, "expected_native_frames": 401, "expected_dimension": 3, "expected_particles": None, "prepared_gencase_particle_total": 418104, "prepared_gencase_particle_counts": {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114}, "producer_scope_schema": "legacy-owner-scope.v0", "source_plan_and_legacy_scope_separate": True, "canonical_physical_binding_sha256": None, "canonical_grant": False, "logical_strict_guard_digest": LOGICAL_GUARD, "actual_strict_dispatch_file_sha256": STRICT_DISPATCH_SHA, "strict_dispatch_inputs_bound": True, "qa_pass_claim": False, "native_typed_visual_claim": False, "raw_receipts_immutable": True, "future_hashes_null": True, "all_requests_disabled": True, "no_jobs_started": True, "no_science_arrays_read": True, "no_shared_registry_write": True, "independent_case_count_increment": 0, "contracts": {"qa_adapter": bind(HERE / "metadata/contracts/qa-semantic-adapter.json"), "native": bind(HERE / "metadata/contracts/native-path-contract.json"), "xmf": bind(HERE / "metadata/contracts/xmf-contract.json"), "render": bind(HERE / "metadata/contracts/render-contract.json"), "strict": bind(HERE / "metadata/contracts/runtime-strict-guard.json")}, "workers": {"qa_adapter": bind(HERE / "workers/fresh103_initial_qa_adapter.py"), "source_validator": bind(HERE / "workers/fresh103_source_contract_validator.py")}}
    dump(HERE / "F2_STAGE1_FRESH103_NATIVE_PATH_XMF_ADAPTER_MANIFEST.json", manifest)
    (HERE / "README.md").write_text("""# F2 fresh103 native-path and XMF adapter\n\nFresh103 rebinds the 16 real fresh102 prepared GenCase reports to disabled\ninitial-QA, native401, XMF and Root023 render requests.  Every prepared\nreport is bound to its actual JSON/XML/receipt path and dynamic counts\n(372840 fixed + 24150 moving + 0 floating + 21114 fluid = 418104 total).\nThe upstream producer sidecar supplies the 3-D dimension; fresh103 never\npatches the raw execution receipt.\n\nThe disabled QA adapter keeps the raw receipt immutable and creates an\nattempt-local semantic receipt only when Root enables the CPU worker.  That\nsemantic field is derived from the fresh102 prepared-evidence sidecar and is\nreported separately from the raw execution receipt.  The wrapper then invokes\nthe existing PartVTK initial-QA worker; no source preparation reads BI4,\nDAT, H5, CSV, VTK or XMF.  Existing fresh102 QA outputs are retained as\nhistorical negative/pending evidence and never treated as passes.\n\nAll downstream requests preserve the 401-frame, 4.0 s, 0.01 s, 3-D native\nrecipe.  XMF vectors use dynamic `{actual_particles} 3` dimensions and\nscalars use `{actual_particles}`; the 418104 prepared count is upstream\nevidence, not a typed trajectory count.  Source-plan, prospective\nlegacy-owner, actual-converter and canonical physical scopes remain separate.\nThe logical guard digest is `a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a`; the current strict-dispatch file is bound separately at\n`81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec`.\n\nNo request is executable.  Native, typed, H5, XMF and render receipts and\nhashes are null.  This package adds zero cases, grants no qualification or\nproduction status, does not modify fresh100-102, and does not write global\nregistry or ledger state.\n""", encoding="utf-8")
    print(json.dumps({"schema": "ds02.f2.stage1.fresh103.build-result.v1", "package": str(HERE), "case_count": 16, "qa_requests": 16, "native_requests": 16, "xmf_requests": 16, "render_requests": 16, "prepared_total": 418104, "future_hashes_null": True, "source_only": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
