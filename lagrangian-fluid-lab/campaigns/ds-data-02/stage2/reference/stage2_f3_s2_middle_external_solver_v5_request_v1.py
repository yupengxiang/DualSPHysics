#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Prepare the F3-S2 dp=.006 same-CFL external-solver request.

This forward-only builder has two deliberate stages:

* ``--build-source-card`` records the completed ROOT086 GenCase, ROOT093
  support, and ROOT153 staging evidence.  It reads only bounded JSON/XML
  metadata and ``stat(2)`` for the generated BI4 and forcing copy.  It never
  opens either payload.
* ``--build-request`` delegates the immutable shared v5 request writer after
  the parent has supplied the generated-BI4 SHA observed after reservation.
  The forcing SHA must also be supplied explicitly (the already verified
  ROOT086/current-control SHA).  Without both real 64-hex values no runnable
  request is emitted.

The resulting request remains development/UNKNOWN.  It requests one F3-S2
middle dp=.006 same-CFL full-window canary with the exact ROOT153 window and
``tout=.01``.  GPU selection, reservation, payload hashing, materialization,
launch, terminal RunPARTs/Run.out/DtAllInfo evidence, and charging belong to
the parent v5 guard.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
TMAX = "8.350016881886734"
TOUT = "0.01"
SOURCE_CONTROL_SHA = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
SOURCE_XML_SHA = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
MIDDLE_XML_SHA = "3ae2aae572b0fc8cb0687e0590b0fb1762af61212d037da603d4bc8326a8ae9d"
ROOT086_RECEIPT_SHA = "68ce1e593c568941af8ffadcf37949a1a53714f2e9b99f203b715ed47931e14f"
ROOT093_SUPPORT_SHA = "69a9e39e4b4fa73b24e4431224e2c7e2090052e0604f13b248fdd390dd1f16f6"
ROOT153_PROOF_SHA = "e94f6f93f6864740a79328a2786d86cebbbbd2c69b730432bcea8a598e0fa574"
ROOT153_REPORT_SHA = "2569c320a72c43081fb95c6881e53106077395448c0793d1255e9e4e775eecca"
MIDDLE_BI4_BYTES = 9_227_118
MIDDLE_CONTROL_BYTES = 14_377_599
MIDDLE_FLUID_COUNT = 67_500
MIDDLE_FIXED_COUNT = 111_708
MIDDLE_SAMPLE_MASS_KG = 14.58
OWNER_MASS_KG = 14.58
HEX64 = re.compile(r"^[0-9a-f]{64}$")

MIDDLE_ROOT = DATA_ROOT / "families/F3/F3_S2_P1200_AY0750_MATCHED_SOURCE_GENCASE_ROOT_086" / "f3-s2-source-clone-gencase-v1-root-086-001-root-forward-030-001"
MIDDLE_RECEIPT = MIDDLE_ROOT / "execution-receipt.json"
MIDDLE_XML = MIDDLE_ROOT / "generated/F3_S2_P1200_AY0750_MATCHED.xml"
MIDDLE_BI4 = MIDDLE_ROOT / "generated/F3_S2_P1200_AY0750_MATCHED.bi4"
MIDDLE_CONTROL = MIDDLE_ROOT / "generated/CaseSloshingAccData.csv"
SOURCE_XML = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"
SOURCE_CONTROL = DATA_ROOT / "families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/CaseSloshingAccData.csv"
MIDDLE_SUPPORT = DATA_ROOT / "families/F3/F3_S2_ROOT086_GUARDED_VTK_SUPPORT_V2_ROOT_093/f3-s2-root086-vtk-support-qa-v2-root-093-001-root-forward-030-001/f3-s2-root086-vtk-support-qa-v2.json"
ROOT153_PROOF = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_MIDDLE_STAGING_ACTUAL_METADATA_ROOT_VERIFICATION_153.json"
ROOT153_REPORT = DATA_ROOT / "families/F3/F3_S2_MATCHED_MIDDLE_CONTROL_COST_QA_V1_ROOT_153/f3-s2-matched-middle-control-cost-qa-v1-root-153-001-root-forward-030-001/report/f3_s2_matched_middle_control_cost_qa_v1.json"
ROOT153_REQUEST = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-matched-middle-control-cost-qa-v1-root-forward-153-001.json"
ROOT133_COST_RECEIPT = DATA_ROOT / "families/F3/F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT_133/f3-s2-owner-centered-dp015-full-cfd-canary-v8-root-133-001/execution-receipt.json"

