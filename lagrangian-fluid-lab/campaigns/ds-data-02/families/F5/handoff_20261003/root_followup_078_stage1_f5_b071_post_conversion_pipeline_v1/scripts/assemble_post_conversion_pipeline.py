#!/usr/bin/env python3
"""Assemble F5 B071 post-conversion bindings from actual metadata only.

This helper is intentionally source-only until Root supplies the real typed
conversion receipt/report and, for the downstream stage, the real XMF receipt.
It reads JSON/XML metadata and hashes JSON/XML/source files.  It never opens
BI4, H5, or CSV scientific arrays; the H5 digest is taken from the converter's
verified ``output_sha256`` field and is registered as a strict input digest for
Root's next dispatch.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

PACKAGE_ID = "root_followup_078_stage1_f5_b071_post_conversion_pipeline_v1"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071"
FAMILY_ID = "F5"
PHYSICAL_CASE_ID = "F5_COMPACT_STILL_WATER_RUNUP_REPAIR_B_CENTRAL_SUPPORT_V1"
PHYSICAL_CONDITION_SHA256 = "d791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f"
SOURCE_PLAN_SHA256 = "e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72"
NATIVE_ATTEMPT = "root-stage1-f5-b071-short-native-qualification-187"
TYPED_ATTEMPT = "root-stage1-f5-b071-short-native-typed-nvme-189"
XMF_ATTEMPT = "root-stage1-f5-b071-short-native-xmf-190"
BED_ATTEMPT = "root-stage1-f5-b071-short-native-bed-audit-191"
RENDER_ATTEMPT = "root-stage1-f5-b071-short-native-render-192"
NATIVE_RECEIPT_SHA256 = "b1028f85aa11eb6890dd8c7d9206f9414aff739a473aee9b47b64217a4cc546a"
NATIVE_REQUEST_SHA256 = "4bc13b5bf347113a4c89ebf3bd105a995caa302dd1df541bc227fd86803e0658"
ROOT185_RECEIPT_SHA256 = "74cfb6c7e690c8572c0387e2e5c343d9a3a61018b5efc4224d3cf729b1fad818"
ROOT185_REPORT_SHA256 = "d6f99d4830accac0b97315d4707cc7009434e8fc6084b1af0c59dc08731c575d"
FRESH077_MANIFEST_SHA256 = "b8f811446cd4edfdcfbc2b8c827ece7a28ed708febb20fcf8fb6c51f666c7926"
RUNTIME_SHA256 = "5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60"
STRICT_SHA256 = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
EXPORT_XMF_SHA256 = "d70184e700ee23c6812d3185f37890df0174718445744643822f70ca03bd4e85"
BED_AUDIT_SHA256 = "5415502a4db8b8befed378379888af707289052e75edca97f5218aff2377bda0"
RENDER_SHA256 = "545f5a50d893972f174a3baafed5550e3f3245dc5c0f7ca5247a42402a0d6e87"
H5_SUFFIXES = {".h5", ".hdf5", ".bi4", ".csv"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CPU_ALLOWLIST = {"gencase", "conversion", "audit", "labels", "evaluator", "preview", "tests"}
WORKTREE_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics")
LAB_ROOT = WORKTREE_ROOT / "lagrangian-fluid-lab"
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
RUNTIME_PATH = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT_PATH = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
DEFAULT_FRESH077_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_077_stage1_f5_b071_actual_native187_typed_conversion_v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalized(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def load_json(path: str | Path) -> dict[str, Any]:
    resolved = normalized(path)
    with resolved.open(encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"JSON object required: {resolved}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    require(path.suffix.lower() not in H5_SUFFIXES, f"scientific array digest forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def digest_input(path: Path, declared_h5_sha256: str | None = None) -> str:
    path = normalized(path)
    require(path.is_file(), f"input file missing: {path}")
    lower = path.suffix.lower()
    if lower in H5_SUFFIXES:
        require(lower in {".h5", ".hdf5"}, f"BI4/CSV input forbidden: {path}")
        require(bool(declared_h5_sha256) and SHA256_RE.fullmatch(str(declared_h5_sha256)),
                f"H5 input must use converter output_sha256: {path}")
        return str(declared_h5_sha256)
    require("resource-ledger.json" not in str(path).lower(), f"live ledger input forbidden: {path}")
    return sha256_file(path)


def json_sha(path: Path) -> str:
    require(path.suffix.lower() not in H5_SUFFIXES, f"array metadata path forbidden: {path}")
    return sha256_file(path)


def verify_source_hash(path: Path, expected: str) -> None:
    require(path.is_file(), f"source input missing: {path}")
    actual = sha256_file(path)
    require(actual == expected, f"source changed: {path} ({actual} != {expected})")


def verify_registered_request(request: Mapping[str, Any], label: str, *, allow_h5: bool = False) -> None:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and files, f"{label}.input_files required")
    require(isinstance(hashes, dict), f"{label}.input_sha256 required")
    normalized_files = {str(normalized(value)) for value in files}
    normalized_hashes = {str(normalized(value)) for value in hashes}
    require(normalized_files == normalized_hashes, f"{label}: input_files/input_sha256 sets differ")
    for value in files:
        path = normalized(value)
        require(path.is_file(), f"{label}: missing input {path}")
        if path.suffix.lower() in H5_SUFFIXES:
            require(allow_h5 and path.suffix.lower() in {".h5", ".hdf5"}, f"{label}: array input is not allowed {path}")
        require("resource-ledger.json" not in str(path).lower(), f"{label}: live ledger input")
    for value in hashes.values():
        require(isinstance(value, str) and SHA256_RE.fullmatch(value), f"{label}: invalid digest")


def source_paths(fresh077: Path) -> dict[str, Path]:
    return {
        "fresh077": fresh077,
        "manifest": fresh077 / "manifest.json",
        "binding": fresh077 / "binding.json",
        "xmf_template": fresh077 / "xmf-binding-template.json",
        "xmf_request_template": fresh077 / "xmf-request-template.json",
        "bed_template": fresh077 / "short-bed-audit-binding-template.json",
        "bed_request_template": fresh077 / "short-bed-audit-request.json",
        "render_request_template": fresh077 / "render-request-template.json",
        "export_xmf": fresh077 / "workers/export_xmf.py",
        "bed_audit": fresh077 / "workers/bed_audit.py",
        "render": fresh077 / "workers/render_full_saved_animation.py",
        "runtime": RUNTIME_PATH,
        "strict": STRICT_PATH,
    }


def verify_fresh077_sources(fresh077: Path) -> dict[str, Path]:
    paths = source_paths(fresh077)
    verify_source_hash(paths["manifest"], FRESH077_MANIFEST_SHA256)
    verify_source_hash(paths["runtime"], RUNTIME_SHA256)
    verify_source_hash(paths["strict"], STRICT_SHA256)
    verify_source_hash(paths["export_xmf"], EXPORT_XMF_SHA256)
    verify_source_hash(paths["bed_audit"], BED_AUDIT_SHA256)
    verify_source_hash(paths["render"], RENDER_SHA256)
    for name in ("binding", "xmf_template", "xmf_request_template", "bed_template", "bed_request_template", "render_request_template"):
        require(paths[name].is_file(), f"fresh077 source missing: {paths[name]}")
    return paths


def verify_typed_conversion(receipt_path: Path, report_path: Path) -> dict[str, Any]:
    receipt_path = normalized(receipt_path)
    report_path = normalized(report_path)
    receipt = load_json(receipt_path)
    report = load_json(report_path)
    request = receipt.get("request")
    require(receipt.get("schema") == "ds02.execution-receipt.v1", "typed receipt schema mismatch")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "typed189 is not completed/0")
    require(isinstance(request, dict), "typed receipt nested request missing")
    require(request.get("schema") == "ds02.runner-request.v2", "typed request schema mismatch")
    require(request.get("case_id") == CASE_ID, "typed request case_id mismatch")
    require(request.get("attempt_id") == TYPED_ATTEMPT, "typed request attempt_id mismatch")
    require(request.get("cpu_task_kind") == "conversion", "typed request is not conversion")
    require(request.get("cpu_threads") == 2, "typed conversion must use CPU2")
    require(request.get("execution_allowed") is True and request.get("launch_allowed") is True, "typed receipt was not actually enabled")
    require(request.get("full801_authorized") is False, "full801 must remain disabled")
    require(request.get("physical_condition_sha256") == PHYSICAL_CONDITION_SHA256, "typed physical condition mismatch")
    require(request.get("source_plan_physical_condition_sha256") == SOURCE_PLAN_SHA256, "typed source plan mismatch")
    require(request.get("native_solver_attempt_id") == NATIVE_ATTEMPT, "typed native dependency mismatch")
    require(request.get("native_solver_receipt_sha256") == NATIVE_RECEIPT_SHA256, "typed native receipt hash mismatch")
    require(request.get("expected_frames") == 51 and request.get("expected_particles") == 214385, "typed expected axis mismatch")
    require(request.get("expected_fluid_particles") == 40710, "typed expected fluid count mismatch")
    protocol = request.get("nvme_protocol", {})
    require(protocol.get("staging_limit_bytes") == 25769803776, "typed NVMe peak contract mismatch")
    contract = request.get("conversion_contract", {})
    require(contract.get("native_3d_required") is True, "typed 3D contract missing")
    require(contract.get("mass_difference_reported_without_rescale") is True, "typed mass no-rescale contract missing")
    verify_registered_request(request, "typed request")

    require(report.get("schema") == "ds-data-02.bi4-direct-conversion.v1", "conversion report schema mismatch")
    require(report.get("conversion_status") == "completed", "conversion report is not completed")
    require(report.get("frames") == 51 and report.get("particles") == 214385, "conversion report axis mismatch")
    report_h5 = normalized(report.get("output_hdf5", ""))
    typed_root = normalized(request.get("output_root", ""))
    require(report_h5 == typed_root / "trajectory.h5", "conversion report H5 path mismatch")
    require(report_h5.is_file(), "typed trajectory.h5 is missing")
    output_sha = report.get("output_sha256")
    require(isinstance(output_sha, str) and SHA256_RE.fullmatch(output_sha), "conversion output_sha256 missing")
    storage = report.get("storage_protocol", {})
    require(storage.get("verified_published_output_sha256") == output_sha, "verified H5 digest mismatch")
    require(storage.get("private_staging_removed") is True, "NVMe private staging was not closed")
    dimension = report.get("solver_dimension", {})
    require(dimension.get("solver_dimension") == 3 and dimension.get("xml_data2d") is False, "conversion is not native 3D")
    time_evidence = report.get("time_evidence", {})
    require(time_evidence.get("first_s") == 0.0 and time_evidence.get("last_s", 0.0) >= 1.0, "conversion time window mismatch")
    require(time_evidence.get("strictly_increasing") is True, "conversion time axis is not strict")
    partvtk = report.get("partvtk_validation", {})
    require(partvtk.get("all_passed") is True, "PartVTK metadata validation did not pass")
    typed_identity = report.get("typed_identity", {})
    require(50 in typed_identity.get("observed_mks", []), "native bed Mk50 absent from conversion metadata")
    require({0, 1, 3}.issubset(set(typed_identity.get("observed_types", []))), "native type identity incomplete")
    provenance = report.get("source_provenance", {})
    generated_xml = provenance.get("generated_xml", {})
    require(isinstance(generated_xml, dict) and normalized(generated_xml.get("path", "")).is_file(), "generated XML provenance missing")
    require(report.get("coordinate_frame") == "DualSPHysics case Cartesian coordinates (x,y,z)", "native coordinate frame changed")
    return {
        "receipt_path": receipt_path,
        "receipt": receipt,
        "receipt_sha256": json_sha(receipt_path),
        "request": request,
        "report_path": report_path,
        "report": report,
        "report_sha256": json_sha(report_path),
        "trajectory_h5": report_h5,
        "trajectory_h5_sha256": output_sha,
        "typed_root": typed_root,
    }


def actual_binding_base(fresh077: Path) -> dict[str, Any]:
    return load_json(fresh077 / "binding.json")


def add_path(paths: dict[str, str | None], path: Path, *, known_sha256: str | None = None) -> None:
    path = normalized(path)
    require(path.is_file(), f"pipeline input missing: {path}")
    require("resource-ledger.json" not in str(path).lower(), f"live ledger input forbidden: {path}")
    current = digest_input(path, known_sha256)
    previous = paths.get(str(path))
    require(previous in (None, current), f"conflicting input digest for {path}")
    paths[str(path)] = current


def collect_inputs(base_request: Mapping[str, Any], *, drop_fragments: tuple[str, ...], extra: list[tuple[Path, str | None]], command_files: list[Path]) -> tuple[list[str], dict[str, str]]:
    digests: dict[str, str | None] = {}
    for value in base_request.get("input_files", []):
        text = str(value)
        if any(fragment in text for fragment in drop_fragments):
            continue
        path = normalized(text)
        add_path(digests, path)
    for path in command_files:
        add_path(digests, path)
    for path, known in extra:
        add_path(digests, path, known_sha256=known)
    paths = sorted(digests)
    require(all(digests[path] is not None for path in paths), "input digest assembly incomplete")
    return paths, {path: str(digests[path]) for path in paths}


def update_common_request(request: dict[str, Any], *, attempt_id: str, task_kind: str, depends_on: str,
                          source_root: Path, output_root: Path, command: list[str], input_files: list[str],
                          input_sha256: dict[str, str]) -> dict[str, Any]:
    require(task_kind in CPU_ALLOWLIST, f"task kind outside runtime allowlist: {task_kind}")
    request.update({
        "schema": "ds02.runner-request.v2",
        "package_id": PACKAGE_ID,
        "family_id": FAMILY_ID,
        "case_id": CASE_ID,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": task_kind,
        "cpu_threads": 2,
        "command": command,
        "cwd": str(LAB_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "source_scope_root": str(source_root),
        "output_root": str(output_root),
        "depends_on_attempt": depends_on,
        "input_files": input_files,
        "input_sha256": input_sha256,
        "launch_owner": "root",
        "launch_allowed": False,
        "execution_allowed": False,
        "root_review_required": True,
        "full16_authorized": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "old_attempt_modification_forbidden": True,
    })
    return request


def verify_xmf_receipt(xmf_receipt_path: Path, xmf_dir: Path, typed: Mapping[str, Any]) -> dict[str, Any]:
    xmf_receipt_path = normalized(xmf_receipt_path)
    xmf_dir = normalized(xmf_dir)
    receipt = load_json(xmf_receipt_path)
    request = receipt.get("request")
    require(receipt.get("schema") == "ds02.execution-receipt.v1", "XMF receipt schema mismatch")
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "XMF is not completed/0")
    require(isinstance(request, dict), "XMF nested request missing")
    require(request.get("case_id") == CASE_ID, "XMF case_id mismatch")
    require(request.get("cpu_task_kind") == "audit" and request.get("cpu_threads") == 2, "XMF task kind/CPU mismatch")
    require(request.get("full801_authorized") is False, "XMF full801 gate changed")
    verify_registered_request(request, "XMF request", allow_h5=True)
    normalized_input_hashes = {str(normalized(value)): digest for value, digest in request["input_sha256"].items()}
    trajectory_key = str(normalized(typed["trajectory_h5"]))
    require(normalized_input_hashes.get(trajectory_key) == typed["trajectory_h5_sha256"], "XMF request H5 digest is not the conversion-report digest")
    xmf_path = xmf_dir / "case.xmf"
    manifest_path = xmf_dir / "manifest.json"
    require(xmf_path.is_file() and manifest_path.is_file(), "XMF outputs missing")
    manifest = load_json(manifest_path)
    require(manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1", "XMF manifest schema mismatch")
    require(manifest.get("xdmf") == str(xmf_path), "XMF manifest path mismatch")
    xmf_sha = sha256_file(xmf_path)
    require(manifest.get("xdmf_sha256") == xmf_sha, "XMF manifest digest mismatch")
    require(manifest.get("source_h5_sha256") == typed["trajectory_h5_sha256"], "XMF source H5 digest mismatch")
    require(manifest.get("frames") == 51 and manifest.get("particles") == 214385, "XMF axis mismatch")
    require(manifest.get("source_h5_read_only") is True, "XMF source H5 was not read-only")
    require(manifest.get("physical_condition_sha256") == PHYSICAL_CONDITION_SHA256, "XMF physical condition mismatch")
    actual_times = manifest.get("actual_time_s")
    require(isinstance(actual_times, list) and len(actual_times) == 51, "XMF does not contain all 51 actual times")
    return {
        "receipt_path": xmf_receipt_path,
        "receipt": receipt,
        "receipt_sha256": json_sha(xmf_receipt_path),
        "request": request,
        "xmf_dir": xmf_dir,
        "xmf_path": xmf_path,
        "xmf_sha256": xmf_sha,
        "manifest_path": manifest_path,
        "manifest_sha256": json_sha(manifest_path),
        "manifest": manifest,
    }


def make_xmf_stage(args: argparse.Namespace, fresh077: Path, typed: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    paths = verify_fresh077_sources(fresh077)
    base_request = load_json(paths["xmf_request_template"])
    base_binding = load_json(paths["xmf_template"])
    typed_root = Path(typed["typed_root"])
    case_root = typed_root.parent
    attempt_id = args.xmf_attempt
    output_root = case_root / attempt_id
    binding_path = output_dir / "xmf-binding.json"
    xmf_path = output_root / "case.xmf"
    manifest_path = output_root / "manifest.json"
    binding = copy.deepcopy(base_binding)
    binding.update({
        "schema": "ds02.stage1.paraview-temporal-binding.v2",
        "bound_status": "actual_typed189_metadata_bound_xmf_disabled",
        "package_id": PACKAGE_ID,
        "scope": PACKAGE_ID,
        "attempt_id": attempt_id,
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "native_receipt_status": "completed0",
        "typed_receipt": str(typed["receipt_path"]),
        "typed_receipt_sha256": typed["receipt_sha256"],
        "typed_receipt_status": "completed0",
        "conversion_report": str(typed["report_path"]),
        "conversion_report_sha256": typed["report_sha256"],
        "trajectory_h5": str(typed["trajectory_h5"]),
        "trajectory_h5_sha256": typed["trajectory_h5_sha256"],
        "xmf": str(xmf_path),
        "manifest": str(manifest_path),
        "xmf_sha256": None,
        "manifest_sha256": None,
        "source_h5_read_only": True,
        "full16_authorized": False,
        "full801_authorized": False,
        "visual_status": "pending actual XMF and Root visual review",
    })
    write_json(binding_path, binding)
    command = [str(LAB_ROOT / ".venv/bin/python"), str(paths["export_xmf"]), "--binding", str(binding_path), "--output-dir", "{attempt_root}"]
    input_files, input_sha256 = collect_inputs(
        base_request,
        drop_fragments=("xmf-binding-template.json",),
        command_files=[Path(command[0]), paths["export_xmf"], paths["runtime"], paths["strict"]],
        extra=[
            (binding_path, None),
            (typed["receipt_path"], None),
            (typed["report_path"], None),
            (typed["trajectory_h5"], typed["trajectory_h5_sha256"]),
        ],
    )
    request = update_common_request(copy.deepcopy(base_request), attempt_id=attempt_id, task_kind="audit",
                                    depends_on=TYPED_ATTEMPT, source_root=Path(__file__).resolve().parents[1],
                                    output_root=output_root, command=command,
                                    input_files=input_files, input_sha256=input_sha256)
    request.update({
        "expected_dimension": 3,
        "expected_frames": 51,
        "expected_particles": 214385,
        "expected_fluid_particles": 40710,
        "save_interval_s": 0.02,
        "estimated_storage_bytes": 4294967296,
        "conversion_allowed": False,
        "xmf_required": True,
        "native_conversion_required": True,
        "output_contract": {
            "required_outputs": ["case.xmf", "manifest.json", "README.txt"],
            "all_51_frames_required": True,
            "source_h5_sha256": typed["trajectory_h5_sha256"],
            "future_xmf_sha256": None,
            "future_manifest_sha256": None,
            "native_fields_preserved": True,
            "visual_acceptance": "pending Root review; XMF integrity does not certify physics",
        },
        "future_bindings": {"xmf": str(xmf_path), "manifest": str(manifest_path), "xmf_sha256": None, "manifest_sha256": None},
    })
    request_path = output_dir / "xmf-request.json"
    write_json(request_path, request)
    return {"xmf_binding": binding_path, "xmf_request": request_path, "xmf_request_obj": request, "xmf_output_root": output_root}


def make_downstream_stage(args: argparse.Namespace, fresh077: Path, typed: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    paths = verify_fresh077_sources(fresh077)
    xmf = verify_xmf_receipt(normalized(args.xmf_receipt), normalized(args.xmf_dir), typed)
    typed_root = Path(typed["typed_root"])
    case_root = typed_root.parent
    bed_attempt = args.bed_attempt
    render_attempt = args.render_attempt
    bed_output_root = case_root / bed_attempt
    render_output_root = case_root / render_attempt

    bed_binding = copy.deepcopy(load_json(paths["bed_template"]))
    bed_binding.update({
        "schema": "ds02.f5.b071.short-event-bed-audit-binding.v2",
        "bound_status": "actual_typed189_xmf190_metadata_bound_disabled",
        "package_id": PACKAGE_ID,
        "attempt_id": bed_attempt,
        "case_id": CASE_ID,
        "native_bed_marker_mk": 50,
        "source_bed_marker_mkbound": 40,
        "typed_receipt": str(typed["receipt_path"]),
        "typed_receipt_sha256": typed["receipt_sha256"],
        "native_conversion_report": str(typed["report_path"]),
        "native_conversion_report_sha256": typed["report_sha256"],
        "trajectory_h5": str(typed["trajectory_h5"]),
        "trajectory_h5_sha256": typed["trajectory_h5_sha256"],
        "xdmf": str(xmf["xmf_path"]),
        "xdmf_sha256": xmf["xmf_sha256"],
        "xmf_manifest": str(xmf["manifest_path"]),
        "xmf_manifest_sha256": xmf["manifest_sha256"],
        "full16_authorized": False,
        "full801_authorized": False,
        "repair_success": "unknown_until_actual_short_framewise_audit",
        "trajectory_source_read_only": True,
    })
    bed_binding_path = output_dir / "bed-audit-binding.json"
    write_json(bed_binding_path, bed_binding)
    bed_base = load_json(paths["bed_request_template"])
    bed_command = [str(LAB_ROOT / ".venv/bin/python"), str(paths["bed_audit"]), "--binding", str(bed_binding_path),
                   "--trajectory-h5", str(typed["trajectory_h5"]), "--xdmf", str(xmf["xmf_path"]), "--output-dir", "{attempt_root}/audit-output"]
    bed_inputs, bed_hashes = collect_inputs(
        bed_base,
        drop_fragments=("short-bed-audit-binding-template.json",),
        command_files=[Path(bed_command[0]), paths["bed_audit"], paths["runtime"], paths["strict"]],
        extra=[
            (bed_binding_path, None), (typed["receipt_path"], None), (typed["report_path"], None),
            (typed["trajectory_h5"], typed["trajectory_h5_sha256"]),
            (xmf["receipt_path"], None), (xmf["xmf_path"], None), (xmf["manifest_path"], None),
        ],
    )
    bed_request = update_common_request(bed_base, attempt_id=bed_attempt, task_kind="audit", depends_on=xmf["request"]["attempt_id"],
                                        source_root=Path(__file__).resolve().parents[1], output_root=bed_output_root,
                                        command=bed_command, input_files=bed_inputs, input_sha256=bed_hashes)
    bed_request.update({
        "expected_dimension": 3, "expected_frames": 51, "expected_particle_axis": 174896,
        "expected_fluid_particles": 40710, "save_interval_s": 0.02,
        "estimated_storage_bytes": 8589934592, "xmf_required": True,
        "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40,
        "output_contract": {
            "required_outputs": ["audit-output/b071-short-event-bed-footprint-audit.json"],
            "all_51_actual_frames_required": True, "frame_indices": list(range(51)),
            "future_report_sha256": None, "penetration_thresholds_diagnostic_only": True,
            "uid_loss_nonfinite_unexplained": True,
            "bed_y_bounds_m": [-0.15, 0.15], "native_bed_marker_mk": 50,
        },
        "future_bindings": {"report": str(bed_output_root / "audit-output/b071-short-event-bed-footprint-audit.json"), "report_sha256": None},
    })
    bed_request_path = output_dir / "bed-audit-request.json"
    write_json(bed_request_path, bed_request)

    render_base = load_json(paths["render_request_template"])
    render_command = ["/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython", str(paths["render"]),
                      "--manifest", str(xmf["manifest_path"]), "--output-dir", "{attempt_root}/render"]
    render_inputs, render_hashes = collect_inputs(
        render_base,
        drop_fragments=(),
        command_files=[Path(render_command[0]), paths["render"], paths["runtime"], paths["strict"]],
        extra=[
            (typed["receipt_path"], None), (typed["report_path"], None), (typed["trajectory_h5"], typed["trajectory_h5_sha256"]),
            (xmf["receipt_path"], None), (xmf["xmf_path"], None), (xmf["manifest_path"], None),
        ],
    )
    render_request = update_common_request(render_base, attempt_id=render_attempt, task_kind="preview", depends_on=xmf["request"]["attempt_id"],
                                           source_root=Path(__file__).resolve().parents[1], output_root=render_output_root,
                                           command=render_command, input_files=render_inputs, input_sha256=render_hashes)
    render_request.update({
        "expected_dimension": 3, "expected_frames": 51, "expected_particles": 214385,
        "save_interval_s": 0.02, "estimated_storage_bytes": 8589934592,
        "xmf_required": True, "native_fields_preserved": True,
        "output_contract": {
            "required_outputs": ["render/paraview-full-animation-report.json", "render/case.pvsm", "render/full_saved_animation.gif"],
            "all_51_frame_pngs": True, "contact_sheets": True, "actual_time_axis_preserved": True,
            "future_output_sha256": None, "visual_acceptance": "pending Root inspection; render integrity does not certify physics",
        },
        "future_bindings": {"manifest": str(xmf["manifest_path"]), "manifest_sha256": xmf["manifest_sha256"], "render_output_sha256": None},
    })
    render_request_path = output_dir / "render-request.json"
    write_json(render_request_path, render_request)
    return {
        "xmf_receipt": xmf["receipt_path"], "xmf_receipt_sha256": xmf["receipt_sha256"],
        "xmf_sha256": xmf["xmf_sha256"], "xmf_manifest_sha256": xmf["manifest_sha256"],
        "bed_binding": bed_binding_path, "bed_request": bed_request_path,
        "render_request": render_request_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh077-root", type=Path, default=DEFAULT_FRESH077_ROOT)
    parser.add_argument("--typed-receipt", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--stage", choices=("xmf", "downstream"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--xmf-receipt", type=Path)
    parser.add_argument("--xmf-dir", type=Path)
    parser.add_argument("--xmf-attempt", default=XMF_ATTEMPT)
    parser.add_argument("--bed-attempt", default=BED_ATTEMPT)
    parser.add_argument("--render-attempt", default=RENDER_ATTEMPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fresh077 = normalized(args.fresh077_root)
    output_dir = normalized(args.output_dir)
    require(fresh077.is_dir(), f"fresh077 root missing: {fresh077}")
    typed = verify_typed_conversion(args.typed_receipt, args.conversion_report)
    require(normalized(args.typed_receipt) == typed["receipt_path"], "typed receipt normalization failure")
    if args.stage == "xmf":
        result = make_xmf_stage(args, fresh077, typed, output_dir)
        result.update({"stage": "xmf", "typed_receipt_sha256": typed["receipt_sha256"], "conversion_report_sha256": typed["report_sha256"], "trajectory_h5_sha256": typed["trajectory_h5_sha256"]})
    else:
        require(args.xmf_receipt and args.xmf_dir, "downstream stage requires --xmf-receipt and --xmf-dir")
        result = make_downstream_stage(args, fresh077, typed, output_dir)
        result.update({"stage": "downstream", "typed_receipt_sha256": typed["receipt_sha256"], "conversion_report_sha256": typed["report_sha256"], "trajectory_h5_sha256": typed["trajectory_h5_sha256"]})
    write_json(output_dir / "assembly-report.json", {"schema": "ds02.f5.b071.post-conversion-assembly.v1", "source_only": True, "arrays_opened": False, "jobs_started": False, **{k: str(v) if isinstance(v, Path) else v for k, v in result.items() if k not in {"xmf_request_obj"}}})
    print(json.dumps({"schema": "ds02.f5.b071.post-conversion-assembly.v1", "stage": args.stage, "source_only": True, "arrays_opened": False, "jobs_started": False, "outputs": sorted(str(k) for k in result if k.endswith("request") or k.endswith("binding"))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
