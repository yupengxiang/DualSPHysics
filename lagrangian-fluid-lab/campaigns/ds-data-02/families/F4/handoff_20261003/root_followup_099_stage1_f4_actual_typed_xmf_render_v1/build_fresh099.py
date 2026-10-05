#!/usr/bin/env python3
"""Build the F4 fresh099 typed-result to Root023 render handoff.

This is a metadata-only, repeatable poller.  It reads Root533 execution
receipts and conversion reports, plus the fresh098 JSON bindings.  It never
opens, copies, or hashes BI4/H5/VTK/CSV/DAT scientific payloads and it never
starts a conversion, XMF export, or render.  A later invocation can observe
new Root533 JSON receipts without creating a new attempt identity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = Path(__file__).resolve().parent

FRESH098 = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_098_stage1_f4_root530_typed_xmf_render_v1"
ROOT533 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actualnative514_frame0QA530_full1201_typed_NVMe_533"
ROOT547 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actualtyped533_full1201_normal_N3_XMF_547"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
ROOT023 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"

RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RENDERER = ROOT023 / "render.py"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
ROOT134_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"
PV_PYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
ENV = Path("/usr/bin/env")
MESA_JSON = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")

SCOPE = "root_followup_099_stage1_f4_actual_typed_xmf_render_v1"
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
STATIC_SUFFIXES = {"", ".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log"}

RENDERER_SHA = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
RESOURCE_HOME_GIB = 500
RESOURCE_NVME_GIB = 100
RESOURCE_STAGE_GIB = 24


def load_json(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload read refused: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_static(path: Path, known: dict[str, str]) -> str:
    path = Path(path).resolve()
    text_path = str(path)
    if text_path in known:
        return str(known[text_path])
    suffix = path.suffix.lower()
    if suffix in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload hash refused: {path}")
    if suffix not in STATIC_SUFFIXES:
        raise RuntimeError(f"non-static input hash refused: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path | None, known: dict[str, str]) -> dict[str, str] | None:
    if path is None:
        return None
    path = Path(path).resolve()
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": sha_static(path, known)}


def unique(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def safe_existing(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for raw in unique(paths):
        path = Path(raw)
        if not path.is_file():
            continue
        if path.suffix.lower() in RAW_SUFFIXES:
            continue
        result.append(path)
    return result


def load_fresh098_known_hashes() -> dict[str, str]:
    paths = sorted((FRESH098 / "requests").glob("*-full1201-render-fresh098-disabled.request.json"))
    if len(paths) != 24:
        raise RuntimeError(f"fresh098 render requests expected 24, found {len(paths)}")
    sample = load_json(paths[0])
    values = sample.get("input_sha256", {})
    return {str(Path(k).resolve()): str(v) for k, v in values.items()}


def fresh098_xmf_bindings() -> dict[str, tuple[Path, dict[str, Any], Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any], Path, dict[str, Any]]] = {}
    binding_paths = sorted((FRESH098 / "bindings").glob("*-xmf-binding.json"))
    if len(binding_paths) != 24:
        raise RuntimeError(f"fresh098 XMF bindings expected 24, found {len(binding_paths)}")
    for binding_path in binding_paths:
        binding = load_json(binding_path)
        case_id = str(binding["case_id"])
        request_path = FRESH098 / "requests" / f"{case_id}-full1201-xmf-fresh098-disabled.request.json"
        request = load_json(request_path)
        if case_id in result:
            raise RuntimeError(f"duplicate fresh098 case {case_id}")
        result[case_id] = (binding_path.resolve(), binding, request_path.resolve(), request)
    return result


def root533_requests() -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    paths = sorted(ROOT533.glob("*-typed-request.json"))
    if len(paths) != 24:
        raise RuntimeError(f"Root533 typed requests expected 24, found {len(paths)}")
    for path in paths:
        request = load_json(path)
        case_id = str(request["case_id"])
        if case_id in result:
            raise RuntimeError(f"duplicate Root533 case {case_id}")
        result[case_id] = (path.resolve(), request)
    return result


def root547_xmf_source(
    case_id: str,
    fallback_binding_path: Path,
    fallback_binding: dict[str, Any],
    fallback_request_path: Path,
    fallback_request: dict[str, Any],
) -> tuple[Path, dict[str, Any], Path, dict[str, Any], bool]:
    """Return Root547's actual XMF binding/request when Root has registered it.

    Fresh098 remains the immutable source fallback.  Root547 may only have a
    subset of the 24 cases registered at a given poll, so the fallback is
    retained per case until a Root547 request exists.
    """
    request_path = ROOT547 / f"{case_id}-xmf-request.json"
    binding_path = ROOT547 / "bindings" / f"{case_id}-actual-xmf-binding.json"
    if request_path.is_file() and binding_path.is_file():
        return (
            binding_path.resolve(),
            load_json(binding_path),
            request_path.resolve(),
            load_json(request_path),
            True,
        )
    return fallback_binding_path, fallback_binding, fallback_request_path, fallback_request, False


def find_one(root: Path, attempt_id: str, filename: str) -> Path | None:
    direct = root / attempt_id / filename
    if direct.is_file():
        return direct.resolve()
    matches = sorted(root.glob(f"*{attempt_id}*/{filename}"))
    if len(matches) > 1:
        raise RuntimeError(f"multiple {filename} artifacts for {attempt_id}")
    return matches[0].resolve() if matches else None


def lifecycle_summary(report: dict[str, Any]) -> dict[str, Any]:
    identity = report.get("typed_identity") or {}
    ledger = identity.get("initial_exclusion_ledger") or {}
    lifecycle = report.get("lifecycle") or {}

    def event_count(value: Any) -> int:
        if isinstance(value, (list, dict)):
            return len(value)
        return 0

    return {
        "contract": lifecycle.get("contract"),
        "identity_key": identity.get("key"),
        "zone_source": identity.get("zone_source"),
        "observed_mks": identity.get("observed_mks"),
        "observed_types": identity.get("observed_types"),
        "mass_semantics": identity.get("mass_semantics"),
        "fluid_blocks": [
            {
                key: block.get(key)
                for key in ("begin", "count", "mk", "mkfluid", "tag", "type")
                if key in block
            }
            for block in identity.get("blocks", [])
            if isinstance(block, dict) and block.get("tag") == "fluid"
        ],
        "initial_exclusion_ledger": {
            "count": ledger.get("count"),
            "mass_kg": ledger.get("mass_kg"),
            "mk_counts": ledger.get("mk_counts"),
            "type_counts": ledger.get("type_counts"),
            "semantics": ledger.get("semantics"),
            "ids_sha256_omitted": True,
        },
        "first_missing_frame_by_mk": lifecycle.get("first_missing_frame_by_mk", {}),
        "first_missing_frame_by_type": lifecycle.get("first_missing_frame_by_type", {}),
        "transient_missing_frame_count": lifecycle.get("transient_missing_frame_count"),
        "transient_missing_by_mk_event_count": event_count(lifecycle.get("transient_missing_by_mk_frame_events")),
        "transient_missing_by_type_event_count": event_count(lifecycle.get("transient_missing_by_type_frame_events")),
        "introduced_id_count": event_count(lifecycle.get("introduced_ids")),
        "missing_semantics": lifecycle.get("missing_semantics"),
        "open_birth_adaptive_multi_piece": lifecycle.get("open_birth_adaptive_multi_piece"),
        "padding_or_reclassification": "forbidden; observed lifecycle retained exactly",
    }


def partvtk_summary(report: dict[str, Any]) -> dict[str, Any]:
    validation = report.get("partvtk_validation") or {}
    frames = validation.get("frames") or []
    samples = []
    if isinstance(frames, list):
        if len(frames) <= 3:
            chosen = frames
        else:
            chosen = [frames[0], frames[len(frames) // 2], frames[-1]]
        for row in chosen:
            if not isinstance(row, dict):
                continue
            samples.append({
                "frame": row.get("frame"),
                "rows": row.get("rows"),
                "expected_rows": row.get("expected_rows"),
                "passed": row.get("passed"),
                "partvtk_time": row.get("partvtk_time"),
                "type_counts": row.get("type_counts"),
                "identity_type_mk_exact": row.get("identity_type_mk_exact"),
            })
    return {
        "all_passed": validation.get("all_passed"),
        "sample_count": len(samples),
        "samples": samples,
        "csv_paths_omitted": True,
    }


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    solver = report.get("solver_dimension") or {}
    time = report.get("time_evidence") or {}
    units = report.get("units") or {}
    return {
        "schema": report.get("schema"),
        "conversion_status": report.get("conversion_status"),
        "frames": report.get("frames"),
        "particles": report.get("particles"),
        "solver_dimension": {
            "solver_dimension": solver.get("solver_dimension"),
            "run_out_dimensions": solver.get("run_out_dimensions"),
            "xml_data2d": solver.get("xml_data2d"),
        },
        "time_evidence": {
            "first_s": time.get("first_s"),
            "last_s": time.get("last_s"),
            "strictly_increasing": time.get("strictly_increasing"),
            "source": time.get("source"),
        },
        "units": {
            key: units.get(key)
            for key in ("density", "mass", "position", "pressure", "time", "velocity")
            if key in units
        },
        "typed_identity_lifecycle": lifecycle_summary(report),
        "partvtk_validation": partvtk_summary(report),
        "conversion_claim": report.get("conversion_claim"),
        "q_i_status": report.get("q_i_status"),
        "q_n_status": report.get("q_n_status"),
        "production_eligibility": report.get("production_eligibility"),
        "unsupported_contract": {
            "dynamic_metadata": (report.get("unsupported_contract") or {}).get("dynamic_metadata"),
            "open_birth_adaptive": (report.get("unsupported_contract") or {}).get("open_birth_adaptive"),
        },
        "raw_payload_rehashed_by_source": False,
        "report_h5_output_digest_copied_by_source": False,
    }


def report_is_complete(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    solver = report.get("solver_dimension") or {}
    time = report.get("time_evidence") or {}
    validation = report.get("partvtk_validation") or {}
    return bool(
        report.get("conversion_status") == "completed"
        and report.get("frames") == 1201
        and report.get("particles") == 83233
        and solver.get("solver_dimension") == 3
        and time.get("strictly_increasing") is True
        and validation.get("all_passed") is True
    )


def root533_state(case_id: str, request_path: Path, request: dict[str, Any], known: dict[str, str]) -> dict[str, Any]:
    attempt_id = str(request["attempt_id"])
    case_root = DATA / "families/F4" / case_id
    receipt_path = find_one(case_root, attempt_id, "execution-receipt.json")
    receipt = load_json(receipt_path) if receipt_path else None
    receipt_status = receipt.get("status") if receipt else "WAIT"
    returncode = receipt.get("returncode") if receipt else None
    output_root = Path(str(receipt.get("output_root"))).resolve() if receipt and receipt.get("output_root") else case_root / attempt_id
    report_path = (output_root / "conversion-report.json") if (output_root / "conversion-report.json").is_file() else None
    if report_path is None:
        report_matches = sorted(case_root.glob(f"*{attempt_id}*/conversion-report.json"))
        if len(report_matches) > 1:
            raise RuntimeError(f"multiple Root533 reports for {case_id}")
        report_path = report_matches[0].resolve() if report_matches else None
    report = load_json(report_path) if report_path else None
    complete_receipt = receipt_status == "completed" and returncode == 0
    if complete_receipt and report_is_complete(report):
        typed_status = "completed_reported"
    elif complete_receipt and report is None:
        typed_status = "completed_receipt_missing_report"
    elif complete_receipt:
        typed_status = "completed_report_invalid"
    elif receipt_status == "running":
        typed_status = "running"
    elif receipt is None:
        typed_status = "WAIT"
    else:
        typed_status = f"receipt_{receipt_status}"
    owner_path = Path(str(request["owner_metadata"])).resolve()
    return {
        "case_id": case_id,
        "attempt_id": attempt_id,
        "request": ref(request_path, known),
        "receipt": ref(receipt_path, known),
        "report": ref(report_path, known),
        "receipt_status": receipt_status,
        "receipt_returncode": returncode,
        "typed_status": typed_status,
        "output_root": str(output_root),
        "owner_metadata": ref(owner_path, known),
        "physical_condition_sha256": request.get("physical_condition_sha256"),
        "source_owner_physical_condition_sha256": request.get("source_owner_physical_condition_sha256"),
        "converter_scope_schema": (request.get("actual_converter_physical_scope") or {}).get("schema"),
        "converter_scope_semantic_status": (request.get("actual_converter_physical_scope") or {}).get("semantic_binding_status"),
        "report_summary": compact_report(report) if report else None,
        "future_typed_product_hashes": {
            "trajectory_h5": None,
            "conversion_report": None,
            "execution_receipt": None,
        },
        "source_did_not_read_or_hash_payload": True,
    }


def xmf_state(
    case_id: str,
    xmf_request_path: Path,
    xmf_request: dict[str, Any],
    known: dict[str, str],
    fresh098_request_path: Path | None = None,
    actual_binding_path: Path | None = None,
) -> dict[str, Any]:
    outputs = xmf_request.get("expected_outputs") or {}
    output_hint = outputs.get("output_root") or outputs.get("manifest") or outputs.get("xdmf")
    if not output_hint:
        raise RuntimeError(f"XMF request has no output hint for {case_id}")
    output_root = Path(str(output_hint)).resolve()
    if output_root.suffix.lower() in {".json", ".xmf"}:
        output_root = output_root.parent
    attempt_id = str(xmf_request.get("attempt_id", ""))
    case_root = DATA / "families/F4" / case_id
    receipt_path = find_one(case_root, attempt_id, "execution-receipt.json") if attempt_id else None
    if receipt_path is None:
        candidate = output_root / "execution-receipt.json"
        receipt_path = candidate if candidate.is_file() else None
    receipt = load_json(receipt_path) if receipt_path and receipt_path.is_file() else None
    manifest_path = output_root / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else None
    receipt_complete = bool(receipt and receipt.get("status") == "completed" and receipt.get("returncode") == 0)
    if receipt_complete and manifest is not None:
        status = "completed/0_with_manifest"
    elif receipt and receipt.get("status") == "running":
        status = "running"
    elif receipt_complete:
        status = "completed/0_missing_manifest"
    elif receipt is None:
        status = "WAIT"
    else:
        status = f"receipt_{receipt.get('status')}"
    manifest_summary = None
    if manifest is not None:
        manifest_summary = {
            "schema": manifest.get("schema"),
            "frames": manifest.get("frames", manifest.get("frame_count")),
            "particles": manifest.get("particles", manifest.get("particle_count")),
            "time_window_s": manifest.get("time_window_s"),
            "payload_hashes_read_by_source": False,
        }
    return {
        "case_id": case_id,
        "upstream_xmf_request": ref(xmf_request_path, known),
        "fresh098_xmf_request": ref(fresh098_request_path or xmf_request_path, known),
        "root547_actual_binding": ref(actual_binding_path, known),
        "attempt_id": attempt_id,
        "expected_output_root": str(output_root),
        "case_xmf": str(output_root / "case.xmf"),
        "manifest_path": str(manifest_path),
        "receipt_path": str(output_root / "execution-receipt.json"),
        "receipt": ref(receipt_path, known),
        "manifest": ref(manifest_path, known),
        "status": status,
        "manifest_summary": manifest_summary,
        "future_xmf_hashes": {"case_xmf": None, "manifest": None, "execution_receipt": None},
        "source_did_not_read_or_hash_payload": True,
    }


def request_base(
    *,
    case_id: str,
    attempt_id: str,
    command: list[str],
    inputs: list[Path],
    deferred: list[Path],
    expected_outputs: dict[str, Any],
    known: dict[str, str],
    disabled_reason: str,
) -> dict[str, Any]:
    inputs = safe_existing(inputs)
    for path in inputs:
        if path.suffix.lower() in RAW_SUFFIXES:
            raise RuntimeError(f"raw input accidentally selected: {path}")
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 14400,
        "estimated_storage_bytes": 12 * 1024**3,
        "cwd": str(INTEGRATION / "lagrangian-fluid-lab"),
        "worktree_root": str(WORKTREE),
        "command": command,
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha_static(path, known) for path in inputs},
        "deferred_input_files": [str(Path(path).resolve()) for path in deferred],
        "deferred_input_sha256": {str(Path(path).resolve()): None for path in deferred},
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "source_only": True,
        "status": "source_only_disabled",
        "disabled_reason": disabled_reason,
        "independent_case_count_increment": 0,
        "root_review_required": True,
        "scope_id": SCOPE,
        "precision_status": "not_accepted",
        "production_approval": "none",
        "q_n_status": "not_assessed",
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "expected_outputs": expected_outputs,
    }


def collect_case_static_inputs(
    case_id: str,
    xmf_binding: dict[str, Any],
    xmf_binding_path: Path,
    xmf_request_path: Path,
    root533_request_path: Path,
    root533_request: dict[str, Any],
    root533: dict[str, Any],
    render_binding_path: Path,
    known: dict[str, str],
) -> list[Path]:
    gencase = xmf_binding.get("gencase_actual_evidence") or {}
    native_recipe = xmf_binding.get("root514_native_recipe") or {}
    frame0 = xmf_binding.get("root530_frame0_audit") or {}
    candidates: list[Path] = [
        RUNTIME,
        STRICT,
        RESOURCE,
        ROOT230_ENTRY,
        ROOT230_HOME,
        ROOT230_CONTRACT,
        ROOT134_GPU,
        ROOT023 / "README.md",
        RENDERER,
        ENV,
        MESA_JSON,
        PV_PYTHON,
        xmf_binding_path,
        xmf_request_path,
        root533_request_path,
        render_binding_path,
        FRESH098 / "render/camera-spec.json",
        FRESH098 / "render/contact-page-keys.json",
        FRESH098 / "render/n3-vector-spec.json",
    ]
    for key in ("source_owner", "actual_owner_metadata", "native_frame0_binding"):
        value = xmf_binding.get(key)
        if isinstance(value, dict) and value.get("path"):
            candidates.append(Path(str(value["path"])))
    for key in ("generated_xml", "prepared_input_report", "gencase_receipt"):
        if gencase.get(key):
            candidates.append(Path(str(gencase[key])))
    if isinstance(native_recipe.get("receipt"), dict) and native_recipe["receipt"].get("path"):
        candidates.append(Path(str(native_recipe["receipt"]["path"])))
    for key in ("receipt", "report"):
        value = frame0.get(key)
        if isinstance(value, dict) and value.get("path"):
            candidates.append(Path(str(value["path"])))
    if root533.get("receipt"):
        candidates.append(Path(str(root533["receipt"]["path"])))
    if root533.get("report"):
        candidates.append(Path(str(root533["report"]["path"])))
    if root533.get("owner_metadata"):
        candidates.append(Path(str(root533["owner_metadata"]["path"])))
    # Keep the parameter explicit so future changes cannot silently hash a raw input.
    _ = root533_request
    _ = known
    return safe_existing(candidates)


def main() -> None:
    for directory in (PACKAGE / "bindings", PACKAGE / "requests", PACKAGE / "evidence", PACKAGE / "metadata"):
        directory.mkdir(parents=True, exist_ok=True)
    known = load_fresh098_known_hashes()
    xmf_cases = fresh098_xmf_bindings()
    typed_requests = root533_requests()
    typed_rows: list[dict[str, Any]] = []
    xmf_rows: list[dict[str, Any]] = []
    case_state: dict[str, dict[str, Any]] = {}
    for case_id in sorted(xmf_cases):
        fresh098_binding_path, fresh098_binding, fresh098_request_path, fresh098_request = xmf_cases[case_id]
        xmf_binding_path, xmf_binding, xmf_request_path, xmf_request, root547_registered = root547_xmf_source(
            case_id,
            fresh098_binding_path,
            fresh098_binding,
            fresh098_request_path,
            fresh098_request,
        )
        if case_id not in typed_requests:
            raise RuntimeError(f"Root533 request missing {case_id}")
        typed_request_path, typed_request = typed_requests[case_id]
        root533 = root533_state(case_id, typed_request_path, typed_request, known)
        xmf = xmf_state(
            case_id,
            xmf_request_path,
            xmf_request,
            known,
            fresh098_request_path=fresh098_request_path,
            actual_binding_path=xmf_binding_path if root547_registered else None,
        )
        xmf["root547_registered"] = root547_registered
        typed_row = {
            **root533,
            "request_physical_condition_sha256": typed_request.get("physical_condition_sha256"),
            "source_owner_physical_condition_sha256": typed_request.get("source_owner_physical_condition_sha256"),
            "expected_contract": {
                "frames": typed_request.get("expected_frames", 1201),
                "particles": typed_request.get("expected_particles", 83233),
                "dimension": 3,
                "time_window_s": [0.0, 1.2],
                "save_interval_s": 0.001,
            },
            "vector_contract": {
                "semantic_type": "N3",
                "components": ["vx", "vy", "vz"],
                "field": "velocity",
                "coordinate_frame": "DualSPHysics Cartesian (x,y,z)",
                "basis": "fresh098 Root023/XMF contract; no trajectory payload opened by this builder",
            },
            "future_typed_product_hashes": {"trajectory_h5": None, "conversion_report": None, "execution_receipt": None},
        }
        typed_rows.append(typed_row)
        xmf_rows.append(xmf)
        case_state[case_id] = {
            "fresh098_binding_path": fresh098_binding_path,
            "fresh098_binding": fresh098_binding,
            "fresh098_request_path": fresh098_request_path,
            "fresh098_request": fresh098_request,
            "xmf_binding_path": xmf_binding_path,
            "xmf_binding": xmf_binding,
            "xmf_request_path": xmf_request_path,
            "xmf_request": xmf_request,
            "root547_registered": root547_registered,
            "typed_request_path": typed_request_path,
            "typed_request": typed_request,
            "typed": root533,
            "typed_row": typed_row,
            "xmf": xmf,
        }

    typed_evidence_path = PACKAGE / "evidence/root533-conversion-report-snapshot.json"
    xmf_evidence_path = PACKAGE / "evidence/fresh098-xmf-result-snapshot.json"
    dump(typed_evidence_path, {
        "schema": "ds02.f4.fresh099.root533-conversion-report-json-evidence.v1",
        "claim_boundary": "Root533 receipt and conversion-report JSON are polled as actual evidence. A completed/0 receipt without a valid report remains incomplete. Reported fluid omissions are retained; this package does not pad IDs, reclassify Mk/Type, or recompute an H5 digest.",
        "cases": typed_rows,
        "case_count": len(typed_rows),
        "vector_contract": {"semantic_type": "N3", "components": ["vx", "vy", "vz"], "source_builder_payload_read": False},
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    })
    dump(xmf_evidence_path, {
        "schema": "ds02.f4.fresh099.fresh098-xmf-json-state.v1",
        "claim_boundary": "fresh098 XMF remains the immutable source request; when Root547 has registered an actual XMF request/binding, this snapshot polls only its JSON receipt/manifest. No XMF export is launched here and all XMF hashes remain null.",
        "cases": xmf_rows,
        "case_count": len(xmf_rows),
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    })

    request_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    for case_id in sorted(case_state):
        state = case_state[case_id]
        fresh098_binding_path = state["fresh098_binding_path"]
        fresh098_request_path = state["fresh098_request_path"]
        xmf_binding_path = state["xmf_binding_path"]
        xmf_binding = state["xmf_binding"]
        xmf_request_path = state["xmf_request_path"]
        xmf_request = state["xmf_request"]
        typed_request_path = state["typed_request_path"]
        typed_request = state["typed_request"]
        typed = state["typed"]
        xmf = state["xmf"]
        root547_registered = state["root547_registered"]
        render_binding_path = PACKAGE / "bindings" / f"{case_id}-render-binding.json"
        physical = xmf_binding.get("physical_binding")
        if not isinstance(physical, dict):
            raise RuntimeError(f"missing physical binding {case_id}")
        actual_scope = xmf_binding.get("actual_converter_scope") or {}
        source_owner = xmf_binding.get("source_owner")
        owner_metadata = xmf_binding.get("actual_owner_metadata")
        frame0 = xmf_binding.get("root530_frame0_audit")
        render_root = DATA / "families/F4" / case_id / f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh099"
        xmf_outputs = xmf_request.get("expected_outputs") or {}
        binding = {
            "schema": "ds02.f4.fresh099.root023-render-binding.v1",
            "fresh_id": "fresh099",
            "scope_id": SCOPE,
            "case_id": case_id,
            "physical_case_id": case_id,
            "physical_binding": physical,
            "physical_condition_sha256": typed_request.get("physical_condition_sha256"),
            "source_owner_physical_condition_sha256": typed_request.get("source_owner_physical_condition_sha256"),
            "source_physical_condition_sha256": xmf_binding.get("source_physical_condition_sha256"),
            "source_plan_condition_sha256": xmf_binding.get("source_plan_condition_sha256"),
            "actual_converter_scope": actual_scope,
            "scope_separation": {
                "source_owner_and_source_plan_are_retained": True,
                "root533_legacy_scope_is_actual_converter_scope": True,
                "source_owner_sha256_must_not_be_reused": True,
                "semantic_binding_status": actual_scope.get("semantic_binding_status", "legacy scope only"),
            },
            "source_owner": source_owner,
            "actual_owner_metadata": owner_metadata,
            "fresh098_xmf_request": ref(fresh098_request_path, known),
            "fresh098_xmf_binding": ref(fresh098_binding_path, known),
            "actual_root547_xmf_request": ref(xmf_request_path, known) if root547_registered else None,
            "actual_root547_xmf_binding": ref(xmf_binding_path, known) if root547_registered else None,
            "fresh098_typed_request": ref(typed_request_path, known),
            "root530_frame0_evidence": frame0,
            "root533_typed_evidence": {
                "snapshot": ref(typed_evidence_path, known),
                "case_status": typed["typed_status"],
                "receipt": typed["receipt"],
                "conversion_report": typed["report"],
                "summary": typed["report_summary"],
                "reported_frames": (typed["report_summary"] or {}).get("frames") if typed["report_summary"] else None,
                "reported_last_time_s": ((typed["report_summary"] or {}).get("time_evidence") or {}).get("last_s") if typed["report_summary"] else None,
                "reported_dimension": ((typed["report_summary"] or {}).get("solver_dimension") or {}).get("solver_dimension") if typed["report_summary"] else None,
                "n3_vector_contract": {"semantic_type": "N3", "components": ["vx", "vy", "vz"], "field": "velocity"},
                "source_did_not_read_or_hash_h5": True,
            },
            "typed_lifecycle_policy": {
                "preserve_reported_mk_type_uid_lifecycle": True,
                "observed_fluid_exclusions": ((typed["report_summary"] or {}).get("typed_identity_lifecycle") if typed["report_summary"] else None),
                "no_padding": True,
                "no_reclassification": True,
                "no_mass_rescale": True,
            },
            "xmf_stage": xmf,
            "expected_native_contract": {
                "frames": 1201,
                "time_window_s": [0.0, 1.2],
                "save_interval_s": 0.001,
                "particles": 83233,
                "fluid_particles": 59072,
                "dimension": 3,
                "vector_semantic_type": "N3",
                "typed_mk_type_uid_is_report_evidence_only": True,
            },
            "renderer": {
                "worker": str(RENDERER),
                "worker_sha256": RENDERER_SHA,
                "contract": "Root023 full native reader; scan all 1201 saved frames and retain all native fields",
                "pvpython": str(PV_PYTHON),
                "environment": {
                    "VTK_SMP_MAX_THREADS": "2",
                    "LP_NUM_THREADS": "2",
                    "OMP_NUM_THREADS": "2",
                    "LIBGL_ALWAYS_SOFTWARE": "1",
                    "MESA_LOADER_DRIVER_OVERRIDE": "llvmpipe",
                    "QT_QPA_PLATFORM": "offscreen",
                    "VTK_DEFAULT_OPENGL_WINDOW": "vtkEGLRenderWindow",
                    "__EGL_VENDOR_LIBRARY_FILENAMES": str(MESA_JSON),
                },
                "all_temporal_frames_required": True,
                "contact_pages": 51,
            },
            "render_output_root": str(render_root),
            "render_outputs_future_hashes": {
                "case_pvsm": None,
                "contact_pages": None,
                "gif": None,
                "report": None,
                "execution_receipt": None,
            },
            "precision_status": "not_accepted",
            "production_approval": "none",
            "q_n_status": "not_assessed",
            "arrays_read_by_source": False,
            "jobs_started_by_source": False,
            "shared_registry_write_by_source": False,
        }
        dump(render_binding_path, binding)

        static_inputs = collect_case_static_inputs(
            case_id,
            xmf_binding,
            xmf_binding_path,
            xmf_request_path,
            typed_request_path,
            typed_request,
            typed,
            render_binding_path,
            known,
        )
        static_inputs = safe_existing(static_inputs + [fresh098_binding_path, fresh098_request_path])
        render_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh099"
        manifest_path = Path(str(xmf.get("manifest_path"))).resolve()
        command = [
            str(ENV),
            "VTK_SMP_MAX_THREADS=2",
            "LP_NUM_THREADS=2",
            "LIBGL_ALWAYS_SOFTWARE=1",
            "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe",
            "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
            "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow",
            "QT_QPA_PLATFORM=offscreen",
            "OMP_NUM_THREADS=2",
            str(PV_PYTHON),
            "--force-offscreen-rendering",
            str(RENDERER),
            "--manifest",
            str(manifest_path),
            "--output-dir",
            "{attempt_root}",
        ]
        deferred = [
            Path(str(xmf.get("case_xmf", manifest_path.with_name("case.xmf")))),
            manifest_path,
            Path(str(xmf.get("receipt_path", manifest_path.with_name("execution-receipt.json")))),
            DATA / "families/F4" / case_id / typed["attempt_id"] / "trajectory.h5",
            DATA / "families/F4" / case_id / typed["attempt_id"] / "conversion-report.json",
            DATA / "families/F4" / case_id / typed["attempt_id"] / "execution-receipt.json",
            render_root / "case.pvsm",
            render_root / "full_saved_animation.gif",
            render_root / "paraview-full-animation-report.json",
            render_root / "execution-receipt.json",
        ]
        request_path = PACKAGE / "requests" / f"{case_id}-full1201-render-fresh099-disabled.request.json"
        request = request_base(
            case_id=case_id,
            attempt_id=render_attempt,
            command=command,
            inputs=static_inputs,
            deferred=deferred,
            expected_outputs={
                "output_root": str(render_root),
                "case_pvsm": str(render_root / "case.pvsm"),
                "full_saved_animation_gif": str(render_root / "full_saved_animation.gif"),
                "report": str(render_root / "paraview-full-animation-report.json"),
                "execution_receipt": str(render_root / "execution-receipt.json"),
                "all_sha256": None,
            },
            known=known,
            disabled_reason="Root must independently settle Root533 typed conversion with a valid 1201-frame 3-D conversion report, then complete fresh098 XMF export. This request is only a disabled Root023 full-frame continuation; it does not relaunch typed/XMF and it preserves every reported Mk/Type/UID exclusion.",
        )
        request.update({
            "physical_case_id": case_id,
            "physical_condition_sha256": typed_request.get("physical_condition_sha256"),
            "source_owner_physical_condition_sha256": typed_request.get("source_owner_physical_condition_sha256"),
            "physical_window_s": [0.0, 1.2],
            "expected_frames": 1201,
            "expected_particles": 83233,
            "expected_contact_pages": 51,
            "vector_semantic_type": "N3",
            "depends_on_attempts": [typed["attempt_id"], str(xmf.get("attempt_id") or xmf_request.get("attempt_id"))],
            "typed_stage_is_not_relaunched": True,
            "xmf_stage_is_not_relaunched": True,
            "typed_gate": {
                "status": typed["typed_status"],
                "requires_root533_reported_frames": 1201,
                "requires_root533_reported_particles": 83233,
                "requires_solver_dimension": 3,
                "requires_strictly_increasing_time": True,
                "receipt_only_is_insufficient": True,
                "observed_fluid_exclusions_are_preserved": True,
            },
            "xmf_gate": {
                "status": xmf["status"],
                "requires_fresh098_xmf_completed0_and_manifest": True,
                "future_hashes": {"case_xmf": None, "manifest": None, "execution_receipt": None},
            },
            "render_binding": ref(render_binding_path, known),
            "typed_evidence": ref(typed_evidence_path, known),
            "xmf_evidence": ref(xmf_evidence_path, known),
            "future_sha256_values": "null until Root independently completes XMF and Root023 render",
        })
        dump(request_path, request)
        request_rows.append({
            "case_id": case_id,
            "kind": "root023_render",
            "path": str(request_path),
            "sha256": sha_static(request_path, known),
            "launch_allowed": False,
            "typed_status": typed["typed_status"],
            "xmf_status": xmf["status"],
        })
        case_rows.append({
            "case_id": case_id,
            "typed_status": typed["typed_status"],
            "xmf_status": xmf["status"],
            "typed_report": typed["report"],
            "typed_lifecycle": ((typed["report_summary"] or {}).get("typed_identity_lifecycle") if typed["report_summary"] else None),
            "render_binding": str(render_binding_path),
            "render_request": str(request_path),
            "render_output_hash": None,
        })

    typed_counts: dict[str, int] = {}
    for row in typed_rows:
        typed_counts[row["typed_status"]] = typed_counts.get(row["typed_status"], 0) + 1
    xmf_counts: dict[str, int] = {}
    for row in xmf_rows:
        xmf_counts[row["status"]] = xmf_counts.get(row["status"], 0) + 1
    dump(PACKAGE / "requests/index.json", {
        "schema": "ds02.f4.fresh099-render-request-index.v1",
        "scope_id": SCOPE,
        "family_id": "F4",
        "case_count": 24,
        "request_count": len(request_rows),
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "typed_status_counts_at_build": typed_counts,
        "xmf_status_counts_at_build": xmf_counts,
        "requests": request_rows,
        "future_output_hashes": None,
    })
    dump(PACKAGE / "metadata/typed-lifecycle-contract.json", {
        "schema": "ds02.f4.fresh099.typed-lifecycle-contract.v1",
        "typed_report_is_authoritative_for_observed_lifecycle": True,
        "vector_semantic_type": "N3",
        "identity_key": "(Zone,Idp)",
        "observed_mk_type_partition_is_retained": True,
        "fluid_exclusions": "first_missing_frame_by_mk/type and transient_missing_frame_count are copied from each Root533 report; no ID padding or Mk/Type reclassification",
        "initial_exclusion_ledger_ids_sha256": "omitted_by_source_builder",
        "mass_rescaling": "forbidden",
        "source_payload_read_or_hash": False,
    })
    dump(PACKAGE / "source-binding.json", {
        "schema": "ds02.f4.fresh099-source-binding.v1",
        "scope_id": SCOPE,
        "family_id": "F4",
        "claim_boundary": "Polls Root533 JSON conversion evidence and prepares disabled Root023 render requests. Root533/XMF/render products remain Root-owned; source builder performs no launch and no scientific payload read/hash.",
        "case_count": len(case_rows),
        "independent_case_count_increment": 0,
        "root533_evidence": str(typed_evidence_path),
        "xmf_evidence": str(xmf_evidence_path),
        "typed_lifecycle_contract": str(PACKAGE / "metadata/typed-lifecycle-contract.json"),
        "requests_index": str(PACKAGE / "requests/index.json"),
        "cases": case_rows,
        "resource_window": ref(RESOURCE, known),
        "root230_policy": {
            "entry": ref(ROOT230_ENTRY, known),
            "home_policy": ref(ROOT230_HOME, known),
            "contract": ref(ROOT230_CONTRACT, known),
            "gpu_policy": ref(ROOT134_GPU, known),
            "home_free_gib_floor": RESOURCE_HOME_GIB,
            "nvme_free_gib_floor": RESOURCE_NVME_GIB,
            "nvme_peak_gib": RESOURCE_STAGE_GIB,
            "conversion_concurrency_cap": 2,
        },
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    })
    print(json.dumps({
        "package": str(PACKAGE),
        "case_count": len(case_rows),
        "render_request_count": len(request_rows),
        "typed_status_counts": typed_counts,
        "xmf_status_counts": xmf_counts,
        "future_hashes": None,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