V5_REQUEST = Path(__file__).with_name("stage2_f3_s2_external_solver_v5_request.py")
V5_MATERIALIZER = Path(__file__).with_name("stage2_f3_s2_external_solver_v5_materialize.py")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _small_record(path: Path, label: str, expected_sha: str | None = None) -> dict[str, Any]:
    record = _stat(path, label)
    if record["bytes"] > 2 * 1024 * 1024:
        raise ValueError(f"{label} exceeds bounded metadata limit: {record['bytes']} bytes")
    record.update({
        "label": label,
        "sha256": expected_sha or _sha256(path),
        "content_scope": "small_metadata_hashed_by_builder_and_parent",
        "content_read_by_builder": True,
    })
    return record


def _payload_record(path: Path, label: str, expected_sha: str | None, *, authority: str) -> dict[str, Any]:
    """Record payload stat only; never open the payload."""
    record = _stat(path, label)
    record.update({
        "label": label,
        "sha256": expected_sha,
        "sha256_required": True,
        "sha256_computed_by_builder": False,
        "content_scope": "parent_after_reservation_pre_post_hash",
        "content_read_by_builder": False,
        "sha_authority": authority,
    })
    return record


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def _receipt_identity(receipt: dict[str, Any]) -> tuple[str, str]:
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise ValueError("ROOT086 receipt has no request object")
    case_id = str(request.get("case_id", ""))
    physical = str(request.get("physical_case_id", ""))
    if not case_id or physical != PHYSICAL_CASE_ID:
        raise ValueError("ROOT086 receipt identity is not F3-S2 source-bound")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"}:
        raise ValueError("ROOT086 GenCase receipt is not completed")
    if receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT086 GenCase receipt is nonzero")
    root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if root != MIDDLE_ROOT.resolve():
        raise ValueError("ROOT086 receipt output root differs from bound generated source")
    return case_id, physical


