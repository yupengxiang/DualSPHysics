#!/usr/bin/env python3
"""Build the fresh182 M101/T100 metadata-only previsual handoff.

The actual case belongs to F5; this source package is stored in the assigned
F3 worktree.  Only JSON/XML/XMF/Python/Markdown metadata is opened or hashed.
H5/BI4/IBI4/CSV/DAT/VTK payloads are represented by producer attestations and
are never opened, copied, walked, or hashed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
)
DATA = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34"
)
SOURCE180 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/"
    "root_followup_180_f5_m101_scope_repair_and_new_xmf_bed_disabled_v1"
)
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34"
PHYSICAL = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M101_T100"
CANONICAL = "1a04363bffefde127740d3da87de48ba66db566b7ae0cdf44d6c6f4b73137cf3"
LEGACY = "80039c17cc7a088b7bc0fdc5c7a74d9051aa72763652261e2823635fcd5ad93d"
XMF_HISTORICAL_LEGACY = "37c47df9bf900444e6d0dafcb41af77a8a0d9ff9e777fbf8c3cd056512642235"
SOURCE_DEF = "6c74924feda21861f0a15d1259871f3a536ae2a2264acc4047a60caee1b5d451"
SOURCE_PLAN = "366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324"
H5_PRODUCER = "ec9285c2984e960dbe3b7d12c26c78d21b9df47ddd0273d59b0691ed1d341aa1"
FRAMES = 801
PARTICLES = 194427
COUNTS = {"fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210}
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
ALLOWED_METADATA = {".json", ".xml", ".xmf", ".py", ".md"}


class BuildError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise BuildError(message)


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read refused for {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {label}: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"metadata object required for {label}: {path}")
    return value


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN:
        fail(f"scientific payload hash refused for {label}: {path}")
    if suffix not in ALLOWED_METADATA:
        fail(f"unsupported metadata hash for {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata for {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata_ref(path: Path, role: str, *, json_only: bool = False) -> dict[str, Any]:
    if not path.is_absolute():
        fail(f"metadata ref is not absolute: {role}: {path}")
    if json_only:
        load_json(path, role)
    elif path.suffix.lower() == ".json":
        load_json(path, role)
    elif path.suffix.lower() not in {".xml", ".xmf", ".py", ".md"}:
        fail(f"metadata ref has unsupported suffix: {role}: {path}")
    return {"path": str(path), "sha256": metadata_sha(path, role), "role": role}


def scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return {"kind": "list", "length": len(value)}
    if isinstance(value, dict):
        return {"kind": "object", "keys": sorted(value)[:64]}
    return {"kind": type(value).__name__}


def field_mask(obj: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Keep absent, explicit-null, and present roles distinguishable."""
    result: dict[str, Any] = {}
    for key in keys:
        if key not in obj:
            result[key] = {"presence": "absent"}
        elif obj[key] is None:
            result[key] = {"presence": "null"}
        else:
            result[key] = {"presence": "present", "value": scalar(obj[key])}
    return result


def stage_summary(path: Path, role: str, *, case: str = CASE) -> dict[str, Any]:
    obj = load_json(path, role)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{role} is not completed/0: {path}: {obj.get('status')}/{obj.get('returncode')}")
    req = obj.get("request") if isinstance(obj.get("request"), dict) else {}
    got_case = req.get("case_id", obj.get("case_id"))
    got_physical = req.get("physical_case_id", obj.get("physical_case_id"))
    if got_case not in (None, case) or got_physical not in (None, PHYSICAL):
        fail(f"{role} identity mismatch: {path}")
    return {
        "path": str(path),
        "sha256": metadata_sha(path, role),
        "role": role,
        "schema": obj.get("schema"),
        "status": obj.get("status"),
        "returncode": obj.get("returncode"),
        "attempt_id": req.get("attempt_id", obj.get("attempt_id")),
        "case_id": got_case,
        "physical_case_id": got_physical,
        "started_at_utc": obj.get("started_at_utc"),
        "finished_at_utc": obj.get("finished_at_utc"),
        "output_root": obj.get("output_root"),
        "production_product_acceptance": obj.get("production_product_acceptance"),
        "numerical_reference_status": obj.get("numerical_reference_status"),
    }