def _producer_control_sha(receipt: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("input_hashes_at_launch", "input_hashes_after_run"):
        mapping = receipt.get(key)
        if not isinstance(mapping, dict):
            raise ValueError(f"ROOT086 receipt missing {key}")
        matches = [value for path, value in mapping.items() if isinstance(path, str) and Path(path).name == "CaseSloshingAccData.csv"]
        if len(matches) != 1 or not HEX64.fullmatch(str(matches[0])):
            raise ValueError(f"ROOT086 receipt does not expose one closed control SHA in {key}")
        values.append(str(matches[0]))
    if values[0] != values[1] or values[0] != SOURCE_CONTROL_SHA:
        raise ValueError("ROOT086/current control SHA is not the frozen 9a776... binding")
    return values[0]


def _support_status(report: dict[str, Any]) -> str:
    status = str(report.get("status", ""))
    if status != "COMPLETED_ROOT086_VTK_SUPPORT_SOURCE_CLOSED":
        raise ValueError(f"ROOT093 support status changed: {status}")
    if report.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("ROOT093 support physical identity differs")
    return status


def build_source_card(output: Path) -> dict[str, Any]:
    receipt = _load_json(MIDDLE_RECEIPT, "ROOT086 GenCase receipt")
    producer_case_id, _ = _receipt_identity(receipt)
    control_sha = _producer_control_sha(receipt)
    support = _load_json(MIDDLE_SUPPORT, "ROOT093 support report")
    support_status = _support_status(support)
    proof = _load_json(ROOT153_PROOF, "ROOT153 staging proof")
    report = _load_json(ROOT153_REPORT, "ROOT153 staging report")

    if _sha256(MIDDLE_XML) != MIDDLE_XML_SHA:
        raise ValueError("ROOT086 generated XML SHA differs from the ROOT153 source binding")
    if _sha256(SOURCE_XML) != SOURCE_XML_SHA:
        raise ValueError("F3 source XML SHA differs from the frozen source binding")
    # The forcing table is 14 MB.  Its SHA is already closed by the ROOT086
    # producer receipt and the ROOT093 source record; this builder deliberately
    # does not reopen either copy.  The parent v5 guard performs the actual
    # post-reservation pre/post content hash before materialization.
    if _stat(MIDDLE_CONTROL, "ROOT086 generated forcing CSV")["bytes"] != MIDDLE_CONTROL_BYTES:
        raise ValueError("ROOT086 generated control byte count changed")
    if _stat(SOURCE_CONTROL, "current forcing CSV")["bytes"] != MIDDLE_CONTROL_BYTES:
        raise ValueError("current source control byte count changed")
    if _sha256(MIDDLE_RECEIPT) != ROOT086_RECEIPT_SHA:
        raise ValueError("ROOT086 receipt SHA differs from the frozen producer binding")
    if _sha256(MIDDLE_SUPPORT) != ROOT093_SUPPORT_SHA:
        raise ValueError("ROOT093 support SHA differs from the frozen support binding")
    if _sha256(ROOT153_PROOF) != ROOT153_PROOF_SHA:
        raise ValueError("ROOT153 proof SHA differs from the frozen staging binding")
    if str(proof.get("status", "")) != "VERIFIED_ACTUAL_F3_MIDDLE_STAGING_INITIAL_XML_MASS_AND_COARSE_TIME_COST_METADATA_ONLY":
        raise ValueError("ROOT153 proof status is not the actual middle-staging proof")
    if str(report.get("status", "")) != "PASS_SOURCE_BOUND_METADATA_MIDDLE_STAGING_QA_NO_SOLVER":
        raise ValueError("ROOT153 report status is not the completed metadata QA")
    if report.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("ROOT153 report physical identity differs")

    card: dict[str, Any] = {
        "schema": "ds02.stage2.f3.s2.middle-external-v5-source-card.v1",
        "status": "SOURCE_READY_PENDING_PARENT_DYNAMIC_SHA",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": "F3_S2_MATCHED_MIDDLE_SAME_CFL_FULL_WINDOW",
        "source_read_scope": {
            "builder_reads_small_json_xml": True,
            "builder_reads_generated_bi4_payload": False,
            "builder_reads_forcing_payload": False,
            "builder_reads_native_part_or_hdf5": False,
            "generated_bi4_sha256": "PARENT_GUARD_COMPUTED_AFTER_RESERVATION",
            "forcing_sha256": control_sha,
            "dynamic_hashes_must_be_literal_lowercase_sha256_before_v5_request": True,
        },
        "producer": {
            "case_id": producer_case_id,
            "receipt": _small_record(MIDDLE_RECEIPT, "ROOT086 GenCase receipt", ROOT086_RECEIPT_SHA),
            "generated_xml": _small_record(MIDDLE_XML, "ROOT086 generated XML", MIDDLE_XML_SHA),
            "generated_bi4": _payload_record(MIDDLE_BI4, "ROOT086 generated BI4", None, authority="parent_guard_after_reservation"),
            "generated_forcing": _payload_record(MIDDLE_CONTROL, "ROOT086 generated forcing CSV", control_sha, authority="ROOT086 receipt launch/end and current source control"),
            "producer_output_immutable": True,
        },
        "support": {
            "report": _small_record(MIDDLE_SUPPORT, "ROOT093 VTK support report", ROOT093_SUPPORT_SHA),
            "status": support_status,
            "support_scope": "discrete owner-envelope/support evidence; no continuous no-penetration or flux credit",
            "fluid_count": MIDDLE_FLUID_COUNT,
            "fixed_count": MIDDLE_FIXED_COUNT,
            "sample_mass_kg": MIDDLE_SAMPLE_MASS_KG,
            "continuous_owner_mass_kg": OWNER_MASS_KG,
            "mass_rescale": False,
        },
        "staging": {
            "root153_proof": _small_record(ROOT153_PROOF, "ROOT153 middle staging proof", ROOT153_PROOF_SHA),
            "root153_report": _small_record(ROOT153_REPORT, "ROOT153 middle staging report"),
            "root153_request": _small_record(ROOT153_REQUEST, "ROOT153 metadata QA request"),
            "root153_report_sha256_bound": ROOT153_REPORT_SHA,
            "root153_actual_coarse_terminal_is_reference_only": True,
            "metadata_qa_solver_started": False,
        },
        "source_control": {
            "canonical_xml": _small_record(SOURCE_XML, "F3 current source XML", SOURCE_XML_SHA),
            "canonical_forcing": _payload_record(SOURCE_CONTROL, "F3 current forcing CSV", control_sha, authority="ROOT086 receipt and frozen source control"),
            "generated_forcing": _payload_record(MIDDLE_CONTROL, "ROOT086 generated forcing CSV", control_sha, authority="ROOT086 receipt and frozen source control"),
            "sha_equal_source_and_generated": True,
            "time_window_s": [0.0, float(TMAX)],
        },
        "solver_contract": {
            "solver_schema": "ds02.stage2.external-solver-request.v5",
            "same_cfl": True,
            "half_cfl_started": False,
            "window_s": [0.0, float(TMAX)],
            "tout_s": float(TOUT),
            "terminal_evidence_required": ["RunPARTs.csv", "Run.out", "DtAllInfo", "DTsMin", "actual_terminal_time", "native_input_pre_post_sha_stat"],
            "expected_native_frames": "UNKNOWN_UNTIL_TERMINAL_RUNPARTS",
            "storage_proxy_bytes": 6604181245,
            "storage_proxy_is_not_reservation_or_frame_guarantee": True,
            "external_reserve_bytes_recommended": 12 * 1024**3,
            "home_receipt_reserve_bytes_recommended": 16 * 1024**2,
            "max_wall_seconds_recommended": 3600,
            "estimated_peak_gpu_mib": 4096,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "continuous_equivalence": "UNKNOWN",
        },
        "finalization": {
            "requires_generated_bi4_sha256_cli": True,
            "requires_forcing_sha256_cli": True,
            "final_request_must_pass_shared_v5_validate_request": True,
            "final_request_top_level_status": "READY_FOR_PARENT_GUARD",
            "no_payload_hash_by_source_card_builder": True,
        },
    }
    card["sha256"] = _canonical(card)
    _write_once(output, card)
    return {"status": card["status"], "output": str(output.resolve()), "sha256": card["sha256"], "bi4_payload_read": False, "forcing_payload_read": False, "solver_started": False}


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("stage2_f3_middle_v5_delegate", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    for name, value in (("generated BI4 SHA", args.generated_bi4_sha256), ("forcing SHA", args.forcing_sha256)):
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            raise ValueError(f"{name} must be an explicit lowercase SHA-256 obtained by the parent guard")
    if args.forcing_sha256 != SOURCE_CONTROL_SHA:
        raise ValueError("forcing SHA does not match the ROOT086/current-control binding")
    receipt = _load_json(args.receipt, "ROOT086 GenCase receipt")
    producer_case_id, _ = _receipt_identity(receipt)
    support = _load_json(args.support_report, "ROOT093 support report")
    _support_status(support)

    delegate = _load_module(V5_REQUEST)
    delegate.FAMILY = FAMILY_ID
    delegate.SENTINEL = SENTINEL_ID
    delegate.PHYSICAL_CASE_ID = PHYSICAL_CASE_ID
    delegate.ROOT120_CASE = producer_case_id
    delegate.ROOT120_RECEIPT_ROOT = MIDDLE_ROOT
    delegate.DEFAULT_SOURCE_XML = SOURCE_XML
    delegate.DEFAULT_SOURCE_CONTROL = MIDDLE_CONTROL
    delegate.COST_BASIS_RECEIPT = ROOT133_COST_RECEIPT
    delegate.WRAPPER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_external_solver_v5_materialize.py"

    def support_status(report: dict[str, Any]) -> str:
        return _support_status(report)

    delegate._actual_support_status = support_status
    delegated = argparse.Namespace(**vars(args))
    delegated.source_control = args.source_control
    delegated.source_xml = args.source_xml
    delegated.cost_basis_receipt = args.cost_basis_receipt
    delegated.case_id = args.case_id
    delegated.attempt_id = args.attempt_id
    delegated.external_reserve_bytes = args.external_reserve_bytes
    delegated.home_receipt_reserve_bytes = args.home_receipt_reserve_bytes
    delegated.max_wall_seconds = args.max_wall_seconds
    delegated.output = args.output
    delegated.launch_commit = args.launch_commit
    # The consumed ROOT086 receipt records the attempt root, while GenCase
    # placed its generated XML/BI4/control under ``<root>/generated``.  The
    # old generic V5 builder required direct children of its receipt root.
    # Give that immutable delegate an ephemeral metadata-only receipt view
    # with the actual generated directory as output root, then restore the
    # real receipt path in the emitted request.  No producer bytes or receipt
    # are modified, and the final request still hashes/binds the real receipt.
    actual_receipt_path = _regular(args.receipt, "ROOT086 GenCase receipt")
    actual_receipt_value = dict(receipt)
    actual_receipt_value["output_root"] = str(Path(args.generated_xml).expanduser().resolve().parent)
    temp_receipt = Path(f"/tmp/ds02-f3-middle-v5-delegate-receipt-{os.getpid()}.json")
    if temp_receipt.exists() or temp_receipt.is_symlink():
        raise FileExistsError(f"temporary delegate receipt already exists: {temp_receipt}")
    with temp_receipt.open("x", encoding="utf-8") as stream:
        json.dump(actual_receipt_value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    # ROOT133's v5 receipt keeps terminal product bytes under
    # ``filesystem.external_product_bytes`` rather than the legacy top-level
    # ``bytes`` field expected by the old generic builder.  Use a temporary
    # metadata view only for that delegate's numeric cost check; the emitted
    # request is rebound to the immutable ROOT133 receipt below.
    actual_cost_path = _regular(args.cost_basis_receipt, "ROOT133 cost-basis receipt")
    actual_cost_value = _load_json(actual_cost_path, "ROOT133 cost-basis receipt")
    filesystem = actual_cost_value.get("filesystem")
    if not isinstance(filesystem, dict) or int(filesystem.get("external_product_bytes", 0) or 0) <= 0:
        raise ValueError("ROOT133 cost-basis receipt has no positive external product bytes")
    temp_cost_receipt = Path(f"/tmp/ds02-f3-middle-v5-cost-{os.getpid()}.json")
    if temp_cost_receipt.exists() or temp_cost_receipt.is_symlink():
        raise FileExistsError(f"temporary cost receipt already exists: {temp_cost_receipt}")
    actual_cost_value["bytes"] = int(filesystem["external_product_bytes"])
    with temp_cost_receipt.open("x", encoding="utf-8") as stream:
        json.dump(actual_cost_value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    delegated.receipt = temp_receipt
    delegated.cost_basis_receipt = temp_cost_receipt
    try:
        result = delegate.build(delegated)
    finally:
        temp_receipt.unlink(missing_ok=True)
        temp_cost_receipt.unlink(missing_ok=True)
    request = json.loads(Path(args.output).read_text(encoding="utf-8"))
    if request.get("schema") != "ds02.stage2.external-solver-request.v5" or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ValueError("delegated request is not strict shared-v5 schema/status")
    request["request_variant_schema"] = "ds02.stage2.f3.s2.middle-external-solver-request.v1"
    request["request_variant_status"] = "READY_FOR_PARENT_GUARD_AFTER_ROOT153_AND_PARENT_DYNAMIC_SHA"
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    temp_receipt_text = str(temp_receipt.resolve())
    real_receipt_text = str(actual_receipt_path.resolve())
    request["input_files"] = [real_receipt_text if item == temp_receipt_text else item for item in request.get("input_files", [])]
    request["input_sha256"] = dict(request.get("input_sha256", {}))
    temp_hash = request["input_sha256"].pop(temp_receipt_text, None)
    request["input_sha256"][real_receipt_text] = _sha256(actual_receipt_path)
    request["input_content_scope"] = dict(request.get("input_content_scope", {}))
    temp_scope = request["input_content_scope"].pop(temp_receipt_text, None)
    request["input_content_scope"][real_receipt_text] = temp_scope or "small_metadata_hashed_by_builder_and_parent"
    temp_cost_text = str(temp_cost_receipt.resolve())
    real_cost_text = str(actual_cost_path.resolve())
    request["input_files"] = [real_cost_text if item == temp_cost_text else item for item in request.get("input_files", [])]
    temp_cost_hash = request["input_sha256"].pop(temp_cost_text, None)
    request["input_sha256"][real_cost_text] = _sha256(actual_cost_path)
    temp_cost_scope = request["input_content_scope"].pop(temp_cost_text, None)
    request["input_content_scope"][real_cost_text] = temp_cost_scope or "small_metadata_hashed_by_builder_and_parent"
    basis = request.get("storage_scope", {}).get("reservation_basis", {})
    if isinstance(basis, dict):
        basis["actual_cost_basis_receipt"] = real_cost_text
        basis["actual_cost_basis_receipt_sha256"] = _sha256(actual_cost_path)
        basis["actual_cost_basis_terminal_bytes"] = int(filesystem["external_product_bytes"])
    request["source_provenance"]["gencase_receipt"] = real_receipt_text
    request["source_provenance"]["gencase_output_root"] = str(MIDDLE_ROOT.resolve())
    request["source_provenance"].update({
        "producer_label": "ROOT086_MIDDLE_DP006",
        "root093_support_report": str(args.support_report),
        "root153_staging_proof": str(ROOT153_PROOF),
        "root153_staging_report": str(ROOT153_REPORT),
        "continuous_owner_mass_kg": OWNER_MASS_KG,
        "sample_mass_kg": MIDDLE_SAMPLE_MASS_KG,
        "continuous_equivalence": "UNKNOWN",
        "mass_rescale": False,
        "generated_bi4_sha256_source": "parent_guard_after_reservation",
        "forcing_sha256_source": "ROOT086_receipt_and_frozen_current_control",
        "old_root120_labels_in_delegate": "forward adapter uses middle ROOT086 producer; no ROOT120 producer is claimed",
    })
    for key, label in (("generated_bi4", "ROOT086 generated BI4"), ("generated_xml", "ROOT086 generated XML")):
        if isinstance(request["source_provenance"].get(key), dict):
            request["source_provenance"][key]["label"] = label
    if isinstance(request["source_provenance"].get("source_control"), dict):
        request["source_provenance"]["source_control"]["sha_authority"] = "ROOT086_receipt_input_hashes_at_launch_and_after_run"
    request["source_provenance"]["producer_output_immutable"] = True
    request["source_provenance"].pop("root120_output_immutable", None)
    request["solver_plan"] = {
        "grid": "middle_dp0.006",
        "cfl_mode": "same_cfl",
        "window_s": [0.0, float(TMAX)],
        "tout_s": float(TOUT),
        "terminal_time_source": "RunPARTs/Run.out/DtAllInfo only",
        "native_frames": "UNKNOWN_UNTIL_TERMINAL",
        "no_endpoint_extrapolation": True,
        "half_cfl_separate_request": True,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    # Ensure source card evidence is carried in input closure without reading
    # native payloads.  The parent can regenerate this adapter in the primary
    # worktree, where all paths and code SHAs are authoritative.
    for path, label, expected in ((ROOT153_PROOF, "ROOT153 middle staging proof", ROOT153_PROOF_SHA), (ROOT153_REPORT, "ROOT153 middle staging report", ROOT153_REPORT_SHA)):
        record = _small_record(path, label, expected)
        request.setdefault("input_files", []).append(record["path"])
        request.setdefault("input_sha256", {})[record["path"]] = record["sha256"]
        request.setdefault("input_content_scope", {})[record["path"]] = record["content_scope"]
    request["input_files"] = sorted(set(request["input_files"]))
    request["sha256"] = _canonical(request)
    # The delegated writer has already created the output.  Rewrite is only
    # allowed here in-memory to the same newly-created path; an existing
    # request from an earlier run is rejected before delegate.build().
    Path(args.output).write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {
        "status": "PASS_STRICT_V5_REQUEST_BUILT",
        "output": str(Path(args.output).resolve()),
        "request_sha256": request["sha256"],
        "generated_bi4_sha256": args.generated_bi4_sha256,
        "forcing_sha256": args.forcing_sha256,
        "forcing_sha256_authority": "ROOT086_receipt_and_frozen_current_control",
        "solver_started": False,
        "payload_read_by_builder": False,
    }


def self_test() -> dict[str, Any]:
    if str(PYTHON) != "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python":
        raise AssertionError("literal venv binding changed")
    if TMAX != "8.350016881886734" or TOUT != "0.01":
        raise AssertionError("F3 middle window/cadence changed")
    if not HEX64.fullmatch(SOURCE_CONTROL_SHA):
        raise AssertionError("frozen forcing SHA malformed")
    if MIDDLE_BI4_BYTES <= 0 or MIDDLE_CONTROL_BYTES <= 0:
        raise AssertionError("middle payload metadata missing")
    return {"status": "PASS", "schema": "ds02.stage2.f3.s2.middle-external-v5-source-card.v1", "bi4_payload_read": False, "forcing_payload_read": False, "solver_started": False, "strict_v5_finalization_requires_real_parent_hashes": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-source-card", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, required=False, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-external-v5-source-card-v1.json")
    parser.add_argument("--gencase-request", type=Path, default=PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-source-clone-gencase-v1-root-forward-082-001/f3-s2-source-clone-gencase-v1-request.json")
    parser.add_argument("--receipt", type=Path, default=MIDDLE_RECEIPT)
    parser.add_argument("--generated-xml", type=Path, default=MIDDLE_XML)
    parser.add_argument("--generated-bi4", type=Path, default=MIDDLE_BI4)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--source-xml", type=Path, default=SOURCE_XML)
    parser.add_argument("--source-control", type=Path, default=MIDDLE_CONTROL)
    parser.add_argument("--forcing-sha256", default=SOURCE_CONTROL_SHA)
    parser.add_argument("--support-report", type=Path, default=MIDDLE_SUPPORT)
    parser.add_argument("--cost-basis-receipt", type=Path, default=ROOT133_COST_RECEIPT)
    parser.add_argument("--launch-commit", default=None)
    parser.add_argument("--case-id", default="F3_S2_MATCHED_MIDDLE_SAME_CFL_FULL_WINDOW")
    parser.add_argument("--attempt-id", default="f3-s2-matched-middle-same-cfl-full-window-v5-root-155-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=12 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=16 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=3600.0)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.build_source_card:
        print(json.dumps(build_source_card(args.output), ensure_ascii=False, indent=2)); return 0
    required = (args.gencase_request, args.receipt, args.generated_xml, args.generated_bi4, args.generated_bi4_sha256, args.source_xml, args.source_control, args.support_report, args.cost_basis_receipt, args.launch_commit)
    if any(value is None for value in required):
        parser.error("--build-request requires q/receipt/generated XML+BI4/BI4 SHA/source/support/cost/launch commit")
    print(json.dumps(build_request(args), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