def process_snapshot(pid: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"pid": pid, "present": False}
    if not isinstance(pid, int) or pid <= 0:
        return result
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except OSError as exc:
        result["error"] = type(exc).__name__
        return result
    try:
        after = raw.rsplit(") ", 1)[1].split()
        result.update(
            {
                "present": True,
                "state": after[0],
                "ppid": int(after[1]),
                "start_ticks": after[19],
            }
        )
    except (IndexError, ValueError) as exc:
        result["error"] = f"stat_parse:{exc}"
    return result


def stat_pngs(directory: Path) -> dict[str, Any]:
    """Stat filenames only; never open a PNG."""
    if not directory.exists():
        return {"directory_exists": False, "png_count": 0, "png_names": []}
    names: list[str] = []
    for item in directory.rglob("*.png"):
        try:
            item.stat()
        except OSError:
            continue
        names.append(str(item.relative_to(directory)))
    names.sort()
    return {"directory_exists": True, "png_count": len(names), "png_names": names[:64], "names_truncated": len(names) > 64}


def render_snapshot(render_path: Path, wrapper: dict[str, Any], controller: dict[str, Any]) -> dict[str, Any]:
    receipt = load_json(render_path, "current render receipt")
    req = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    identity = {
        "case_id": req.get("case_id", receipt.get("case_id")),
        "physical_case_id": req.get("physical_case_id", receipt.get("physical_case_id")),
        "attempt_id": req.get("attempt_id", receipt.get("attempt_id")),
    }
    if identity["case_id"] != CASE or identity["physical_case_id"] != PHYSICAL:
        fail("current render receipt identity mismatch")
    output_root = Path(str(receipt.get("output_root", wrapper.get("home_output", ""))))
    render_dir = output_root / "render"
    report = render_dir / "paraview-full-animation-report.json"
    observed = datetime.now(timezone.utc).isoformat()
    terminal = receipt.get("status") in {"completed", "failed", "cancelled"}
    return {
        "receipt": {
            "path": str(render_path),
            "observed_sha256": metadata_sha(render_path, "current render receipt"),
            "schema": receipt.get("schema"),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "pid": receipt.get("pid"),
            "started_at_utc": receipt.get("started_at_utc"),
            "output_root": str(output_root),
            "request_sha256": receipt.get("request_sha256"),
            "production_product_acceptance": receipt.get("production_product_acceptance"),
            "numerical_reference_status": receipt.get("numerical_reference_status"),
        },
        "observed_at_utc": observed,
        "terminal_at_observation": terminal,
        "published_report": {"path": str(report), "exists": report.is_file()},
        "private_render": stat_pngs(render_dir),
        "worker_proc": process_snapshot(receipt.get("pid")),
        "controller_proc": process_snapshot(controller.get("pid")),
        "visual_status": "pending actual complete render and personal delegated review",
        "case_credit": 0,
    }


def build(output_dir: Path) -> Path:
    output_dir = output_dir.resolve()
    metadata_dir = output_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    chain_path = SOURCE180 / "metadata" / "M101_T100-actual-chain.json"
    chain = load_json(chain_path, "actual M101 chain")
    binding_path = INTEGRATION / "root_stage1_F5_M101_T100_actual1115_bed0_full801_UID_footprint_original116023944_expected34_render_1158" / "registered-render-binding.json"
    lineage_path = binding_path.parent / "actual-bed0-to-render-input-lineage.json"
    review_path = binding_path.parent / "actual-full801-bed-UID-footprint-times-and-scope-independent-review.json"
    request_path = binding_path.parent / "enabled-full801-render-request.json"
    wrapper_path = binding_path.parent / "enabled-render-wrapper.json"
    controller_launch_path = binding_path.parent / "controller-launch-process.json"
    controller_config_path = binding_path.parent / "controller-config.json"
    render_path = DATA / "root-stage1-f5-m101_t100-actual1115-bed0-full801-original116023-frozen-progress-root1158" / "execution-receipt.json"

    binding = load_json(binding_path, "registered render binding")
    lineage = load_json(lineage_path, "render lineage")
    review = load_json(review_path, "full bed review")
    request = load_json(request_path, "enabled render request")
    wrapper = load_json(wrapper_path, "enabled render wrapper")
    controller = load_json(controller_launch_path, "controller launch metadata")
    render = load_json(render_path, "current render receipt")

    xmf_path = DATA / "root-stage1-f5-m101_t100-actual1028-full801-N3-xmf129-root1074" / "xmf" / "manifest.json"
    xmf = load_json(xmf_path, "XMF manifest")
    xmf_receipt_path = xmf_path.parent.parent / "execution-receipt.json"
    typed_report_path = DATA / "root-stage1-f5-m101_t100-actual-native0-full801-typed157-home4gib-root1028" / "conversion-report.json"
    typed_receipt_path = typed_report_path.parent / "execution-receipt.json"
    native_receipt_path = DATA / "root-stage1-f5-next34-m101_t100-own848849-full801-native-source170-root1017" / "execution-receipt.json"
    bed_dir = DATA / "root-stage1-f5-m101_t100-actual1035-1073-1074-full801-original138-fresh180-bed-root1115"
    bed_report_path = bed_dir / "audit-output" / "c082s1-full-event-bed-footprint-audit.json"
    bed_receipt_path = bed_dir / "execution-receipt.json"
    native_receipt = load_json(native_receipt_path, "native receipt")
    typed_report = load_json(typed_report_path, "typed report")
    bed_report = load_json(bed_report_path, "bed report")
    xmf_receipt = load_json(xmf_receipt_path, "XMF receipt")
    native_request_path = Path(str(xmf.get("actual_native_request")))
    source_owner_path = Path(str(xmf.get("source_owner"))) if xmf.get("source_owner") else None
    source_plan_path = Path(str(xmf.get("source_plan"))) if xmf.get("source_plan") else None
    source_definition_path = Path(str(xmf.get("source_definition"))) if xmf.get("source_definition") else None

    static_refs = [
        metadata_ref(chain_path, "source180 actual chain", json_only=True),
        metadata_ref(binding_path, "registered render binding", json_only=True),
        metadata_ref(lineage_path, "actual bed-to-render lineage", json_only=True),
        metadata_ref(review_path, "actual full801 bed review", json_only=True),
        metadata_ref(request_path, "enabled render request", json_only=True),
        metadata_ref(wrapper_path, "enabled render wrapper", json_only=True),
        metadata_ref(controller_launch_path, "controller launch metadata", json_only=True),
        metadata_ref(controller_config_path, "controller config", json_only=True),
        metadata_ref(native_receipt_path, "native receipt", json_only=True),
        metadata_ref(typed_receipt_path, "typed receipt", json_only=True),
        metadata_ref(typed_report_path, "typed conversion report", json_only=True),
        metadata_ref(xmf_receipt_path, "XMF receipt", json_only=True),
        metadata_ref(xmf_path, "XMF manifest", json_only=True),
        metadata_ref(DATA / "root-stage1-f5-m101_t100-actual1028-full801-N3-xmf129-root1074" / "xmf" / "case.xmf", "XMF XML"),
        metadata_ref(bed_receipt_path, "bed receipt", json_only=True),
        metadata_ref(bed_report_path, "bed report", json_only=True),
        metadata_ref(Path(str(chain["chain"]["gencase"]["receipt"]["path"])), "GenCase receipt", json_only=True),
        metadata_ref(Path(str(chain["chain"]["gencase"]["prepared_report"]["path"])), "GenCase prepared report", json_only=True),
        metadata_ref(Path(str(chain["chain"]["gencase"]["generated_xml"]["path"])), "GenCase generated XML"),
        metadata_ref(Path(str(chain["chain"]["initial_qa"]["receipt"]["path"])), "initial QA receipt", json_only=True),
        metadata_ref(Path(str(chain["chain"]["initial_qa"]["report"]["path"])), "initial QA report", json_only=True),
    ]
    for path, role in ((native_request_path, "native request"), (source_owner_path, "source owner"), (source_plan_path, "source plan"), (source_definition_path, "SourceDef XML")):
        if path is not None:
            static_refs.append(metadata_ref(path, role, json_only=path.suffix.lower() == ".json"))

    # The masks deliberately distinguish an absent field from an explicit null.
    role_keys = (
        "canonical_condition_sha256",
        "physical_condition_sha256",
        "canonical_physical_condition_sha256",
        "source_plan_condition_sha256",
        "source_plan_physical_condition_sha256",
        "source_definition_sha256",
        "source_plan_sha256",
    )
    native_request = load_json(native_request_path, "native request")
    native_mask = field_mask(native_request, role_keys)
    xmf_mask = field_mask(xmf, role_keys)
    typed_mask = field_mask(typed_report, role_keys)
    bed_mask = field_mask(bed_report, role_keys)

    actual_times = xmf.get("actual_time_s") if isinstance(xmf.get("actual_time_s"), list) else []
    typed_time = typed_report.get("time_evidence") if isinstance(typed_report.get("time_evidence"), dict) else {}
    bed_time = bed_report.get("time_provenance") if isinstance(bed_report.get("time_provenance"), dict) else {}
    fields = xmf.get("fields") if isinstance(xmf.get("fields"), dict) else {}
    field_contract = {k: scalar(v) for k, v in fields.items()}

    stage_refs = {
        "gencase": stage_summary(Path(str(chain["chain"]["gencase"]["receipt"]["path"])), "GenCase receipt"),
        "initial_qa": stage_summary(Path(str(chain["chain"]["initial_qa"]["receipt"]["path"])), "initial QA receipt"),
        "native": stage_summary(native_receipt_path, "native receipt"),
        "typed": stage_summary(typed_receipt_path, "typed receipt"),
        "xmf": stage_summary(xmf_receipt_path, "XMF receipt"),
        "bed": stage_summary(bed_receipt_path, "bed receipt"),
    }

    controller_identity = {
        "path": str(controller_launch_path),
        "sha256": metadata_sha(controller_launch_path, "controller launch metadata"),
        "pid": controller.get("pid"),
        "proc_start_ticks_declared": controller.get("proc_start_ticks"),
        "observed_proc": process_snapshot(controller.get("pid")),
        "controller_sha256": controller.get("controller_sha256"),
        "request_sha256": controller.get("request_sha256"),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    proof = {
        "schema": "ds02.f3.assigned.f5.m101_t100.previsual-primary-namespace-preflight.v1",
        "fresh_id": "fresh182",
        "package_scope": {
            "assigned_worktree_family": "F3",
            "actual_case_family": "F5",
            "source_only": True,
            "science_payload_opened_or_hashed_by_source_agent": False,
            "new_case_credit": 0,
            "q_n_granted": False,
            "q_e_granted": False,
        },
        "identity": {
            "family_id": "F5",
            "case_id": CASE,
            "physical_case_id": PHYSICAL,
            "canonical_native_physical_condition_sha256": CANONICAL,
            "actual_typed_legacy_scope_sha256": LEGACY,
        },
        "counts": {
            **COUNTS,
            "total": PARTICLES,
            "solver_dimension": 3,
            "frames": FRAMES,
            "contact_sheets": 34,
            "keyframe_indices": [0, 100, 200, 300, 400, 500, 600, 700, 800],
        },
        "time_and_fields": {
            "xmf_frame_count": len(actual_times),
            "xmf_first_time_s": actual_times[0] if actual_times else None,
            "xmf_last_time_s": actual_times[-1] if actual_times else None,
            "xmf_time_sequence_sha256": hashlib.sha256(json.dumps(actual_times, separators=(",", ":")).encode()).hexdigest() if actual_times else None,
            "typed_time_evidence": {k: typed_time.get(k) for k in ("first_s", "last_s", "strictly_increasing")},
            "bed_time_evidence": {k: bed_time.get(k) for k in ("frame_count", "first_s", "last_s", "match", "strictly_increasing", "max_h5_xdmf_abs_difference_s")},
            "xmf_field_contract": field_contract,
            "coordinate_frame": xmf.get("coordinate_frame"),
        },
        "producer_lifecycle": stage_refs,
        "initial_qa": {
            "basic_placement_pass": chain["chain"]["initial_qa"].get("basic_placement_pass"),
            "precision_accepted": chain["chain"]["initial_qa"].get("precision_accepted"),
            "q_n_granted": False,
            "native_bed_marker_mk": chain.get("native_bed_marker_mk"),
            "source_mkbound": chain.get("source_mkbound"),
            "historical_precision_negative_retained": True,
            "historical_A_B_penetration_failures_retained": True,
        },
        "namespace_roles": {
            "native": {
                "condition_scope": CANONICAL,
                "physical_plan_scope": native_request.get("source_plan_physical_condition_sha256"),
                "raw_field_mask": native_mask,
                "source_definition_scope": None,
                "note": "Native condition/canonical-condition fields remain absent or null where the producer omitted them; physical and source-plan-physical roles are recorded from the native request without backfilling.",
            },
            "typed": {
                "legacy_scope": LEGACY,
                "scope_schema": "legacy-owner-scope.v0",
                "raw_field_mask": typed_mask,
                "q_i_status": typed_report.get("q_i_status"),
                "q_n_status": typed_report.get("q_n_status"),
                "note": "Typed conversion evidence is legacy scope and does not grant a canonical physical or numerical claim.",
            },
            "xmf": {
                "canonical_physical_scope": xmf.get("canonical_physical_condition_sha256"),
                "physical_scope": xmf.get("physical_condition_sha256"),
                "source_plan_physical_scope": xmf.get("source_plan_physical_condition_sha256"),
                "source_plan_file_scope": SOURCE_PLAN,
                "historical_legacy_scope": XMF_HISTORICAL_LEGACY,
                "raw_field_mask": xmf_mask,
                "manifest_status": xmf.get("status"),
                "visual_status": xmf.get("visual_status"),
            },
            "bed": {
                "source_definition_file_scope": SOURCE_DEF,
                "report_source_plan_physical_scope": bed_report.get("source_plan_physical_condition_sha256"),
                "raw_field_mask": bed_mask,
                "diagnostic_only": bed_report.get("diagnostic_only"),
                "repair_success": bed_report.get("repair_success"),
                "q_n_status": bed_report.get("q_n_status"),
                "note": "Bed footprint bins and UID checks are diagnostic evidence; they are not numerical acceptance thresholds.",
            },
            "source_definition": {
                "path": str(source_definition_path) if source_definition_path else None,
                "sha256": SOURCE_DEF,
                "role": "SourceDef file; independent from XMF canonical physical scope",
            },
            "source_plan_file": {
                "path": str(source_plan_path) if source_plan_path else None,
                "sha256": SOURCE_PLAN,
                "role": "source-plan JSON file; independent metadata role",
            },
            "trajectory_h5": {
                "path": str(xmf.get("trajectory_h5")),
                "producer_attested_sha256": H5_PRODUCER,
                "scope_schema": "legacy-owner-scope.v0",
                "source_agent_opened_or_hashed": False,
            },
        },
        "metadata_refs": static_refs,
        "render_previsual": render_snapshot(render_path, wrapper, controller),
        "runtime_binding": {
            "launch_owner": request.get("launch_owner"),
            "current_attempt_id": wrapper.get("current_attempt_id"),
            "reservation_id": wrapper.get("reservation_id"),
            "cpu_task_kind": request.get("cpu_task_kind"),
            "cpu_threads": wrapper.get("cpu_threads"),
            "environment_threads": wrapper.get("environment_threads"),
            "max_wall_seconds": wrapper.get("max_wall_seconds"),
            "expected_storage_bytes": request.get("estimated_storage_bytes"),
            "home_publish_cap_bytes": wrapper.get("home_publish_cap_bytes"),
            "home_free_floor_bytes": wrapper.get("home_free_floor_bytes"),
            "nvme_free_floor_bytes": wrapper.get("nvme_free_floor_bytes"),
            "resource_ledger_lock": wrapper.get("resource_ledger_lock"),
            "root_actual_launch_source": request.get("root_actual_launch_source"),
            "root_actual_launch_source_sha256": request.get("root_actual_launch_source_sha256"),
            "renderer_sha256": wrapper.get("renderer_sha256"),
            "future_render_hashes": {"receipt": None, "report": None},
        },
        "controller_identity": controller_identity,
        "limitations": [
            "Current render is recorded as a live/pending observation; a running receipt is not a terminal success.",
            "No personal contact-sheet or key-frame visual review is included in fresh182.",
            "Native/typed/XMF/bed producer receipts are metadata-only evidence; their exit codes do not grant Q-N, Q-E, precision, or production acceptance.",
            "Producer-attested H5/BI4/DAT/CSV values are copied as attestations only; source preparation did not open or hash those payloads.",
        ],
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    proof_path = metadata_dir / "M101_T100-previsual-primary-namespace-preflight.json"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof_path


def write_manifest(output_dir: Path) -> Path:
    files = []
    for rel in ["README.md", "build_fresh182.py", "validate_fresh182.py", "metadata/M101_T100-previsual-primary-namespace-preflight.json"]:
        path = output_dir / rel
        if not path.is_file():
            fail(f"package file missing before manifest: {path}")
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {
        "schema": "ds02.f3.fresh182.package-manifest.v1",
        "fresh_id": "fresh182",
        "package_manifest_excluded_from_own_hash": True,
        "files": files,
    }
    path = output_dir / "package-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    proof = build(args.output_dir)
    manifest = write_manifest(args.output_dir.resolve())
    print(json.dumps({"proof": str(proof), "manifest": str(manifest)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
